from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.demand.tests import make_buyer, make_factory
from apps.ledger.chain import entries_for, verify
from apps.reference.models import BiomassType

from . import services
from .models import Batch, CustomerMember, JobRole, PlantProfile, Pile, Stockyard, TransactionKind

D = Decimal


def make_yard(name="Yard A"):
    return Stockyard.objects.create(name=name, location=Point(76.9, 30.1, srid=4326))


def make_pile(yard=None, label="A-01", exposure="open"):
    return Pile.objects.create(yard=yard or make_yard(), label=label, form="bales", exposure=exposure)


def make_batch(customer, pile, tonnes="100", moisture="14", **extra):
    batch = Batch.objects.create(
        customer=customer, pile=pile, biomass_type=BiomassType.objects.get(name="Paddy straw"), form="bales",
        intake_tonnes=D(tonnes), intake_moisture_percent=None if moisture is None else D(moisture), **extra,
    )
    services.receive_batch(batch)
    return batch


class StockCase(TestCase):
    def setUp(self):
        self.buyer = make_buyer()
        self.plant = make_factory(self.buyer, maximum_moisture_percent=D("18"))
        PlantProfile.objects.create(factory=self.plant, daily_consumption_tonnes=D("10"))
        self.pile = make_pile()
        self.batch = make_batch(self.buyer, self.pile, "100", "14")


class ReceiptAndMovementTests(StockCase):
    def test_a_new_batch_gets_a_code_a_receipt_and_an_intake_reading(self):
        self.assertEqual(self.batch.code, "BAT-000001")
        self.assertEqual(services.book_tonnes(self.batch), D("100"))
        self.assertEqual(self.batch.quality.get().moisture_percent, D("14"))
        self.assertEqual([e.entry_type for e in entries_for(self.batch)], ["stock.receipt", "quality.observed"])

    def test_burning_loss_and_return_take_stock_away(self):
        services.record_transaction(self.batch, TransactionKind.CONSUMPTION, D("30"))
        services.record_transaction(self.batch, TransactionKind.LOSS, D("5"), loss_cause="rain")
        services.record_transaction(self.batch, TransactionKind.RETURN, D("10"))
        self.assertEqual(services.book_tonnes(self.batch), D("55"))

    def test_book_stock_cannot_go_below_zero(self):
        with self.assertRaises(ValidationError):
            services.record_transaction(self.batch, TransactionKind.CONSUMPTION, D("101"))

    def test_a_loss_needs_a_cause(self):
        with self.assertRaises(ValidationError):
            services.record_transaction(self.batch, TransactionKind.LOSS, D("1"))

    def test_weights_must_be_positive_except_adjustments(self):
        with self.assertRaises(ValidationError):
            services.record_transaction(self.batch, TransactionKind.CONSUMPTION, D("-1"))
        services.record_transaction(self.batch, TransactionKind.ADJUSTMENT, D("-4"), note="Recount")
        services.record_transaction(self.batch, TransactionKind.ADJUSTMENT, D("2"))
        self.assertEqual(services.book_tonnes(self.batch), D("98"))
        with self.assertRaises(ValidationError):
            services.record_transaction(self.batch, TransactionKind.ADJUSTMENT, D("0"))

    def test_moving_to_another_pile_keeps_the_quantity(self):
        other = make_pile(self.pile.yard, "A-02")
        services.record_transaction(self.batch, TransactionKind.TRANSFER, to_pile=other)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.pile, other)
        self.assertEqual(services.book_tonnes(self.batch), D("100"))
        with self.assertRaises(ValidationError):
            services.record_transaction(self.batch, TransactionKind.TRANSFER, to_pile=other)
        with self.assertRaises(ValidationError):
            services.record_transaction(self.batch, TransactionKind.TRANSFER)

    def test_every_movement_is_on_the_ledger_and_the_chain_holds(self):
        row = services.record_transaction(self.batch, TransactionKind.LOSS, D("5"), loss_cause="rain")
        self.assertIsNotNone(row.ledger_seq)
        services.record_count(self.batch, D("95"), "audit")
        result = verify()
        self.assertTrue(result.ok, result.problem)


class CountAndConfidenceTests(StockCase):
    def view(self):
        return services.batch_view(self.batch, limit=D("18"))

    def test_an_uncounted_batch_is_calculated_and_not_usable(self):
        v = self.view()
        self.assertEqual((v.confidence, v.physical, v.usable), ("Calculated", None, D("0")))

    def test_a_recent_count_makes_it_verified_and_usable(self):
        services.record_count(self.batch, D("96"), "weighbridge")
        v = self.view()
        self.assertEqual((v.confidence, v.physical, v.usable, v.gap), ("Verified", D("96"), D("96"), D("-4")))

    def test_a_survey_is_only_an_estimate(self):
        services.record_count(self.batch, D("96"), "survey")
        self.assertEqual(self.view().confidence, "Estimated")

    def test_an_old_count_is_overdue(self):
        services.record_count(self.batch, D("96"), "audit", counted_on=date.today() - timedelta(days=20))
        self.assertEqual(self.view().confidence, "Overdue")

    def test_movements_after_a_count_roll_the_physical_figure_forward(self):
        services.record_count(self.batch, D("96"), "audit")
        tomorrow = timezone.now() + timedelta(days=1)
        services.record_transaction(self.batch, TransactionKind.CONSUMPTION, D("10"), occurred_at=tomorrow)
        self.assertEqual(self.view().physical, D("86"))

    def test_moisture_over_the_limit_is_not_usable(self):
        services.record_quality(self.batch, moisture_percent=D("19.5"))
        services.record_count(self.batch, D("96"), "audit")
        v = self.view()
        self.assertEqual((v.quality, v.usable), ("over_limit", D("0")))

    def test_an_estimate_does_not_count_as_a_moisture_reading(self):
        b = make_batch(self.buyer, self.pile, "10", moisture=None)
        services.record_quality(b, moisture_percent=D("10"), basis="estimated")
        services.record_count(b, D("10"), "audit")
        self.assertEqual(services.batch_view(b, limit=D("18")).quality, "no_reading")

    def test_with_no_plant_limit_a_counted_batch_is_usable(self):
        services.record_count(self.batch, D("96"), "audit")
        self.assertEqual(services.batch_view(self.batch, limit=None).usable, D("96"))

    def test_a_quality_reading_needs_at_least_one_value(self):
        with self.assertRaises(ValidationError):
            services.record_quality(self.batch)


class ReservationAndSummaryTests(StockCase):
    def setUp(self):
        super().setUp()
        services.record_count(self.batch, D("100"), "audit")

    def test_reserved_stock_is_not_available(self):
        services.reserve(self.batch, self.plant, D("40"))
        v = services.batch_view(self.batch, limit=D("18"))
        self.assertEqual((v.usable, v.reserved, v.available), (D("100"), D("40"), D("60")))

    def test_cannot_reserve_more_than_is_free_or_for_another_company(self):
        services.reserve(self.batch, self.plant, D("90"))
        with self.assertRaises(ValidationError):
            services.reserve(self.batch, self.plant, D("20"))
        other_plant = make_factory(make_buyer(company_name="Other Ltd"), name="Other plant")
        with self.assertRaises(ValidationError):
            services.reserve(self.batch, other_plant, D("1"))

    def test_fuel_cover_is_available_stock_over_daily_burn(self):
        services.reserve(self.batch, self.plant, D("30"))
        s = services.summary(self.buyer)
        self.assertEqual((s.book, s.physical, s.usable, s.reserved, s.available), (D("100"), D("100"), D("100"), D("30"), D("70")))
        self.assertEqual(s.fuel_cover_days, D("7.0"))  # 70 t at 10 t a day

    def test_low_fuel_cover_raises_an_action(self):
        titles = [a[1] for a in services.summary(self.buyer).actions]
        self.assertIn("Low fuel cover", titles)  # 10 days is under the 14-day lead time

    def test_actions_flag_overdue_counts_missing_readings_and_gaps(self):
        old = make_batch(self.buyer, make_pile(self.pile.yard, "A-02"), "50", moisture=None)
        services.record_count(old, D("45"), "audit", counted_on=date.today() - timedelta(days=30))
        titles = [a[1] for a in services.summary(self.buyer).actions]
        for expected in ("Verification overdue", "Check moisture", "Reconcile"):
            self.assertIn(expected, titles)

    def test_one_company_never_sees_anothers_stock(self):
        other = make_buyer(company_name="Other Ltd")
        make_batch(other, make_pile(make_yard("Yard Z"), "Z-01"), "500")
        self.assertEqual(services.summary(self.buyer).book, D("100"))
        self.assertEqual(services.summary(other).book, D("500"))

    def test_exposed_stock_is_what_sits_in_open_piles(self):
        make_batch(self.buyer, make_pile(self.pile.yard, "A-02", exposure="protected"), "40")
        s = services.summary(self.buyer)
        self.assertEqual((s.book, s.exposed), (D("140"), D("100")))


class PageTests(StockCase):
    def setUp(self):
        super().setUp()
        services.record_count(self.batch, D("100"), "audit")
        self.user = User.objects.create_user(username="cust1", password="pw-12345-x", role=Role.BUYER)
        CustomerMember.objects.create(user=self.user, buyer=self.buyer, job_role=JobRole.OPERATIONS)

    def login(self):
        self.assertTrue(self.client.login(username="cust1", password="pw-12345-x"))

    def test_login_leads_to_the_overview(self):
        response = self.client.post(reverse("customers:login"), {"username": "cust1", "password": "pw-12345-x"}, follow=True)
        self.assertContains(response, "Stock overview")
        self.assertContains(response, "Fuel cover")

    def test_overview_yard_and_batch_pages_show_the_stock(self):
        self.login()
        self.assertContains(self.client.get(reverse("customers:dashboard")), "Yard A")
        self.assertContains(self.client.get(reverse("customers:yard", args=[self.pile.yard.pk])), self.batch.code)
        page = self.client.get(reverse("customers:batch", args=[self.batch.pk]))
        self.assertContains(page, "stock.receipt")
        self.assertContains(page, "Physical counts")

    def test_anonymous_visitors_are_sent_to_log_in(self):
        response = self.client.get(reverse("customers:dashboard"))
        self.assertRedirects(response, "/customer/login/?next=/customer/", fetch_redirect_response=False)

    def test_a_mitra_login_gets_a_403(self):
        User.objects.create_user(username="m1", password="pw-12345-x", role=Role.MITRA)
        self.client.login(username="m1", password="pw-12345-x")
        self.assertEqual(self.client.get(reverse("customers:dashboard")).status_code, 403)

    def test_a_customer_is_sent_from_the_mitra_pages_to_their_own(self):
        self.login()
        self.assertRedirects(self.client.get("/mitra/"), reverse("customers:dashboard"), fetch_redirect_response=False)

    def test_a_customer_cannot_open_another_companys_batch_or_yard(self):
        other = make_buyer(company_name="Other Ltd")
        theirs = make_batch(other, make_pile(make_yard("Yard Z"), "Z-01"), "500")
        self.login()
        self.assertEqual(self.client.get(reverse("customers:batch", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("customers:yard", args=[theirs.pile.yard.pk])).status_code, 404)

    def test_a_deactivated_member_loses_access(self):
        self.user.customer_member.deactivate()
        self.login()
        self.assertEqual(self.client.get(reverse("customers:dashboard")).status_code, 403)


class AdminTests(StockCase):
    def setUp(self):
        super().setUp()
        self.boss = User.objects.create_superuser(username="boss", password="pw-12345-x")
        self.client.force_login(self.boss)

    def test_admin_pages_open(self):
        for model in ("customermember", "plantprofile", "stockyard", "pile", "batch", "inventorytransaction", "stockcount", "qualityobservation", "reservation"):
            self.assertEqual(self.client.get(f"/admin/customers/{model}/").status_code, 200, model)
            self.assertEqual(self.client.get(f"/admin/customers/{model}/add/").status_code, 200, model)

    def test_adding_a_batch_in_admin_records_its_receipt(self):
        response = self.client.post("/admin/customers/batch/add/", {
            "status": "active", "customer": self.buyer.pk, "pile": self.pile.pk,
            "biomass_type": BiomassType.objects.get(name="Paddy straw").pk, "form": "bales", "source_note": "",
            "received_on": "2026-10-01", "intake_tonnes": "25", "intake_moisture_percent": "13",
        })
        self.assertEqual(response.status_code, 302)
        new = Batch.objects.get(intake_tonnes=D("25"))
        self.assertEqual(services.book_tonnes(new), D("25"))

    def test_adding_a_transaction_goes_through_the_service_and_the_ledger(self):
        response = self.client.post("/admin/customers/inventorytransaction/add/", {
            "batch": self.batch.pk, "kind": "consumption", "tonnes": "12", "loss_cause": "",
            "occurred_at_0": "2026-10-02", "occurred_at_1": "09:00:00", "note": "",
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context_data", None) and response.context_data["adminform"].form.errors)
        self.assertEqual(services.book_tonnes(self.batch), D("88"))
        self.assertTrue(self.batch.transactions.filter(kind="consumption").get().ledger_seq)

    def test_admin_refuses_a_transaction_bigger_than_the_stock(self):
        response = self.client.post("/admin/customers/inventorytransaction/add/", {
            "batch": self.batch.pk, "kind": "consumption", "tonnes": "500", "loss_cause": "",
            "occurred_at_0": "2026-10-02", "occurred_at_1": "09:00:00", "note": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "on the books")
        self.assertEqual(services.book_tonnes(self.batch), D("100"))

    def test_admin_adds_a_count(self):
        response = self.client.post("/admin/customers/stockcount/add/", {
            "batch": self.batch.pk, "counted_tonnes": "97", "method": "audit", "counted_on": "2026-10-03", "counted_by": "Ravi",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.batch.counts.get().counted_tonnes, D("97"))


class DemoDataTests(TestCase):
    def test_demo_customer_loads_once_and_the_numbers_make_sense(self):
        call_command("load_demo_customer", verbosity=0)
        call_command("load_demo_customer", verbosity=0)
        buyer = CustomerMember.objects.get(user__username="customer1").buyer
        s = services.summary(buyer)
        self.assertEqual(len(s.yards), 4)
        self.assertEqual(s.book, D("10300"))
        self.assertEqual(s.physical, D("9800"))
        self.assertIsNotNone(s.fuel_cover_days)
        self.assertTrue(verify().ok)
