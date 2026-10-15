from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.reference.models import BiomassType, ProcessingType, Product

from .models import Requirement
from .tests import make_buyer, make_factory


class RequirementTests(TestCase):
    def setUp(self):
        self.factory = make_factory(make_buyer())
        self.product = Product.objects.create(
            name="Paddy pellets",
            form="processed",
            biomass_type=BiomassType.objects.get(name="Paddy straw"),
            processing_type=ProcessingType.objects.get(name="Pelletising"),
            grade="A",
        )

    def post(self, **extra):
        values = {
            "factory": self.factory,
            "product": self.product,
            "volume_tonnes": Decimal("100"),
            "needed_from": date(2026, 11, 1),
            "needed_by": date(2026, 11, 30),
        }
        values.update(extra)
        return Requirement.objects.create(**values)

    def test_posting_a_requirement_starts_open_with_a_code(self):
        requirement = self.post(target_gcv=3200, quality_notes="Moisture under 15%")
        self.assertEqual(requirement.code, "REQ-000001")
        self.assertEqual(requirement.fulfilment, "open")
        self.assertEqual(requirement.volume_met_tonnes, 0)
        self.assertEqual(requirement.volume_remaining, Decimal("100"))

    def test_target_gcv_is_optional_and_never_checked(self):
        requirement = self.post()
        requirement.full_clean()
        self.assertIsNone(requirement.target_gcv)
        # Far above the product's grade minimum: still accepted, a person decides.
        self.post(target_gcv=9000).full_clean()

    def test_volume_must_be_positive(self):
        unsaved = Requirement(
            factory=self.factory,
            product=self.product,
            volume_tonnes=Decimal("0"),
            needed_from=date(2026, 11, 1),
            needed_by=date(2026, 11, 30),
        )
        with self.assertRaises(ValidationError):
            unsaved.full_clean(exclude=["code"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.post(volume_tonnes=Decimal("0"))

    def test_latest_date_cannot_be_before_the_earliest(self):
        requirement = self.post()
        requirement.needed_by = date(2026, 10, 1)
        with self.assertRaises(ValidationError) as caught:
            requirement.clean()
        self.assertIn("needed_by", caught.exception.message_dict)
        with self.assertRaises(IntegrityError), transaction.atomic():
            requirement.save()

    def test_volume_met_cannot_exceed_volume_needed(self):
        requirement = self.post()
        requirement.volume_met_tonnes = Decimal("150")
        with self.assertRaises(ValidationError) as caught:
            requirement.clean()
        self.assertIn("volume_met_tonnes", caught.exception.message_dict)

    def test_remaining_volume_after_a_partial_delivery(self):
        requirement = self.post()
        requirement.volume_met_tonnes = Decimal("40")
        requirement.fulfilment = Requirement.Fulfilment.PARTLY
        requirement.save()
        self.assertEqual(requirement.volume_remaining, Decimal("60"))

    def test_admin_lists_requirements_with_what_has_been_produced(self):
        from apps.network.models import Grid, Hub, Mitra  # noqa: F401  (ensures apps are loaded)
        from apps.operations.models import ProcessedOutput  # noqa: F401

        user = get_user_model().objects.create_superuser(username="boss", password="pw-12345-x")
        self.client.force_login(user)
        self.post()
        response = self.client.get("/admin/demand/requirement/")
        self.assertContains(response, "REQ-000001")
        self.assertContains(response, "Produced so far")
        self.assertEqual(self.client.get("/admin/demand/requirement/add/").status_code, 200)
