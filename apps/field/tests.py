from datetime import date

from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.farms.models import Farmer, FarmPlot, PlotSeason
from apps.farms.services import register_farmer
from apps.farms.tests import FarmsTestCase
from apps.geography.models import Village
from apps.network.models import MitraOperatingStatus
from apps.operations.models import CollectionRecord, ProcessedOutput
from apps.reference.models import BiomassType, Crop, ProcessingType, Product, Season
from apps.territory.testing import SIDE, square


class FieldTestCase(FarmsTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            username="mitra1", password="pw-12345-x", role=Role.MITRA
        )
        self.mitra.user = self.user
        self.mitra.save()
        self.grid = self.make_grid()
        self.cell_a = self.cell("GC-A", square(76.0, 30.0), panchayat=self.home_panchayat, grid=self.grid)
        self.assign(self.mitra, self.grid)
        self.client.login(username="mitra1", password="pw-12345-x")

    def other_mitra_farmer(self):
        other_user = User.objects.create_user(username="m2", password="x", role=Role.MITRA)
        other = self.make_mitra("MITRA-2", mobile="9123456780", user=other_user)
        village = Village.objects.create(lgd_code="50002", name="Far", panchayat=self.panchayat("9002"))
        return register_farmer(mitra=other, name="Stranger", mobile="9000000001", village=village)

    def farmer_data(self, **extra):
        data = {
            "name": "Sita Devi",
            "mobile": "9811111111",
            "village": self.village.pk,
            "preferred_language": "hi",
            "consent": "on",
        }
        data.update(extra)
        return data


class AccessTests(FieldTestCase):
    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("field:dashboard"))
        self.assertRedirects(response, f"{reverse('field:login')}?next={reverse('field:dashboard')}")

    def test_admin_without_a_mitra_record_gets_403(self):
        User.objects.create_user(username="adm", password="pw-12345-x", role=Role.ADMIN)
        self.client.login(username="adm", password="pw-12345-x")
        self.assertEqual(self.client.get(reverse("field:dashboard")).status_code, 403)

    def test_suspended_mitra_gets_403(self):
        self.mitra.operating_status = MitraOperatingStatus.SUSPENDED
        self.mitra.save()
        self.assertEqual(self.client.get(reverse("field:farmer_list")).status_code, 403)

    def test_dashboard_loads(self):
        response = self.client.get(reverse("field:dashboard"))
        self.assertContains(response, "Gurpreet Singh")

    def test_root_redirects_to_the_dashboard(self):
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_logout_works(self):
        response = self.client.post(reverse("field:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(reverse("field:dashboard")).status_code, 302)


class PredictorLinkTests(FieldTestCase):
    @override_settings(PREDICTOR_URL="https://predict.example.org/")
    def test_link_shows_when_the_predictor_address_is_set(self):
        farmer = self.register()
        for url in (reverse("field:dashboard"), reverse("field:farmer_detail", args=[farmer.pk])):
            response = self.client.get(url)
            self.assertContains(response, 'href="https://predict.example.org/"')
            self.assertContains(response, 'rel="noopener"')

    @override_settings(PREDICTOR_URL="")
    def test_no_link_when_it_is_not_set(self):
        self.assertNotContains(self.client.get(reverse("field:dashboard")), "Estimate earnings")


class FarmerPageTests(FieldTestCase):
    def test_registering_a_farmer_needs_consent(self):
        data = self.farmer_data()
        del data["consent"]
        response = self.client.post(reverse("field:farmer_new"), data)
        self.assertContains(response, "Consent is needed")
        self.assertEqual(Farmer.objects.count(), 0)

    def test_registering_creates_farmer_and_consent(self):
        response = self.client.post(reverse("field:farmer_new"), self.farmer_data())
        farmer = Farmer.objects.get()
        self.assertRedirects(response, reverse("field:farmer_detail", args=[farmer.pk]))
        self.assertEqual(farmer.registered_by_mitra, self.mitra)
        self.assertTrue(farmer.has_consent)

    def test_duplicate_mobile_asks_for_confirmation(self):
        register_farmer(mitra=self.mitra, name="Existing", mobile="9811111111", village=self.village)
        response = self.client.post(reverse("field:farmer_new"), self.farmer_data())
        self.assertContains(response, "already exists")
        self.assertEqual(Farmer.objects.count(), 1)
        response = self.client.post(
            reverse("field:farmer_new"), self.farmer_data(confirm_duplicate="1")
        )
        self.assertEqual(Farmer.objects.count(), 2)

    def test_search_finds_by_name_and_hides_other_mitras_farmers(self):
        self.register("Ramesh Kumar")
        self.other_mitra_farmer()
        response = self.client.get(reverse("field:farmer_list"), {"q": "ramesh"})
        self.assertContains(response, "Ramesh Kumar")
        response = self.client.get(reverse("field:farmer_list"))
        self.assertNotContains(response, "Stranger")

    def test_cannot_open_another_mitras_farmer(self):
        stranger = self.other_mitra_farmer()
        response = self.client.get(reverse("field:farmer_detail", args=[stranger.pk]))
        self.assertEqual(response.status_code, 404)


class PlotPageTests(FieldTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.register()
        self.url = reverse("field:plot_new", args=[self.farmer.pk])

    def plot_data(self, **extra):
        data = {"latitude": "30.005", "longitude": "76.005", "area_acres": "2.5"}
        data.update(extra)
        return data

    def test_adds_a_plot_inside_a_cell(self):
        self.client.post(self.url, self.plot_data())
        plot = FarmPlot.objects.get()
        self.assertEqual(plot.geocell, self.cell_a)
        self.assertEqual(str(plot.area_acres), "2.50")

    def test_plot_outside_every_cell_is_saved_with_a_warning(self):
        response = self.client.post(self.url, self.plot_data(latitude="20", longitude="80"), follow=True)
        self.assertContains(response, "outside every GeoCell")
        self.assertTrue(FarmPlot.objects.get().outside_geocells)

    def test_coordinates_outside_india_are_rejected(self):
        response = self.client.post(self.url, self.plot_data(latitude="76", longitude="30"))
        self.assertContains(response, "between 6 and 38")
        self.assertEqual(FarmPlot.objects.count(), 0)

    def test_area_must_be_positive(self):
        self.client.post(self.url, self.plot_data(area_acres="0"))
        self.assertEqual(FarmPlot.objects.count(), 0)


class SeasonPageTests(FieldTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.register()
        self.plot = FarmPlot.objects.create(farmer=self.farmer, location=self.inside(), area_acres=2)
        self.url = reverse("field:season_new", args=[self.farmer.pk, self.plot.pk])
        self.data = {
            "season": Season.objects.get(name="Kharif").pk,
            "crop": Crop.objects.get(name="Paddy").pk,
            "year": 2026,
        }

    def test_adds_a_crop(self):
        self.client.post(self.url, self.data)
        self.assertEqual(PlotSeason.objects.count(), 1)

    def test_duplicate_crop_gives_a_readable_error(self):
        self.client.post(self.url, self.data)
        response = self.client.post(self.url, self.data)
        self.assertContains(response, "already recorded")
        self.assertEqual(PlotSeason.objects.count(), 1)

    def test_harvest_before_sowing_is_rejected(self):
        data = dict(self.data, sowing_date="2026-07-01", expected_harvest_date="2026-06-01")
        response = self.client.post(self.url, data)
        self.assertContains(response, "cannot be before")
        self.assertEqual(PlotSeason.objects.count(), 0)


class DashboardEstimateTests(FieldTestCase):
    def test_dashboard_shows_expected_biomass_for_the_grid(self):
        from datetime import date

        farmer = self.register()
        plot = FarmPlot.objects.create(farmer=farmer, location=self.inside(), area_acres=2)
        PlotSeason.objects.create(
            plot=plot,
            season=Season.objects.get(name="Kharif"),
            crop=Crop.objects.get(name="Paddy"),
            year=date.today().year,
        )
        response = self.client.get(reverse("field:dashboard"))
        self.assertContains(response, "Expected biomass")
        self.assertContains(response, "2.60 tonnes")


class CollectionAndStockPageTests(FieldTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.register()
        self.straw = BiomassType.objects.get(name="Paddy straw")

    def test_logging_a_pickup_updates_the_stock_page(self):
        response = self.client.post(
            reverse("field:collection_new", args=[self.farmer.pk]),
            {"biomass_type": self.straw.pk, "quantity_tonnes": "2.5", "price_paid": "3750", "collected_on": date.today().isoformat()},
            follow=True,
        )
        self.assertContains(response, "2.5")
        self.assertEqual(CollectionRecord.objects.get().price_paid, 3750)
        self.assertContains(self.client.get(reverse("field:stock")), "2.500")

    def test_future_pickup_date_is_rejected(self):
        response = self.client.post(
            reverse("field:collection_new", args=[self.farmer.pk]),
            {"biomass_type": self.straw.pk, "quantity_tonnes": "1", "price_paid": "100", "collected_on": "2999-01-01"},
        )
        self.assertContains(response, "future")
        self.assertEqual(CollectionRecord.objects.count(), 0)

    def test_cannot_log_a_pickup_for_another_mitras_farmer(self):
        stranger = self.other_mitra_farmer()
        response = self.client.get(reverse("field:collection_new", args=[stranger.pk]))
        self.assertEqual(response.status_code, 404)

    def test_reporting_output_shows_on_the_stock_page(self):
        product = Product.objects.create(
            name="Paddy pellets", form="processed", biomass_type=self.straw,
            processing_type=ProcessingType.objects.get(name="Pelletising"),
        )
        response = self.client.post(
            reverse("field:output_new"),
            {"product": product.pk, "quantity_tonnes": "1.2", "produced_on": date.today().isoformat()},
            follow=True,
        )
        self.assertContains(response, "Paddy pellets")
        self.assertEqual(ProcessedOutput.objects.get().grid, self.grid)

    def test_dashboard_shows_stock(self):
        self.assertContains(self.client.get(reverse("field:dashboard")), "Stock at your site")

    def test_admin_stock_report_for_staff(self):
        boss = User.objects.create_superuser(username="boss", password="pw-12345-x")
        self.client.force_login(boss)
        self.assertEqual(self.client.get("/admin/reports/stock/").status_code, 200)
