from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.models import Status

from .models import Equipment, EquipmentType
from .test_mitra import MitraTestCase


class EquipmentTestCase(MitraTestCase):
    def make_equipment(self, code="EQ-1", type_name="Pelletizer", **extra):
        return Equipment.objects.create(
            code=code,
            equipment_type=EquipmentType.objects.get(name=type_name),
            **extra,
        )


class EquipmentTypeTests(EquipmentTestCase):
    def test_starter_types_are_available(self):
        names = set(EquipmentType.objects.values_list("name", flat=True))
        self.assertEqual(
            names,
            {"Pelletizer", "Baler", "Shredder", "Tractor", "Collection vehicle", "Weighbridge"},
        )


class EquipmentTests(EquipmentTestCase):
    def test_equipment_can_sit_at_a_grid(self):
        grid = self.make_grid()
        machine = self.make_equipment(grid=grid, capacity=Decimal("2.5"), capacity_unit="t_per_hour")
        machine.clean()
        self.assertEqual(list(grid.equipment.all()), [machine])

    def test_equipment_can_sit_at_a_hub(self):
        hub = self.make_hub()
        machine = self.make_equipment(type_name="Weighbridge", hub=hub)
        machine.clean()
        self.assertEqual(machine.hub, hub)

    def test_equipment_cannot_sit_at_both_a_grid_and_a_hub(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_equipment(grid=self.make_grid(), hub=self.make_hub())

    def test_equipment_must_sit_somewhere(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_equipment()

    def test_form_message_when_no_site_is_chosen(self):
        machine = Equipment(
            code="EQ-X", equipment_type=EquipmentType.objects.get(name="Baler")
        )
        with self.assertRaises(ValidationError) as caught:
            machine.clean()
        self.assertIn("Grid or a Hub", str(caught.exception))

    def test_capacity_needs_a_unit(self):
        machine = self.make_equipment(grid=self.make_grid(), capacity=Decimal("3"))
        with self.assertRaises(ValidationError) as caught:
            machine.clean()
        self.assertIn("capacity_unit", caught.exception.message_dict)

    def test_next_maintenance_cannot_be_before_the_last_one(self):
        machine = self.make_equipment(
            grid=self.make_grid(),
            last_maintenance=date(2026, 6, 1),
            next_maintenance=date(2026, 5, 1),
        )
        with self.assertRaises(ValidationError) as caught:
            machine.clean()
        self.assertIn("next_maintenance", caught.exception.message_dict)

    def test_equipment_code_is_unique(self):
        grid = self.make_grid()
        self.make_equipment("EQ-1", grid=grid)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_equipment("EQ-1", grid=grid)


class MitraEquipmentTests(EquipmentTestCase):
    def test_mitra_equipment_comes_from_their_grid(self):
        mitra, grid = self.make_mitra(), self.make_grid()
        self.assign(mitra, grid)
        self.make_equipment("EQ-1", "Pelletizer", grid=grid)
        self.make_equipment("EQ-2", "Baler", grid=grid)
        self.make_equipment("EQ-3", "Tractor", grid=self.make_grid("GRID-OTHER"))
        self.assertEqual(
            sorted(mitra.equipment.values_list("code", flat=True)), ["EQ-1", "EQ-2"]
        )

    def test_deactivated_equipment_is_not_counted(self):
        mitra, grid = self.make_mitra(), self.make_grid()
        self.assign(mitra, grid)
        machine = self.make_equipment("EQ-1", grid=grid)
        machine.deactivate()
        self.assertEqual(machine.status, Status.INACTIVE)
        self.assertEqual(mitra.equipment.count(), 0)
