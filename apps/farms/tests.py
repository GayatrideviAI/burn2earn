from datetime import date

from django.contrib.gis.geos import Point, Polygon
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.models import AuditLog, Status
from apps.geography.models import Village
from apps.network.test_mitra import MitraTestCase
from apps.reference.models import Crop, Season
from apps.territory.testing import SIDE, square

from .models import ConsentRecord, Farmer, FarmPlot, PlotSeason
from .services import NOTICE_VERSION, register_farmer


class FarmsTestCase(MitraTestCase):
    def setUp(self):
        super().setUp()
        self.home_panchayat = self.panchayat("9001")
        self.village = Village.objects.create(
            lgd_code="50001", name="Village A", panchayat=self.home_panchayat
        )
        self.mitra = self.make_mitra()

    def register(self, name="Ramesh Kumar", mobile="9876543210", **extra):
        return register_farmer(
            mitra=self.mitra, name=name, mobile=mobile, village=self.village, **extra
        )

    def inside(self, cell_lon=76.0, cell_lat=30.0):
        """A point in the middle of a SIDE-sized square starting at the given corner."""
        return Point(cell_lon + SIDE / 2, cell_lat + SIDE / 2, srid=4326)


class FarmerTests(FarmsTestCase):
    def test_registering_creates_the_farmer_and_a_consent_record_together(self):
        farmer = self.register(preferred_language="hi")
        consent = farmer.consents.get()
        self.assertEqual(consent.notice_version, NOTICE_VERSION)
        self.assertEqual(consent.captured_by_mitra, self.mitra)
        self.assertEqual(consent.language, "hi")
        self.assertTrue(farmer.has_consent)
        self.assertEqual(farmer.registered_by_mitra, self.mitra)

    def test_codes_run_in_sequence(self):
        first, second = self.register("A"), self.register("B")
        self.assertEqual(first.code, "FRM-000001")
        self.assertEqual(second.code, "FRM-000002")

    def test_code_does_not_change_when_the_farmer_is_edited(self):
        farmer = self.register()
        code = farmer.code
        farmer.name = "Ramesh K."
        farmer.save()
        farmer.refresh_from_db()
        self.assertEqual(farmer.code, code)

    def test_two_farmers_can_share_a_mobile_number(self):
        self.register("A", mobile="9876543210")
        self.register("B", mobile="9876543210")
        self.assertEqual(Farmer.objects.filter(mobile="9876543210").count(), 2)

    def test_mobile_is_required_and_checked(self):
        farmer = self.register()
        farmer.mobile = ""
        with self.assertRaises(ValidationError) as caught:
            farmer.clean()
        self.assertIn("mobile", caught.exception.message_dict)
        farmer.mobile = "12345"
        with self.assertRaises(ValidationError) as caught:
            farmer.full_clean(exclude=["code"])
        self.assertIn("mobile", caught.exception.message_dict)

    def test_a_failed_consent_record_leaves_no_farmer_behind(self):
        with self.assertRaises(Exception):
            with transaction.atomic():
                register_farmer(
                    mitra=self.mitra,
                    name="X",
                    mobile="9876543210",
                    village=self.village,
                    preferred_language="x" * 50,  # too long for the consent record
                )
        self.assertEqual(Farmer.objects.count(), 0)


class WithdrawalTests(FarmsTestCase):
    def test_withdrawing_consent_anonymises_the_farmer(self):
        farmer = self.register(preferred_language="hi")
        farmer.withdraw_consent()
        farmer.refresh_from_db()
        self.assertEqual(farmer.name, "Anonymised farmer")
        self.assertEqual(farmer.mobile, "")
        self.assertEqual(farmer.preferred_language, "")
        self.assertEqual(farmer.status, Status.INACTIVE)
        self.assertIsNotNone(farmer.anonymised_at)
        self.assertFalse(farmer.has_consent)
        self.assertIsNotNone(farmer.consents.get().withdrawn_at)

    def test_anonymised_farmer_passes_validation_without_a_mobile(self):
        farmer = self.register()
        farmer.withdraw_consent()
        farmer.clean()

    def test_plots_survive_anonymisation(self):
        farmer = self.register()
        FarmPlot.objects.create(farmer=farmer, location=self.inside(), area_acres=3)
        farmer.withdraw_consent()
        self.assertEqual(farmer.plots.count(), 1)

    def test_the_audit_log_never_holds_the_name_or_mobile_number(self):
        farmer = self.register("Ramesh Kumar", "9876543210")
        farmer.name = "Ramesh K. Kumar"
        farmer.save()
        farmer.withdraw_consent()
        logs = AuditLog.objects.filter(
            model_label="farms.Farmer", object_id=str(farmer.pk)
        )
        self.assertGreaterEqual(logs.count(), 3)
        text = " ".join(str(log.changes) for log in logs)
        self.assertNotIn("Ramesh", text)
        self.assertNotIn("9876543210", text)
        self.assertIn("<redacted>", text)


class FarmPlotTests(FarmsTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.register()
        self.cell_a = self.cell("GC-A", square(76.0, 30.0), panchayat=self.home_panchayat)
        self.cell_b = self.cell("GC-B", square(76.0 + SIDE, 30.0))

    def test_plot_is_placed_in_the_cell_that_contains_it(self):
        plot = FarmPlot.objects.create(farmer=self.farmer, location=self.inside(), area_acres=2)
        self.assertEqual(plot.geocell, self.cell_a)

    def test_plot_outside_every_cell_is_kept_but_flagged(self):
        plot = FarmPlot.objects.create(
            farmer=self.farmer, location=Point(80.0, 20.0, srid=4326), area_acres=2
        )
        self.assertIsNone(plot.geocell)
        self.assertTrue(plot.outside_geocells)

    def test_plot_straddling_two_cells_goes_to_the_one_with_more_of_it(self):
        # 25% of the plot's width is in cell A and 50% is in cell B.
        x0, x1 = 76.0 + SIDE * 0.75, 76.0 + SIDE * 1.5
        y0, y1 = 30.0 + SIDE * 0.25, 30.0 + SIDE * 0.75
        boundary = Polygon(((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)), srid=4326)
        plot = FarmPlot.objects.create(
            farmer=self.farmer, location=Point(x0, y0, srid=4326), boundary=boundary
        )
        self.assertEqual(plot.geocell, self.cell_b)

    def test_area_is_calculated_from_the_boundary_in_acres(self):
        boundary = Polygon(
            (
                (76.0, 30.0),
                (76.0 + SIDE / 2, 30.0),
                (76.0 + SIDE / 2, 30.0 + SIDE / 2),
                (76.0, 30.0 + SIDE / 2),
                (76.0, 30.0),
            ),
            srid=4326,
        )
        plot = FarmPlot.objects.create(
            farmer=self.farmer, location=self.inside(), boundary=boundary, area_acres=999
        )
        # About a quarter of the 600 to 700 acre cell, and certainly not the typed 999.
        self.assertGreater(plot.area_acres, 100)
        self.assertLess(plot.area_acres, 250)

    def test_area_or_boundary_is_required(self):
        plot = FarmPlot(farmer=self.farmer, location=self.inside())
        with self.assertRaises(ValidationError) as caught:
            plot.clean()
        self.assertIn("area_acres", caught.exception.message_dict)

    def test_warns_when_the_cell_is_in_another_panchayat(self):
        in_home_cell = FarmPlot.objects.create(
            farmer=self.farmer, location=self.inside(), area_acres=1
        )
        in_other_cell = FarmPlot.objects.create(
            farmer=self.farmer, location=self.inside(76.0 + SIDE, 30.0), area_acres=1
        )
        self.assertFalse(in_home_cell.panchayat_differs_from_village)
        self.assertTrue(in_other_cell.panchayat_differs_from_village)

    def test_moving_a_plot_updates_its_cell(self):
        plot = FarmPlot.objects.create(farmer=self.farmer, location=self.inside(), area_acres=1)
        plot.location = self.inside(76.0 + SIDE, 30.0)
        plot.save()
        plot.refresh_from_db()
        self.assertEqual(plot.geocell, self.cell_b)

    def test_a_farmer_can_have_plots_in_several_cells(self):
        FarmPlot.objects.create(farmer=self.farmer, location=self.inside(), area_acres=1)
        FarmPlot.objects.create(
            farmer=self.farmer, location=self.inside(76.0 + SIDE, 30.0), area_acres=1
        )
        cells = {plot.geocell for plot in self.farmer.plots.all()}
        self.assertEqual(cells, {self.cell_a, self.cell_b})


class PlotSeasonTests(FarmsTestCase):
    def setUp(self):
        super().setUp()
        farmer = self.register()
        self.plot = FarmPlot.objects.create(farmer=farmer, location=self.inside(), area_acres=2)
        self.kharif = Season.objects.get(name="Kharif")
        self.rabi = Season.objects.get(name="Rabi")
        self.paddy = Crop.objects.get(name="Paddy")
        self.wheat = Crop.objects.get(name="Wheat")

    def grow(self, season, crop, year=2026, **extra):
        return PlotSeason.objects.create(
            plot=self.plot, season=season, crop=crop, year=year, **extra
        )

    def test_a_plot_can_grow_different_crops_in_different_seasons(self):
        self.grow(self.kharif, self.paddy)
        self.grow(self.rabi, self.wheat)
        self.assertEqual(self.plot.seasons.count(), 2)

    def test_the_same_crop_cannot_be_recorded_twice_for_a_season_and_year(self):
        self.grow(self.kharif, self.paddy)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.grow(self.kharif, self.paddy)

    def test_the_same_crop_can_return_next_year(self):
        self.grow(self.kharif, self.paddy, year=2026)
        self.grow(self.kharif, self.paddy, year=2027)
        self.assertEqual(self.plot.seasons.count(), 2)

    def test_harvest_cannot_be_before_sowing(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.grow(
                self.kharif,
                self.paddy,
                sowing_date=date(2026, 7, 1),
                expected_harvest_date=date(2026, 6, 1),
            )

    def test_form_message_when_harvest_is_before_sowing(self):
        season = PlotSeason(
            plot=self.plot,
            season=self.kharif,
            crop=self.paddy,
            year=2026,
            sowing_date=date(2026, 7, 1),
            expected_harvest_date=date(2026, 6, 1),
        )
        with self.assertRaises(ValidationError) as caught:
            season.clean()
        self.assertIn("expected_harvest_date", caught.exception.message_dict)


class ConsentRecordTests(FarmsTestCase):
    def test_consent_defaults_to_given_now_and_not_withdrawn(self):
        consent = ConsentRecord.objects.create(
            farmer=self.register(), notice_version="v1"
        )
        self.assertIsNone(consent.withdrawn_at)
        self.assertIsNotNone(consent.given_at)
