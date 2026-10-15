from decimal import Decimal

from apps.reference.models import BiomassType, Crop, Season
from apps.territory.testing import SIDE, square

from .estimates import supply_estimate
from .models import FarmPlot, PlotSeason
from .tests import FarmsTestCase


class SupplyEstimateTests(FarmsTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.register()
        self.grid = self.make_grid()
        self.cell_a = self.cell("GC-A", square(76.0, 30.0), panchayat=self.home_panchayat, grid=self.grid)
        self.kharif = Season.objects.get(name="Kharif")
        self.rabi = Season.objects.get(name="Rabi")
        self.paddy = Crop.objects.get(name="Paddy")
        self.mustard = Crop.objects.get(name="Mustard")
        self.wheat = Crop.objects.get(name="Wheat")

    def plot(self, acres, lon=76.0, lat=30.0):
        return FarmPlot.objects.create(farmer=self.farmer, location=self.inside(lon, lat), area_acres=acres)

    def grow(self, plot, crop, season=None, year=2026):
        return PlotSeason.objects.create(plot=plot, season=season or self.kharif, crop=crop, year=year)

    def test_one_acre_of_paddy_is_one_point_three_tonnes(self):
        self.grow(self.plot(1), self.paddy)
        self.assertEqual(supply_estimate(2026).total.tonnes, Decimal("1.30"))

    def test_one_acre_of_mustard_is_one_point_two_tonnes(self):
        self.grow(self.plot(1), self.mustard, season=self.rabi)
        self.assertEqual(supply_estimate(2026).total.tonnes, Decimal("1.20"))

    def test_area_scales_the_estimate(self):
        self.grow(self.plot(Decimal("2.5")), self.paddy)
        self.assertEqual(supply_estimate(2026).total.tonnes, Decimal("3.25"))

    def test_totals_roll_up_by_cell_grid_and_crop(self):
        self.grow(self.plot(2), self.paddy)
        self.grow(self.plot(1), self.mustard, season=self.rabi)
        estimate = supply_estimate(2026)
        self.assertEqual(estimate.cells[0].label, "GC-A")
        self.assertEqual(estimate.cells[0].tonnes, Decimal("3.80"))
        self.assertEqual(estimate.grids[0].tonnes, Decimal("3.80"))
        self.assertEqual({row.label: row.tonnes for row in estimate.crops}, {"Paddy": Decimal("2.60"), "Mustard": Decimal("1.20")})

    def test_a_crop_with_no_figure_is_left_out_and_reported(self):
        self.grow(self.plot(1), self.wheat, season=self.rabi)
        estimate = supply_estimate(2026)
        self.assertEqual(estimate.total.tonnes, 0)
        self.assertEqual(estimate.crops_without_figure, ["Wheat"])

    def test_filling_in_a_figure_updates_the_estimate(self):
        self.grow(self.plot(2), self.wheat, season=self.rabi)
        BiomassType.objects.filter(name="Wheat straw").update(estimated_tonnes_per_acre=Decimal("1.5"))
        self.assertEqual(supply_estimate(2026).total.tonnes, Decimal("3.00"))

    def test_other_years_and_seasons_are_separate(self):
        plot = self.plot(1)
        self.grow(plot, self.paddy, year=2025)
        self.grow(plot, self.mustard, season=self.rabi, year=2026)
        self.assertEqual(supply_estimate(2026).total.tonnes, Decimal("1.20"))
        self.assertEqual(supply_estimate(2026, season=self.kharif).total.tonnes, 0)

    def test_plots_outside_every_cell_are_counted_separately(self):
        self.grow(self.plot(1, lon=80.0, lat=20.0), self.paddy)
        estimate = supply_estimate(2026)
        self.assertEqual(estimate.outside_cells.tonnes, Decimal("1.30"))
        self.assertEqual(estimate.cells, [])

    def test_inactive_plots_are_not_counted(self):
        plot = self.plot(1)
        self.grow(plot, self.paddy)
        plot.status = "inactive"
        plot.save()
        self.assertEqual(supply_estimate(2026).total.tonnes, 0)

    def test_withdrawn_farmers_are_not_counted(self):
        self.grow(self.plot(1), self.paddy)
        self.farmer.withdraw_consent()
        self.assertEqual(supply_estimate(2026).total.tonnes, 0)

    def test_can_be_limited_to_one_grid(self):
        self.grow(self.plot(1), self.paddy)
        other = self.make_grid("GRID-OTHER")
        self.assertEqual(supply_estimate(2026, grid=self.grid).total.tonnes, Decimal("1.30"))
        self.assertEqual(supply_estimate(2026, grid=other).total.tonnes, 0)


class SupplyReportPageTests(SupplyEstimateTests):
    def test_report_requires_staff_and_shows_totals(self):
        from apps.accounts.models import User

        self.grow(self.plot(1), self.paddy)
        self.assertEqual(self.client.get("/admin/reports/supply/").status_code, 302)
        boss = User.objects.create_superuser(username="boss", password="pw-12345-x")
        self.client.force_login(boss)
        response = self.client.get("/admin/reports/supply/?year=2026")
        self.assertContains(response, "1.30 tonnes")
        self.assertContains(response, "GC-A")


class StateFigureTests(SupplyEstimateTests):
    def factor(self, biomass_name, **values):
        from apps.reference.models import StateBiomassFactor

        return StateBiomassFactor.objects.create(
            biomass_type=BiomassType.objects.get(name=biomass_name), state=self.state, **values
        )

    def test_pilferage_reduces_the_expected_tonnes_but_not_the_gross(self):
        self.factor("Paddy straw", pilferage_percent=Decimal("10"))
        self.grow(self.plot(2), self.paddy)
        estimate = supply_estimate(2026)
        self.assertEqual(estimate.total.gross, Decimal("2.60"))
        self.assertEqual(estimate.total.tonnes, Decimal("2.34"))

    def test_a_state_can_have_its_own_yield_per_acre(self):
        self.factor("Paddy straw", estimated_tonnes_per_acre=Decimal("2.0"))
        self.grow(self.plot(1), self.paddy)
        self.assertEqual(supply_estimate(2026).total.tonnes, Decimal("2.00"))

    def test_a_state_row_without_a_yield_falls_back_to_the_default(self):
        self.factor("Paddy straw", pilferage_percent=Decimal("50"))
        self.grow(self.plot(1), self.paddy)
        self.assertEqual(supply_estimate(2026).total.gross, Decimal("1.30"))

    def test_another_states_figures_do_not_apply(self):
        from apps.geography.models import State
        from apps.reference.models import StateBiomassFactor

        StateBiomassFactor.objects.create(
            biomass_type=BiomassType.objects.get(name="Paddy straw"),
            state=State.objects.create(lgd_code="3", name="Punjab"),
            estimated_tonnes_per_acre=Decimal("9"),
            pilferage_percent=Decimal("90"),
        )
        self.grow(self.plot(1), self.paddy)
        self.assertEqual(supply_estimate(2026).total.tonnes, Decimal("1.30"))

    def test_a_state_figure_can_supply_a_crop_that_has_no_default(self):
        self.factor("Wheat straw", estimated_tonnes_per_acre=Decimal("1.5"))
        self.grow(self.plot(2), self.wheat, season=self.rabi)
        estimate = supply_estimate(2026)
        self.assertEqual(estimate.total.tonnes, Decimal("3.00"))
        self.assertEqual(estimate.crops_without_figure, [])

    def test_pilferage_cannot_exceed_100_percent(self):
        from django.core.exceptions import ValidationError

        row = self.factor("Paddy straw")
        row.pilferage_percent = Decimal("120")
        with self.assertRaises(ValidationError):
            row.full_clean()
