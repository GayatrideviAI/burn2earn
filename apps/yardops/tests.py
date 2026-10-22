from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.customers.models import CustomerMember, JobRole, StockCount
from apps.customers.tests import StockCase, make_batch, make_pile, make_yard
from apps.ledger.chain import entries_for, verify

from . import risk, services
from .models import HeatReading, RiskAlert, YardOperator

D = Decimal


class RiskCase(StockCase):
    def heat(self, temp, hours_ago=0, spot="", pile=None):
        return services.record_heat(
            pile or self.pile, D(str(temp)), taken_at=timezone.now() - timedelta(hours=hours_ago), spot=spot, taken_by="Test"
        )

    def level(self, pile=None):
        return risk.assess(pile or self.pile).level


class RiskRuleTests(RiskCase):
    def test_a_pile_with_no_stock_is_not_assessed(self):
        empty = make_pile(self.pile.yard, "E-01")
        result = risk.assess(empty)
        self.assertFalse(result.has_stock)
        self.assertEqual(result.level, risk.OK)

    def test_a_pile_never_probed_is_not_shown_as_safe(self):
        result = risk.assess(self.pile)
        self.assertEqual(result.level, risk.ATTENTION)
        self.assertIn("No temperature reading has been taken yet", result.top_reason)

    def test_a_cool_fresh_reading_is_normal(self):
        self.heat(38)
        self.assertEqual(self.level(), risk.OK)

    def test_the_temperature_steps(self):
        for temp, expected in ((49, risk.OK), (50, risk.ATTENTION), (65, risk.WATCH), (70, risk.ACT), (80, risk.EMERGENCY)):
            with self.subTest(temp=temp):
                HeatReading.objects.all().delete()
                self.heat(temp)
                self.assertEqual(self.level(), expected)

    def test_a_fast_rise_is_flagged_even_below_the_steps(self):
        self.heat(38, hours_ago=48)
        self.heat(47, hours_ago=0)
        result = risk.assess(self.pile)
        self.assertEqual(result.level, risk.WATCH)
        self.assertGreaterEqual(result.rise_per_day, 3)

    def test_a_slow_rise_gives_an_estimate_not_an_alarm(self):
        self.heat(30, hours_ago=144)
        self.heat(45, hours_ago=0)
        result = risk.assess(self.pile)
        self.assertEqual(result.level, risk.OK)
        self.assertAlmostEqual(result.days_to_watch, 8, delta=1.5)
        self.assertIn("reaches 65", result.projection)

    def test_readings_close_together_make_no_trend(self):
        self.heat(40, hours_ago=1)
        self.heat(46, hours_ago=0)
        self.assertIsNone(risk.assess(self.pile).rise_per_day)

    def test_an_old_reading_is_flagged_as_not_checked(self):
        self.heat(40, hours_ago=24 * 5)
        result = risk.assess(self.pile)
        self.assertEqual(result.level, risk.ATTENTION)
        self.assertIn("No temperature reading for 5 days", result.top_reason)

    def test_an_old_hot_reading_still_counts(self):
        self.heat(66, hours_ago=24 * 5)
        self.assertEqual(self.level(), risk.WATCH)

    def test_the_hottest_spot_decides(self):
        self.heat(40, spot="south")
        self.heat(66, spot="north")
        self.assertEqual(self.level(), risk.WATCH)

    def test_a_newer_cool_reading_at_the_same_spot_replaces_a_hot_one(self):
        self.heat(66, hours_ago=5, spot="north")
        self.heat(45, hours_ago=0, spot="north")
        self.assertEqual(self.level(), risk.OK)

    def test_inspection_findings_count_until_a_newer_inspection(self):
        self.heat(40)
        services.record_inspection(self.pile, steam_or_smell=True, inspected_at=timezone.now() - timedelta(hours=3))
        self.assertEqual(self.level(), risk.ACT)
        services.record_inspection(self.pile, inspected_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.level(), risk.OK)

    def test_a_wet_stack_and_missing_cover_are_flagged(self):
        self.heat(40)
        services.record_inspection(self.pile, looks_wet=True, inspected_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(self.level(), risk.WATCH)
        services.record_inspection(self.pile, cover_in_place=False, inspected_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.level(), risk.ATTENTION)

    def test_stacking_damp_or_too_tall_is_flagged(self):
        damp = make_pile(self.pile.yard, "D-01")
        make_batch(self.buyer, damp, "50", "25")
        self.heat(40, pile=damp)
        self.assertIn("Stacked damp", risk.assess(damp).top_reason)
        self.heat(40)
        services.update_pile_size(self.pile, height_m=D("5.5"))
        self.assertIn("above the 4 m limit", risk.assess(self.pile).top_reason)

    def test_spark_points_need_two_readings(self):
        self.heat(40, hours_ago=10)
        self.assertEqual(risk.spark_points(HeatReading.objects.all()), "")
        self.heat(50, hours_ago=0)
        self.assertEqual(len(risk.spark_points(HeatReading.objects.all()).split()), 2)

    def test_use_first_ranks_risk_before_age(self):
        hot = make_pile(self.pile.yard, "H-01")
        make_batch(self.buyer, hot, "10", "14")
        self.heat(40)
        self.heat(72, pile=hot)
        ranked = [a.pile.label for a in risk.use_first(self.buyer)]
        self.assertEqual(ranked[0], "H-01")


class ValidationTests(RiskCase):
    def test_an_impossible_temperature_is_refused(self):
        with self.assertRaises(ValidationError):
            self.heat(500)

    def test_a_reading_cannot_be_in_the_future(self):
        with self.assertRaises(ValidationError):
            self.heat(40, hours_ago=-3)

    def test_an_inactive_pile_takes_no_readings(self):
        self.pile.status = "inactive"
        self.pile.save()
        with self.assertRaises(ValidationError):
            self.heat(40)


class AlertTests(RiskCase):
    def open(self):
        return list(RiskAlert.objects.filter(resolved_at__isnull=True))

    def test_nothing_is_raised_below_watch(self):
        self.heat(55)
        self.assertEqual(RiskAlert.objects.count(), 0)

    def test_a_hot_reading_raises_one_alert_with_a_ledger_entry(self):
        self.heat(66)
        self.heat(67)
        alerts = self.open()
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertTrue(alert.code.startswith("ALR-"))
        self.assertEqual(alert.level, "watch")
        self.assertIn("66", alert.reasons)
        self.assertEqual([e.entry_type for e in entries_for(alert)], ["yard.alert.raised"])
        self.assertTrue(alert.ledger_seq)

    def test_a_hotter_reading_escalates_and_closes_the_old_alert(self):
        self.heat(66, hours_ago=2)
        self.heat(71, hours_ago=0, spot="other")
        alerts = self.open()
        self.assertEqual([a.level for a in alerts], ["act"])
        self.assertEqual(RiskAlert.objects.count(), 2)

    def test_cooling_down_closes_the_alert(self):
        self.heat(66, hours_ago=2)
        self.heat(45, hours_ago=0)
        self.assertEqual(self.open(), [])
        self.assertTrue(RiskAlert.objects.get().resolved_at)

    def test_acknowledging_records_who_and_how_fast(self):
        self.heat(66)
        alert = self.open()[0]
        alert.raised_at = timezone.now() - timedelta(minutes=12)
        alert.save()
        user = User.objects.create_user(username="sup", password="x", role=Role.YARD)
        services.acknowledge(alert, user, note="Opened the stack")
        alert.refresh_from_db()
        self.assertEqual(alert.acknowledged_by, user)
        self.assertEqual(alert.response_minutes, 12)
        self.assertIn("Opened the stack", alert.note)
        self.assertIn("yard.alert.acknowledged", [e.entry_type for e in entries_for(alert)])
        stamp = alert.acknowledged_at
        services.acknowledge(alert, user)  # a second tap changes nothing
        alert.refresh_from_db()
        self.assertEqual(alert.acknowledged_at, stamp)

    def test_a_closed_alert_cannot_be_acknowledged(self):
        self.heat(66, hours_ago=2)
        self.heat(45)
        alert = RiskAlert.objects.get()
        user = User.objects.create_user(username="sup", password="x", role=Role.YARD)
        with self.assertRaises(ValidationError):
            services.acknowledge(alert, user)

    def test_an_alert_not_acknowledged_in_time_is_overdue(self):
        self.heat(66)
        alert = self.open()[0]
        self.assertFalse(services.overdue(alert))
        alert.raised_at = timezone.now() - timedelta(minutes=45)
        self.assertTrue(services.overdue(alert))

    def test_readings_and_alerts_keep_the_ledger_intact(self):
        self.heat(66)
        self.heat(40, hours_ago=1, spot="other")
        self.assertTrue(verify().ok)


class YardPagesTests(RiskCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="yard1", password="pw-12345-x", role=Role.YARD)
        self.operator = YardOperator.objects.create(user=self.user, name="Gurdeep")
        self.operator.yards.add(self.pile.yard)
        self.client.login(username="yard1", password="pw-12345-x")
        self.pile_url = reverse("yardops:pile", args=[self.pile.pk])

    def post(self, action, data):
        return self.client.post(self.pile_url, {"action": action, **{f"{action}-{k}": v for k, v in data.items()}}, follow=True)

    def test_anonymous_goes_to_the_yard_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(reverse("yardops:home")), f"{reverse('yardops:login')}?next={reverse('yardops:home')}")

    def test_login_leads_to_the_yard_home(self):
        self.client.logout()
        response = self.client.post(reverse("yardops:login"), {"username": "yard1", "password": "pw-12345-x"}, follow=True)
        self.assertContains(response, "Yard check")
        self.assertContains(response, self.pile.label)

    def test_other_logins_are_refused(self):
        self.client.logout()
        User.objects.create_user(username="adm", password="pw-12345-x", role=Role.ADMIN)
        self.client.login(username="adm", password="pw-12345-x")
        self.assertEqual(self.client.get(reverse("yardops:home")).status_code, 403)

    def test_a_yard_operator_is_sent_here_from_the_mitra_pages_and_refused_the_customer_pages(self):
        self.assertRedirects(self.client.get(reverse("field:dashboard")), reverse("yardops:home"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("customers:dashboard")).status_code, 403)

    def test_only_piles_in_the_operators_yards_open(self):
        other = make_pile(make_yard("Yard Z"), "Z-01")
        self.assertEqual(self.client.get(reverse("yardops:pile", args=[other.pk])).status_code, 404)

    def test_logging_a_temperature_saves_and_raises_an_alert(self):
        response = self.post("heat", {"temperature_c": "67.5", "spot": "north", "depth_cm": "100"})
        self.assertContains(response, "Temperature saved")
        reading = HeatReading.objects.get()
        self.assertEqual((reading.temperature_c, reading.taken_by, reading.depth_cm), (D("67.5"), "Gurdeep", 100))
        self.assertContains(self.client.get(reverse("yardops:home")), "Watch closely")

    def test_a_bad_temperature_shows_an_error(self):
        response = self.post("heat", {"temperature_c": "900"})
        self.assertEqual(HeatReading.objects.count(), 0)
        self.assertContains(response, "Ensure this value is less than or equal to 200")

    def test_logging_an_inspection(self):
        self.post("inspect", {"steam_or_smell": "on", "cover_in_place": "on", "notes": "Smells burnt"})
        self.assertEqual(self.level(), risk.ACT)

    def test_a_count_and_a_moisture_reading_feed_the_stock_figures(self):
        self.post("count", {"batch": self.batch.pk, "tonnes": "98.5", "method": "audit"})
        count = StockCount.objects.get(batch=self.batch)
        self.assertEqual((count.counted_tonnes, count.counted_by), (D("98.5"), "Gurdeep"))
        self.post("moisture", {"batch": self.batch.pk, "percent": "13.5", "method": "handheld meter"})
        self.assertEqual(self.batch.quality.filter(tested_by="Gurdeep").get().moisture_percent, D("13.5"))

    def test_pile_size_can_be_saved(self):
        self.post("size", {"height_m": "3.5", "length_m": "10", "width_m": "6", "cover_type": "Tarp"})
        self.pile.refresh_from_db()
        self.assertEqual((self.pile.height_m, self.pile.cover_type), (D("3.5"), "Tarp"))

    def test_acknowledging_from_the_page(self):
        self.heat(66)
        alert = RiskAlert.objects.get()
        response = self.client.post(reverse("yardops:acknowledge", args=[alert.pk]), follow=True)
        self.assertContains(response, "Alert acknowledged")
        alert.refresh_from_db()
        self.assertEqual(alert.acknowledged_by, self.user)

    def test_an_alert_in_another_yard_cannot_be_acknowledged(self):
        other = make_pile(make_yard("Yard Z"), "Z-01")
        make_batch(self.buyer, other, "10", "14")
        self.heat(66, pile=other)
        alert = RiskAlert.objects.get()
        self.assertEqual(self.client.post(reverse("yardops:acknowledge", args=[alert.pk])).status_code, 404)

    def test_the_pile_page_explains_the_flag(self):
        self.heat(72)
        page = self.client.get(self.pile_url)
        self.assertContains(page, "Why this is flagged")
        self.assertContains(page, "Check twice a day")

    def level(self):
        return risk.assess(self.pile).level


class CustomerViewTests(RiskCase):
    def setUp(self):
        super().setUp()
        user = User.objects.create_user(username="cust1", password="pw-12345-x", role=Role.BUYER)
        CustomerMember.objects.create(user=user, buyer=self.buyer, job_role=JobRole.OPERATIONS)
        self.client.login(username="cust1", password="pw-12345-x")

    def test_the_dashboard_shows_pile_risk_and_use_first(self):
        self.heat(72)
        page = self.client.get(reverse("customers:dashboard"))
        self.assertContains(page, "Use first")
        self.assertContains(page, "Check twice a day")
        self.assertContains(page, "above")

    def test_an_unprobed_pile_shows_as_needing_attention(self):
        self.assertContains(self.client.get(reverse("customers:dashboard")), "Needs attention")

    def test_the_yard_and_batch_pages_show_risk_and_temperatures(self):
        self.heat(55, hours_ago=30)
        self.heat(58, hours_ago=0)
        self.assertContains(self.client.get(reverse("customers:yard", args=[self.pile.yard.pk])), "Fire and spoilage risk")
        page = self.client.get(reverse("customers:batch", args=[self.batch.pk]))
        self.assertContains(page, "Pile temperature and risk")
        self.assertContains(page, "58 °C")
        self.assertContains(page, "<polyline")

    def test_nothing_shows_for_other_companies_piles(self):
        from apps.demand.tests import make_buyer

        other = make_buyer(company_name="Other Ltd")
        make_batch(other, make_pile(make_yard("Yard Q"), "Q-01"), "10", "14")
        text = self.client.get(reverse("customers:dashboard")).content.decode()
        self.assertNotIn("Q-01", text)
