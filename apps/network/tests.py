from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError

from apps.accounts.models import Role, User
from apps.core.models import AuditLog, OperatingStatus, Status
from apps.geography.models import District
from apps.territory.models import Region
from apps.territory.testing import SIDE, TerritoryTestCase, square

from .models import Grid, Hub


class NetworkTestCase(TerritoryTestCase):
    def make_hub(self, code="HUB-HR-AMB-001", **extra):
        return Hub.objects.create(
            code=code,
            name="Ambala Hub",
            region=self.region,
            location=Point(76.78, 30.37, srid=4326),
            storage_capacity_t=Decimal("5000"),
            **extra,
        )

    def make_grid(self, code="GRID-HR-AMB-001", **extra):
        return Grid.objects.create(
            code=code,
            name="Ambala Grid",
            region=self.region,
            location=Point(76.8, 30.4, srid=4326),
            processing_capacity_tpd=Decimal("40"),
            **extra,
        )


class HubTests(NetworkTestCase):
    def test_new_hub_is_planned_and_has_no_operator_yet(self):
        hub = self.make_hub()
        self.assertEqual(hub.operating_status, OperatingStatus.PLANNED)
        self.assertIsNone(hub.operator)

    def test_hub_can_be_run_by_a_staff_user(self):
        staff = User.objects.create_user("staff1", password="pw-12345", role=Role.ADMIN)
        hub = self.make_hub(operator=staff)
        self.assertEqual(hub.operator, staff)

    def test_many_grids_can_feed_one_hub(self):
        hub = self.make_hub()
        self.make_grid("GRID-1", hub=hub)
        self.make_grid("GRID-2", hub=hub)
        self.assertEqual(hub.grids.count(), 2)


class GridTests(NetworkTestCase):
    def assign_cells(self, grid, count):
        for index in range(count):
            self.cell(f"GC-{index}", square(76.0 + index * SIDE, 30.0), grid=grid)

    def test_cells_are_linked_to_a_grid(self):
        grid = self.make_grid()
        self.assign_cells(grid, 3)
        self.assertEqual(grid.geocell_count, 3)

    def test_inactive_cells_are_not_counted(self):
        grid = self.make_grid()
        self.assign_cells(grid, 2)
        grid.geocells.first().deactivate()
        self.assertEqual(grid.geocell_count, 1)

    def test_warns_outside_the_seven_to_ten_range_but_does_not_block(self):
        grid = self.make_grid()
        self.assign_cells(grid, 3)
        self.assertIn("7 to 10", grid.geocell_count_note)

    def test_no_warning_inside_the_range(self):
        grid = self.make_grid()
        self.assign_cells(grid, 7)
        self.assertEqual(grid.geocell_count_note, "")

    def test_catchment_is_the_union_of_its_cells(self):
        grid = self.make_grid()
        self.assign_cells(grid, 2)
        # Two squares that share an edge merge into one shape of twice the area.
        self.assertAlmostEqual(grid.catchment.area, 2 * SIDE * SIDE, places=12)

    def test_grid_without_cells_has_no_catchment(self):
        self.assertIsNone(self.make_grid().catchment)

    def test_cell_cannot_join_a_grid_in_another_region(self):
        other_district = District.objects.create(
            lgd_code="44", name="Karnal", state=self.state
        )
        other_region = Region.objects.create(
            code="REG-HR-KAR-001", name="Karnal Pilot", state=self.state, district=other_district
        )
        foreign_grid = Grid.objects.create(
            code="GRID-HR-KAR-001",
            name="Karnal Grid",
            region=other_region,
            location=Point(76.9, 29.7, srid=4326),
            processing_capacity_tpd=Decimal("30"),
        )
        cell = self.cell("GC-1", square(76.0, 30.0))
        cell.grid = foreign_grid
        with self.assertRaises(ValidationError) as caught:
            cell.clean()
        self.assertIn("grid", caught.exception.message_dict)

    def test_moving_a_cell_between_grids_is_recorded_in_the_audit_log(self):
        first, second = self.make_grid("GRID-1"), self.make_grid("GRID-2")
        cell = self.cell("GC-1", square(76.0, 30.0), grid=first)
        cell.grid = second
        cell.save()
        log = AuditLog.objects.filter(object_id=str(cell.pk)).first()
        self.assertEqual(log.changes["grid"], [str(first.pk), str(second.pk)])

    def test_new_grid_is_active(self):
        self.assertEqual(self.make_grid().status, Status.ACTIVE)
