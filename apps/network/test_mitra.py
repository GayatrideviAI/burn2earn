from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import Role, User
from apps.core.models import Status
from apps.territory.testing import SIDE, square

from .models import Grid, Mitra, MitraGridAssignment, MitraOperatingStatus
from .tests import NetworkTestCase


class MitraTestCase(NetworkTestCase):
    def make_mitra(self, code="MITRA-1", **extra):
        defaults = {
            "name": "Gurpreet Singh",
            "mobile": "9876543210",
            "address": "Village Road, Ambala",
            "region": self.region,
        }
        defaults.update(extra)
        return Mitra.objects.create(code=code, **defaults)

    def assign(self, mitra, grid, from_date=date(2026, 1, 1), **extra):
        return MitraGridAssignment.objects.create(
            mitra=mitra, grid=grid, from_date=from_date, **extra
        )


class MitraTests(MitraTestCase):
    def test_new_mitra_is_invited_and_not_yet_operating(self):
        mitra = self.make_mitra()
        self.assertEqual(mitra.onboarding_status, "invited")
        self.assertEqual(mitra.operating_status, MitraOperatingStatus.PENDING)

    def test_mobile_number_is_checked(self):
        mitra = self.make_mitra(mobile="12345")
        with self.assertRaises(ValidationError) as caught:
            mitra.full_clean()
        self.assertIn("mobile", caught.exception.message_dict)

    def test_active_mitra_needs_an_activation_date(self):
        mitra = self.make_mitra(operating_status=MitraOperatingStatus.ACTIVE)
        with self.assertRaises(ValidationError) as caught:
            mitra.clean()
        self.assertIn("activated_on", caught.exception.message_dict)
        mitra.activated_on = date(2026, 2, 1)
        mitra.clean()

    def test_login_must_have_the_mitra_role(self):
        wrong = User.objects.create_user("farmer1", password="pw-12345", role=Role.FARMER)
        mitra = self.make_mitra(user=wrong)
        with self.assertRaises(ValidationError) as caught:
            mitra.clean()
        self.assertIn("user", caught.exception.message_dict)

    def test_one_login_cannot_belong_to_two_mitras(self):
        login = User.objects.create_user("mitra1", password="pw-12345", role=Role.MITRA)
        self.make_mitra("MITRA-1", user=login)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_mitra("MITRA-2", user=login)


class AssignmentTests(MitraTestCase):
    def test_mitra_and_grid_find_each_other(self):
        mitra, grid = self.make_mitra(), self.make_grid()
        self.assign(mitra, grid)
        self.assertEqual(mitra.current_grid, grid)
        self.assertEqual(grid.current_mitra, mitra)

    def test_mitra_without_an_assignment_has_no_grid_cells_or_equipment(self):
        mitra = self.make_mitra()
        self.assertIsNone(mitra.current_grid)
        self.assertEqual(mitra.geocells.count(), 0)
        self.assertEqual(mitra.equipment.count(), 0)

    def test_mitra_cells_come_from_their_grid(self):
        mitra, grid = self.make_mitra(), self.make_grid()
        self.assign(mitra, grid)
        self.cell("GC-1", square(76.0, 30.0), grid=grid)
        self.cell("GC-2", square(76.0 + SIDE, 30.0), grid=grid)
        self.cell("GC-3", square(77.0, 30.0))  # not in the grid
        self.assertEqual(mitra.geocells.count(), 2)

    def test_a_grid_has_only_one_current_mitra(self):
        grid = self.make_grid()
        self.assign(self.make_mitra("MITRA-1"), grid)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.assign(self.make_mitra("MITRA-2"), grid)

    def test_a_mitra_has_only_one_current_grid(self):
        mitra = self.make_mitra()
        self.assign(mitra, self.make_grid("GRID-1"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.assign(mitra, self.make_grid("GRID-2"))

    def test_form_gives_a_readable_message_for_a_second_current_mitra(self):
        grid = self.make_grid()
        self.assign(self.make_mitra("MITRA-1"), grid)
        second = MitraGridAssignment(
            mitra=self.make_mitra("MITRA-2"), grid=grid, from_date=date(2026, 3, 1)
        )
        with self.assertRaises(ValidationError) as caught:
            second.clean()
        self.assertIn("already has a current Mitra", str(caught.exception))

    def test_ending_an_assignment_frees_the_grid_and_keeps_history(self):
        grid = self.make_grid()
        first = self.make_mitra("MITRA-1")
        old = self.assign(first, grid, from_date=date(2026, 1, 1))
        old.to_date = date(2026, 6, 30)
        old.save()

        replacement = self.make_mitra("MITRA-2")
        self.assign(replacement, grid, from_date=date(2026, 7, 1))

        self.assertEqual(grid.current_mitra, replacement)
        self.assertIsNone(first.current_grid)
        self.assertEqual(grid.mitra_assignments.count(), 2)

    def test_deactivated_assignment_is_not_current(self):
        mitra, grid = self.make_mitra(), self.make_grid()
        assignment = self.assign(mitra, grid)
        assignment.deactivate()
        self.assertIsNone(grid.current_mitra)

    def test_end_date_cannot_be_before_start_date(self):
        mitra, grid = self.make_mitra(), self.make_grid()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.assign(mitra, grid, from_date=date(2026, 5, 1), to_date=date(2026, 4, 1))

    def test_mitra_and_grid_must_be_in_the_same_region(self):
        other_region = self.make_other_region()
        foreign_grid = Grid.objects.create(
            code="GRID-OTHER",
            name="Other Grid",
            region=other_region,
            location=self.make_grid().location,
            processing_capacity_tpd=10,
        )
        assignment = MitraGridAssignment(
            mitra=self.make_mitra(), grid=foreign_grid, from_date=date(2026, 1, 1)
        )
        with self.assertRaises(ValidationError) as caught:
            assignment.clean()
        self.assertIn("grid", caught.exception.message_dict)

    def test_assignments_start_out_active(self):
        assignment = self.assign(self.make_mitra(), self.make_grid())
        self.assertEqual(assignment.status, Status.ACTIVE)
