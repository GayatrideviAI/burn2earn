import json
import uuid
from datetime import date

from django.urls import reverse

from apps.accounts.models import Role, User
from apps.farms.models import Farmer, FarmPlot, PlotSeason
from apps.operations.models import CollectionRecord, ProcessedOutput
from apps.reference.models import BiomassType, Crop, ProcessingType, Product, Season

from .tests import FieldTestCase


class SyncTestCase(FieldTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("field:api_sync")

    def send(self, *operations):
        response = self.client.post(
            self.url, data=json.dumps({"operations": list(operations)}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def farmer_op(self, **data):
        base = {
            "name": "Sita Devi",
            "mobile": "9811111111",
            "village_id": str(self.village.pk),
            "preferred_language": "hi",
            "consent": True,
        }
        base.update(data)
        return {"id": str(uuid.uuid4()), "type": "farmer.create", "data": base}


class BootstrapTests(SyncTestCase):
    def test_gives_the_phone_its_lists_and_farmers(self):
        farmer = self.register("Ramesh Kumar")
        plot = FarmPlot.objects.create(farmer=farmer, location=self.inside(), area_acres=2)
        PlotSeason.objects.create(
            plot=plot, season=Season.objects.get(name="Kharif"), crop=Crop.objects.get(name="Paddy"), year=2026
        )
        data = self.client.get(reverse("field:api_bootstrap")).json()
        self.assertEqual(data["mitra"]["name"], "Gurpreet Singh")
        self.assertEqual(data["grid"]["code"], self.grid.code)
        self.assertEqual([f["name"] for f in data["farmers"]], ["Ramesh Kumar"])
        self.assertEqual(data["farmers"][0]["plots"][0]["seasons"][0]["crop"], "Paddy")
        self.assertIn("Paddy straw", [b["name"] for b in data["biomass_types"]])
        self.assertIn(str(self.village.pk), [v["id"] for v in data["villages"]])

    def test_only_this_mitras_farmers_are_included(self):
        self.other_mitra_farmer()
        self.assertEqual(self.client.get(reverse("field:api_bootstrap")).json()["farmers"], [])

    def test_needs_a_login_and_a_mitra(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("field:api_bootstrap")).status_code, 302)
        User.objects.create_user(username="adm", password="pw-12345-x", role=Role.ADMIN)
        self.client.login(username="adm", password="pw-12345-x")
        self.assertEqual(self.client.get(reverse("field:api_bootstrap")).status_code, 403)


class FarmerSyncTests(SyncTestCase):
    def test_a_farmer_is_created_with_the_phones_id_and_consent(self):
        op = self.farmer_op()
        result = self.send(op)[0]
        self.assertEqual(result["status"], "ok")
        farmer = Farmer.objects.get(pk=op["id"])
        self.assertEqual(farmer.registered_by_mitra, self.mitra)
        self.assertTrue(farmer.has_consent)
        self.assertFalse(farmer.needs_review)

    def test_sending_the_same_change_twice_saves_it_once(self):
        op = self.farmer_op()
        self.send(op)
        self.assertEqual(self.send(op)[0]["status"], "exists")
        self.assertEqual(Farmer.objects.count(), 1)

    def test_consent_time_from_the_phone_is_kept_but_not_if_in_the_future(self):
        op = self.farmer_op(consented_at="2026-01-05T10:00:00+05:30")
        self.send(op)
        self.assertEqual(Farmer.objects.get(pk=op["id"]).consents.get().given_at.year, 2026)
        future = self.farmer_op(consented_at="2999-01-01T00:00:00Z")
        self.send(future)
        self.assertLess(Farmer.objects.get(pk=future["id"]).consents.get().given_at.year, 2999)

    def test_same_mobile_is_saved_but_flagged_for_review(self):
        self.register("Existing", "9811111111")
        result = self.send(self.farmer_op())[0]
        self.assertEqual(result["status"], "flagged")
        self.assertIn("review", result["message"])
        self.assertEqual(Farmer.objects.filter(needs_review=True).count(), 1)
        self.assertEqual(Farmer.objects.count(), 2)

    def test_no_consent_means_no_farmer(self):
        result = self.send(self.farmer_op(consent=False))[0]
        self.assertEqual(result["status"], "error")
        self.assertIn("Consent", result["message"])
        self.assertEqual(Farmer.objects.count(), 0)

    def test_bad_mobile_is_rejected_with_a_readable_message(self):
        result = self.send(self.farmer_op(mobile="123"))[0]
        self.assertEqual(result["status"], "error")
        self.assertIn("mobile", result["message"].lower())

    def test_one_bad_change_does_not_stop_the_others(self):
        good, bad = self.farmer_op(), self.farmer_op(name="")
        results = self.send(bad, good)
        self.assertEqual([r["status"] for r in results], ["error", "ok"])
        self.assertEqual(Farmer.objects.count(), 1)

    def test_an_id_that_belongs_to_another_mitra_is_refused(self):
        stranger = self.other_mitra_farmer()
        op = self.farmer_op()
        op["id"] = str(stranger.pk)
        self.assertEqual(self.send(op)[0]["status"], "error")


class ChainedSyncTests(SyncTestCase):
    def test_a_whole_offline_day_arrives_in_order(self):
        farmer_op = self.farmer_op()
        plot_id, season_id, pickup_id, output_id = (str(uuid.uuid4()) for _ in range(4))
        straw = BiomassType.objects.get(name="Paddy straw")
        product = Product.objects.create(
            name="Paddy pellets", form="processed", biomass_type=straw,
            processing_type=ProcessingType.objects.get(name="Pelletising"),
        )
        results = self.send(
            farmer_op,
            {"id": plot_id, "type": "plot.create", "data": {
                "farmer_id": farmer_op["id"], "latitude": "30.005", "longitude": "76.005", "area_acres": "2.5",
                "ownership": "", "irrigation": ""}},
            {"id": season_id, "type": "season.create", "data": {
                "plot_id": plot_id, "season_id": str(Season.objects.get(name="Kharif").pk),
                "crop_id": str(Crop.objects.get(name="Paddy").pk), "year": 2026, "variety": "",
                "sowing_date": "", "expected_harvest_date": ""}},
            {"id": pickup_id, "type": "collection.create", "data": {
                "farmer_id": farmer_op["id"], "plot_id": plot_id, "biomass_type_id": str(straw.pk),
                "quantity_tonnes": "2.5", "price_paid": "3750", "collected_on": date.today().isoformat(), "notes": ""}},
            {"id": output_id, "type": "output.create", "data": {
                "product_id": str(product.pk), "quantity_tonnes": "1.2", "biomass_used_tonnes": "",
                "produced_on": date.today().isoformat(), "notes": ""}},
        )
        self.assertEqual([r["status"] for r in results], ["ok", "ok", "ok", "ok", "ok"], results)
        plot = FarmPlot.objects.get(pk=plot_id)
        self.assertEqual(plot.geocell, self.cell_a)
        self.assertEqual(PlotSeason.objects.get(pk=season_id).plot, plot)
        self.assertEqual(CollectionRecord.objects.get(pk=pickup_id).quantity_tonnes, 2.5)
        self.assertEqual(ProcessedOutput.objects.get(pk=output_id).grid, self.grid)

    def test_a_change_for_a_missing_farmer_is_reported(self):
        result = self.send({"id": str(uuid.uuid4()), "type": "plot.create", "data": {
            "farmer_id": str(uuid.uuid4()), "latitude": "30", "longitude": "76", "area_acres": "1"}})[0]
        self.assertEqual(result["status"], "error")
        self.assertIn("farmer", result["message"].lower())

    def test_plot_outside_every_cell_is_saved_and_flagged(self):
        farmer_op = self.farmer_op()
        plot_op = {"id": str(uuid.uuid4()), "type": "plot.create", "data": {
            "farmer_id": farmer_op["id"], "latitude": "20", "longitude": "80", "area_acres": "1"}}
        results = self.send(farmer_op, plot_op)
        self.assertEqual(results[1]["status"], "flagged")
        self.assertTrue(FarmPlot.objects.get(pk=plot_op["id"]).outside_geocells)

    def test_cannot_use_another_mitras_farmer(self):
        stranger = self.other_mitra_farmer()
        result = self.send({"id": str(uuid.uuid4()), "type": "collection.create", "data": {
            "farmer_id": str(stranger.pk), "biomass_type_id": str(BiomassType.objects.first().pk),
            "quantity_tonnes": "1", "price_paid": "10", "collected_on": date.today().isoformat()}})[0]
        self.assertEqual(result["status"], "error")
        self.assertEqual(CollectionRecord.objects.count(), 0)

    def test_unknown_change_type_and_junk_input(self):
        self.assertEqual(self.send({"id": str(uuid.uuid4()), "type": "nope", "data": {}})[0]["status"], "error")
        self.assertEqual(self.send({"id": "not-a-uuid", "type": "farmer.create", "data": {}})[0]["status"], "error")
        response = self.client.post(self.url, data="not json", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_duplicate_crop_is_reported_not_crashed(self):
        farmer_op = self.farmer_op()
        plot_id = str(uuid.uuid4())
        plot_op = {"id": plot_id, "type": "plot.create", "data": {
            "farmer_id": farmer_op["id"], "latitude": "30.005", "longitude": "76.005", "area_acres": "1"}}
        data = {"plot_id": plot_id, "season_id": str(Season.objects.get(name="Kharif").pk),
                "crop_id": str(Crop.objects.get(name="Paddy").pk), "year": 2026}
        results = self.send(farmer_op, plot_op,
                            {"id": str(uuid.uuid4()), "type": "season.create", "data": data},
                            {"id": str(uuid.uuid4()), "type": "season.create", "data": data})
        self.assertEqual([r["status"] for r in results], ["ok", "ok", "ok", "error"])


class ShellTests(SyncTestCase):
    def test_app_page_service_worker_and_manifest(self):
        page = self.client.get(reverse("field:app"))
        self.assertContains(page, "app.js")
        self.assertIn("csrftoken", self.client.cookies)
        worker = self.client.get(reverse("field:service_worker"))
        self.assertEqual(worker["Service-Worker-Allowed"], "/mitra/")
        self.assertContains(worker, "caches.open")
        manifest = self.client.get(reverse("field:manifest"))
        self.assertEqual(manifest.json()["short_name"], "Mitra")

    def test_online_registration_with_a_shared_mobile_is_flagged_too(self):
        self.register("Existing", "9811111111")
        self.client.post(reverse("field:farmer_new"), self.farmer_data(confirm_duplicate="1"))
        self.assertTrue(Farmer.objects.get(name="Sita Devi").needs_review)
