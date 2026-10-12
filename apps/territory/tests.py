from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.models import Status
from apps.geography.models import State

from .models import GeoCell, Region
from .services import generate_panchayat_cells
from .testing import SIDE, TerritoryTestCase, square


class RegionTests(TerritoryTestCase):
    def test_district_must_belong_to_the_state(self):
        other_state = State.objects.create(lgd_code="3", name="Punjab")
        region = Region(code="REG-X", name="X", state=other_state, district=self.district)
        with self.assertRaises(ValidationError):
            region.clean()


class GeoCellTests(TerritoryTestCase):
    def test_area_in_acres_and_centre_are_derived_from_the_boundary(self):
        cell = self.cell("GC-1", square(76.0, 30.0))
        cell.refresh_from_db()
        # 1/64 degree is about 1.7 km on each side: roughly 700 acres.
        self.assertGreater(cell.area_acres, 500)
        self.assertLess(cell.area_acres, 900)
        self.assertAlmostEqual(cell.center_point.x, 76.0 + SIDE / 2, places=6)
        self.assertAlmostEqual(cell.center_point.y, 30.0 + SIDE / 2, places=6)

    def test_cells_may_share_an_edge(self):
        self.cell("GC-1", square(76.0, 30.0))
        self.cell("GC-2", square(76.0 + SIDE, 30.0))
        self.assertEqual(GeoCell.objects.count(), 2)

    def test_overlapping_cell_is_rejected_by_the_database(self):
        self.cell("GC-1", square(76.0, 30.0))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.cell("GC-2", square(76.0 + SIDE / 2, 30.0))
        self.assertEqual(GeoCell.objects.count(), 1)

    def test_overlap_gives_a_readable_form_error(self):
        self.cell("GC-1", square(76.0, 30.0))
        candidate = GeoCell(
            code="GC-2",
            region=self.region,
            panchayat=self.panchayat("p-2"),
            boundary=square(76.0 + SIDE / 2, 30.0),
        )
        with self.assertRaises(ValidationError) as caught:
            candidate.clean()
        self.assertIn("boundary", caught.exception.message_dict)

    def test_inactive_cells_do_not_block_new_ones(self):
        old = self.cell("GC-1", square(76.0, 30.0))
        old.deactivate()
        self.cell("GC-2", square(76.0, 30.0))
        self.assertEqual(GeoCell.objects.filter(status=Status.ACTIVE).count(), 1)

    def test_one_active_cell_per_panchayat(self):
        shared = self.panchayat("9001")
        self.cell("GC-1", square(76.0, 30.0), panchayat=shared)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.cell("GC-2", square(77.0, 30.0), panchayat=shared)

    def test_panchayat_cell_needs_a_panchayat(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            GeoCell.objects.create(
                code="GC-X",
                region=self.region,
                origin=GeoCell.Origin.PANCHAYAT,
                boundary=square(76.0, 30.0),
            )

    def test_mitra_drawn_cell_needs_no_panchayat(self):
        cell = GeoCell.objects.create(
            code="GC-M1",
            region=self.region,
            origin=GeoCell.Origin.MITRA_DRAWN,
            boundary=square(76.0, 30.0),
        )
        self.assertIsNone(cell.panchayat)


class GenerateCellsTests(TerritoryTestCase):
    def test_creates_one_cell_per_panchayat_with_a_boundary(self):
        self.panchayat("9001", square(76.0, 30.0))
        self.panchayat("9002", square(76.0 + SIDE, 30.0))
        self.panchayat("9003")  # no boundary yet

        result = generate_panchayat_cells(self.region)

        self.assertEqual(result.created, 2)
        self.assertEqual(result.missing_boundary, 1)
        cell = GeoCell.objects.get(code="GC-9001")
        self.assertEqual(cell.origin, GeoCell.Origin.PANCHAYAT)
        self.assertEqual(cell.region, self.region)

    def test_rerunning_creates_nothing_new(self):
        self.panchayat("9001", square(76.0, 30.0))
        generate_panchayat_cells(self.region)
        result = generate_panchayat_cells(self.region)
        self.assertEqual(result.created, 0)
        self.assertEqual(result.already_existing, 1)
        self.assertEqual(GeoCell.objects.count(), 1)
