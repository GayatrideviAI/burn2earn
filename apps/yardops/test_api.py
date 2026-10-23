import json
import re
import uuid
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.customers.models import QualityObservation, StockCount
from apps.customers.tests import make_batch, make_pile, make_yard
from apps.ledger.chain import entries_for, verify

from . import risk, services
from .models import HeatReading, PileInspection, RiskAlert, YardOperator
from .tests import RiskCase

D = Decimal


class ApiCase(RiskCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="yard1", password="pw-12345-x", role=Role.YARD)
        self.operator = YardOperator.objects.create(user=self.user, name="Gurdeep")
        self.operator.yards.add(self.pile.yard)
        self.client.login(username="yard1", password="pw-12345-x")
        self.url = reverse("yardops:api_sync")

    def op(self, kind, **data):
        return {"id": str(uuid.uuid4()), "type": kind, "data": data}

    def send(self, *operations):
        response = self.client.post(self.url, data=json.dumps({"operations": list(operations)}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def heat_op(self, temp="40", hours_ago=0, **extra):
        when = (timezone.now() - timedelta(hours=hours_ago)).isoformat()
        return self.op("heat.create", pile_id=str(self.pile.pk), temperature_c=temp, taken_at=when, **extra)


class BootstrapTests(ApiCase):
    def get(self):
        return self.client.get(reverse("yardops:api_bootstrap")).json()

    def test_gives_the_phone_its_piles_with_risk_and_stock(self):
        self.heat(72)
        data = self.get()
        self.assertEqual(data["operator"]["name"], "Gurdeep")
        pile = data["piles"][0]
        self.assertEqual((pile["label"], pile["assessment"]["level"]), ("A-01", risk.ACT))
        self.assertFalse(pile["assessment"]["stale"])
        self.assertEqual(pile["batches"][0]["code"], self.batch.code)
        self.assertEqual(pile["batches"][0]["book_tonnes"], "100.000")
        self.assertEqual(pile["readings"][0]["temperature_c"], "72.0")
        self.assertEqual(data["thresholds"], {"warm": 50, "watch": 65, "act": 70, "emergency": 80})
        self.assertEqual(len(data["alerts"]), 1)

    def test_an_unprobed_pile_is_stale(self):
        self.assertTrue(self.get()["piles"][0]["assessment"]["stale"])

    def test_only_this_operators_yards_and_piles_with_stock(self):
        make_pile(self.pile.yard, "E-01")  # empty
        other = make_pile(make_yard("Yard Z"), "Z-01")
        make_batch(self.buyer, other, "10", "14")
        self.assertEqual([p["label"] for p in self.get()["piles"]], ["A-01"])

    def test_needs_a_yard_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("yardops:api_bootstrap")).status_code, 302)
        User.objects.create_user(username="adm", password="pw-12345-x", role=Role.ADMIN)
        self.client.login(username="adm", password="pw-12345-x")
        self.assertEqual(self.client.get(reverse("yardops:api_bootstrap")).status_code, 403)


class SyncTests(ApiCase):
    def test_a_temperature_is_saved_with_the_phones_id_and_time(self):
        op = self.heat_op("67.5", hours_ago=5, spot="north", depth_cm=100)
        self.assertEqual(self.send(op)[0]["status"], "ok")
        reading = HeatReading.objects.get()
        self.assertEqual(str(reading.pk), op["id"])
        self.assertEqual((reading.temperature_c, reading.spot, reading.depth_cm, reading.taken_by), (D("67.5"), "north", 100, "Gurdeep"))
        self.assertAlmostEqual((timezone.now() - reading.taken_at).total_seconds(), 5 * 3600, delta=120)
        self.assertTrue(RiskAlert.objects.filter(pile=self.pile, level="watch").exists())

    def test_sending_a_change_twice_saves_it_once(self):
        op = self.heat_op("67")
        self.assertEqual(self.send(op)[0]["status"], "ok")
        self.assertEqual(self.send(op)[0]["status"], "exists")
        self.assertEqual(HeatReading.objects.count(), 1)
        self.assertEqual(entries_for(self.pile).filter(entry_type="yard.heat").count(), 1)

    def test_an_id_belonging_to_another_yard_is_refused(self):
        other = make_pile(make_yard("Yard Z"), "Z-01")
        make_batch(self.buyer, other, "10", "14")
        stranger = services.record_heat(other, D("40"))
        bad = {"id": str(stranger.pk), "type": "heat.create", "data": self.heat_op()["data"]}
        result = self.send(bad)[0]
        self.assertEqual(result["status"], "error")
        self.assertIn("someone else", result["message"])

    def test_a_pile_in_another_yard_cannot_be_written_to(self):
        other = make_pile(make_yard("Yard Z"), "Z-01")
        make_batch(self.buyer, other, "10", "14")
        op = self.op("heat.create", pile_id=str(other.pk), temperature_c="40")
        result = self.send(op)[0]
        self.assertEqual(result["status"], "error")
        self.assertIn("not found in your yards", result["message"])
        self.assertEqual(HeatReading.objects.count(), 0)

    def test_bad_values_are_reported_not_saved(self):
        for op, text in (
            (self.heat_op("900"), "200"),
            (self.heat_op("abc"), "Temperature"),
            (self.op("heat.create", pile_id="nope", temperature_c="40"), "not a valid id"),
            (self.op("heat.create", pile_id=str(self.pile.pk), temperature_c="40", taken_at="yesterday"), "not a valid date"),
            (self.op("heat.create", pile_id=str(self.pile.pk), temperature_c="40", taken_at=(timezone.now() + timedelta(days=2)).isoformat()), "future"),
            ({"id": str(uuid.uuid4()), "type": "nonsense", "data": {}}, "Unknown"),
            ({"id": str(uuid.uuid4()), "type": "heat.create", "data": "x"}, "no data"),
            ({"id": "xx", "type": "heat.create", "data": {}}, "not a valid id"),
        ):
            with self.subTest(text=text):
                result = self.send(op)[0]
                self.assertEqual(result["status"], "error")
                self.assertIn(text, result["message"])
        self.assertEqual(HeatReading.objects.count(), 0)

    def test_an_inspection_is_saved_with_its_time(self):
        when = (timezone.now() - timedelta(hours=3)).isoformat()
        op = self.op("inspection.create", pile_id=str(self.pile.pk), steam_or_smell=True, cover_in_place=True, notes="Smells burnt", inspected_at=when)
        self.assertEqual(self.send(op)[0]["status"], "ok")
        saved = PileInspection.objects.get()
        self.assertEqual((str(saved.pk), saved.steam_or_smell, saved.looks_wet, saved.inspected_by), (op["id"], True, False, "Gurdeep"))
        self.assertEqual(self.send(op)[0]["status"], "exists")
        self.heat(40)
        self.assertEqual(risk.assess(self.pile).level, risk.ACT)

    def test_counts_and_moisture_feed_the_stock_figures(self):
        count = self.op("count.create", batch_id=str(self.batch.pk), tonnes="98.5", method="audit", counted_on=timezone.localdate().isoformat())
        moisture = self.op("moisture.create", batch_id=str(self.batch.pk), percent="13.5", method="handheld meter")
        self.assertEqual([r["status"] for r in self.send(count, moisture)], ["ok", "ok"])
        self.assertEqual([r["status"] for r in self.send(count, moisture)], ["exists", "exists"])
        self.assertEqual(StockCount.objects.get(batch=self.batch).counted_by, "Gurdeep")
        self.assertEqual(QualityObservation.objects.get(tested_by="Gurdeep").moisture_percent, D("13.5"))
        self.assertEqual(str(StockCount.objects.get(batch=self.batch).pk), count["id"])

    def test_a_batch_in_another_yard_is_refused(self):
        other = make_pile(make_yard("Yard Z"), "Z-01")
        theirs = make_batch(self.buyer, other, "10", "14")
        result = self.send(self.op("count.create", batch_id=str(theirs.pk), tonnes="5", method="audit"))[0]
        self.assertEqual(result["status"], "error")
        self.assertEqual(StockCount.objects.filter(batch=theirs).count(), 0)

    def test_a_future_count_date_is_refused(self):
        tomorrow = (timezone.localdate() + timedelta(days=5)).isoformat()
        result = self.send(self.op("count.create", batch_id=str(self.batch.pk), tonnes="5", method="audit", counted_on=tomorrow))[0]
        self.assertEqual(result["status"], "error")

    def test_size_update_only_changes_what_is_filled_in(self):
        self.send(self.op("size.update", pile_id=str(self.pile.pk), length_m="10", width_m="6", height_m="3.5", cover_type="Tarp"))
        self.send(self.op("size.update", pile_id=str(self.pile.pk), length_m="", width_m="", height_m="5.5", cover_type=""))
        self.pile.refresh_from_db()
        self.assertEqual((self.pile.length_m, self.pile.width_m, self.pile.height_m, self.pile.cover_type), (D("10.0"), D("6.0"), D("5.5"), "Tarp"))

    def test_acknowledging_keeps_the_time_the_button_was_pressed(self):
        self.heat(66)
        alert = RiskAlert.objects.get()
        alert.raised_at = timezone.now() - timedelta(minutes=20)
        alert.save()
        pressed = (timezone.now() - timedelta(minutes=8)).isoformat()
        op = self.op("alert.acknowledge", alert_id=str(alert.pk), acknowledged_at=pressed)
        self.assertEqual(self.send(op)[0]["status"], "ok")
        alert.refresh_from_db()
        self.assertEqual(alert.acknowledged_by, self.user)
        self.assertEqual(alert.response_minutes, 12)
        self.assertEqual(self.send(self.op("alert.acknowledge", alert_id=str(alert.pk)))[0]["status"], "exists")

    def test_an_acknowledgement_time_is_kept_inside_the_alert_window(self):
        self.heat(66)
        alert = RiskAlert.objects.get()
        before = (alert.raised_at - timedelta(hours=1)).isoformat()
        self.send(self.op("alert.acknowledge", alert_id=str(alert.pk), acknowledged_at=before))
        alert.refresh_from_db()
        self.assertEqual(alert.response_minutes, 0)

    def test_acknowledging_an_alert_that_has_closed_is_flagged_not_failed(self):
        self.heat(66, hours_ago=2)
        self.heat(40)
        alert = RiskAlert.objects.get()
        result = self.send(self.op("alert.acknowledge", alert_id=str(alert.pk)))[0]
        self.assertEqual(result["status"], "flagged")

    def test_an_alert_in_another_yard_cannot_be_acknowledged(self):
        other = make_pile(make_yard("Yard Z"), "Z-01")
        make_batch(self.buyer, other, "10", "14")
        self.heat(66, pile=other)
        result = self.send(self.op("alert.acknowledge", alert_id=str(RiskAlert.objects.get().pk)))[0]
        self.assertEqual(result["status"], "error")

    def test_one_bad_change_does_not_stop_the_others(self):
        results = self.send(self.heat_op("900"), self.heat_op("41"))
        self.assertEqual([r["status"] for r in results], ["error", "ok"])

    def test_the_ledger_stays_intact(self):
        self.send(self.heat_op("67"), self.op("inspection.create", pile_id=str(self.pile.pk), looks_wet=True))
        self.assertTrue(verify().ok)

    def test_too_many_changes_and_bad_bodies_are_refused(self):
        for body in ('{"operations": "x"}', "not json", '{"operations": [' + ",".join(["{}"] * 201) + "]}"):
            response = self.client.post(self.url, data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_login_is_required(self):
        self.client.logout()
        self.assertEqual(self.client.post(self.url, data="{}", content_type="application/json").status_code, 302)


class AppShellTests(ApiCase):
    def test_the_app_page_the_service_worker_and_the_manifest(self):
        page = self.client.get(reverse("yardops:app"))
        self.assertContains(page, "window.YARD")
        self.assertContains(page, reverse("yardops:api_sync"))
        self.assertIn("csrftoken", page.cookies)
        worker = self.client.get(reverse("yardops:service_worker"))
        self.assertEqual(worker["Service-Worker-Allowed"], "/yard/")
        self.assertContains(worker, "yardops/app.js")
        manifest = self.client.get(reverse("yardops:manifest"))
        self.assertEqual(manifest.json()["start_url"], reverse("yardops:app"))

    def test_the_app_page_needs_a_yard_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("yardops:app")).status_code, 302)

    def test_the_page_carries_the_translations(self):
        catalog = json.loads(re.search(r"catalog: (\{.*\})\n", self.client.get(reverse("yardops:app")).content.decode()).group(1))
        self.assertEqual(set(catalog), {"hi", "pa"})
        self.assertEqual(catalog["hi"]["Watch closely"], "ध्यान से देखें")
        self.assertEqual(catalog["pa"]["Log a temperature"], "ਤਾਪਮਾਨ ਦਰਜ ਕਰੋ")

    def test_every_phrase_in_the_yard_app_is_in_the_sheet(self):
        from apps.customers import i18n_tools as tools
        from apps.field import jscatalog

        from .views import APP_JS

        in_app = set(jscatalog.phrases_in(APP_JS)) | set(jscatalog.phrases_in(jscatalog.PHOTOS_JS))
        self.assertTrue(in_app)
        self.assertLessEqual(in_app, set(tools.collect()))
