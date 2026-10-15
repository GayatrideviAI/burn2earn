from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.reference.models import BiomassType, ProcessingType, Product
from apps.farms.models import FarmPlot
from apps.farms.tests import FarmsTestCase
from apps.territory.testing import square

from .models import CollectionRecord, ProcessedOutput
from .services import NoGridAssigned, log_collection, submit_output, tally


class OperationsTestCase(FarmsTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.register()
        self.hub = self.make_hub()
        self.grid = self.make_grid(hub=self.hub)
        self.assign(self.mitra, self.grid)
        self.straw = BiomassType.objects.get(name="Paddy straw")
        self.mustard = BiomassType.objects.get(name="Mustard stalk")
        self.pellets = Product.objects.create(
            name="Paddy pellets",
            form="processed",
            biomass_type=self.straw,
            processing_type=ProcessingType.objects.get(name="Pelletising"),
            grade="A",
        )

    def collect(self, tonnes="2", price="3000", biomass=None, **extra):
        return log_collection(
            mitra=self.mitra,
            farmer=self.farmer,
            biomass_type=biomass or self.straw,
            quantity_tonnes=Decimal(tonnes),
            price_paid=Decimal(price),
            **extra,
        )


class CollectionTests(OperationsTestCase):
    def test_a_pickup_records_quantity_price_and_the_mitras_grid(self):
        record = self.collect("2.5", "3750")
        self.assertEqual(record.code, "COL-000001")
        self.assertEqual(record.grid, self.grid)
        self.assertEqual(record.rate_per_tonne, Decimal("1500.00"))

    def test_no_grid_means_no_pickup(self):
        other = self.make_mitra("MITRA-2", mobile="9123456780")
        with self.assertRaises(NoGridAssigned):
            log_collection(mitra=other, farmer=self.farmer, biomass_type=self.straw, quantity_tonnes=1, price_paid=100)

    def test_quantity_must_be_positive(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.collect("0")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CollectionRecord.objects.create(
                mitra=self.mitra, grid=self.grid, farmer=self.farmer, biomass_type=self.straw,
                quantity_tonnes=0, price_paid=0,
            )

    def test_price_cannot_be_negative(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.collect("1", "-5")

    def test_the_plot_must_belong_to_the_farmer(self):
        from django.core.exceptions import ValidationError

        stranger = self.register("Other", "9811111111")
        plot = FarmPlot.objects.create(farmer=stranger, location=self.inside(), area_acres=1)
        with self.assertRaises(ValidationError):
            self.collect(plot=plot)

    def test_the_grid_is_kept_when_the_mitra_moves_later(self):
        record = self.collect()
        assignment = self.mitra.grid_assignments.get()
        from datetime import date

        assignment.to_date = date.today()
        assignment.save()
        record.refresh_from_db()
        self.assertEqual(record.grid, self.grid)


class OutputTests(OperationsTestCase):
    def test_output_is_reported_against_the_grid(self):
        output = submit_output(mitra=self.mitra, product=self.pellets, quantity_tonnes=Decimal("1.2"))
        self.assertEqual(output.code, "OUT-000001")
        self.assertEqual(output.grid, self.grid)

    def test_no_grid_means_no_output(self):
        other = self.make_mitra("MITRA-2", mobile="9123456780")
        with self.assertRaises(NoGridAssigned):
            submit_output(mitra=other, product=self.pellets, quantity_tonnes=1)


class TallyTests(OperationsTestCase):
    def test_running_totals_for_a_grid(self):
        self.collect("2", "3000")
        self.collect("1", "1800", biomass=self.mustard)
        result = tally(grid=self.grid)
        self.assertEqual(result.collections, 2)
        self.assertEqual(result.collected_tonnes, Decimal("3"))
        self.assertEqual(result.paid, Decimal("4800"))
        self.assertEqual(result.average_rate, Decimal("1600.00"))
        self.assertEqual(dict(result.by_biomass), {"Mustard stalk": Decimal("1"), "Paddy straw": Decimal("2")})

    def test_on_hand_subtracts_residue_reported_as_used(self):
        self.collect("5")
        submit_output(mitra=self.mitra, product=self.pellets, quantity_tonnes=Decimal("1.5"), biomass_used_tonnes=Decimal("2"))
        result = tally(grid=self.grid)
        self.assertEqual(result.on_hand_tonnes, Decimal("3"))
        self.assertEqual(result.processed_tonnes, Decimal("1.5"))
        self.assertEqual(result.by_product, [("Paddy pellets (A)", Decimal("1.500"))])

    def test_output_without_a_used_figure_does_not_change_stock(self):
        self.collect("5")
        submit_output(mitra=self.mitra, product=self.pellets, quantity_tonnes=Decimal("1"))
        self.assertEqual(tally(grid=self.grid).on_hand_tonnes, Decimal("5"))

    def test_hub_total_adds_up_its_grids(self):
        self.collect("2")
        other_grid = self.make_grid("GRID-2", hub=self.hub)
        other = self.make_mitra("MITRA-2", mobile="9123456780")
        self.assign(other, other_grid)
        log_collection(mitra=other, farmer=self.farmer, biomass_type=self.straw, quantity_tonnes=3, price_paid=100)
        self.assertEqual(tally(hub=self.hub).collected_tonnes, Decimal("5"))
        self.assertEqual(tally(grid=self.grid).collected_tonnes, Decimal("2"))

    def test_inactive_records_are_not_counted(self):
        record = self.collect("2")
        record.status = "inactive"
        record.save()
        self.assertEqual(tally(grid=self.grid).collected_tonnes, 0)

    def test_empty_tally_is_zero(self):
        result = tally(grid=self.grid)
        self.assertEqual(result.on_hand_tonnes, 0)
        self.assertIsNone(result.average_rate)
