from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.reference.models import BiomassType, ProcessingType, Product

from .models import Buyer, Factory


def make_buyer(**extra):
    defaults = {
        "company_name": "Green Power Ltd",
        "contact_name": "Anil Verma",
        "contact_mobile": "9876543210",
        "payment_terms": "Within 15 days of delivery",
    }
    defaults.update(extra)
    return Buyer.objects.create(**defaults)


def make_factory(buyer, **extra):
    defaults = {
        "name": "Panipat Plant",
        "location": Point(76.97, 29.39, srid=4326),
        "delivery_address": "Industrial Area, Panipat",
    }
    defaults.update(extra)
    return Factory.objects.create(buyer=buyer, **defaults)


class BuyerTests(TestCase):
    def test_buyer_gets_a_code_and_starts_as_a_prospect(self):
        buyer = make_buyer()
        self.assertEqual(buyer.code, "BUY-000001")
        self.assertEqual(buyer.commercial_status, "prospect")

    def test_gst_number_is_checked_and_uppercased(self):
        buyer = make_buyer(gst_number="06abcde1234f1z5")
        buyer.full_clean()
        self.assertEqual(buyer.gst_number, "06ABCDE1234F1Z5")
        buyer.gst_number = "NOT-A-GST"
        with self.assertRaises(ValidationError) as caught:
            buyer.full_clean()
        self.assertIn("gst_number", caught.exception.message_dict)

    def test_gst_number_is_optional(self):
        make_buyer().full_clean()

    def test_payment_terms_are_required(self):
        buyer = make_buyer()
        buyer.payment_terms = ""
        with self.assertRaises(ValidationError) as caught:
            buyer.full_clean()
        self.assertIn("payment_terms", caught.exception.message_dict)

    def test_contact_details_stay_out_of_the_audit_log(self):
        buyer = make_buyer()
        buyer.contact_name = "Someone Else"
        buyer.save()
        text = " ".join(
            str(log.changes) for log in AuditLog.objects.filter(object_id=str(buyer.pk))
        )
        self.assertNotIn("Anil", text)
        self.assertNotIn("9876543210", text)

    def test_a_login_belongs_to_at_most_one_buyer(self):
        user = User.objects.create_user(username="b1", password="x", role=Role.BUYER)
        make_buyer(user=user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_buyer(company_name="Other", user=user)


class FactoryTests(TestCase):
    def test_factory_belongs_to_a_buyer_and_gets_a_code(self):
        buyer = make_buyer()
        factory = make_factory(buyer)
        self.assertEqual(factory.code, "FAC-000001")
        self.assertEqual(list(buyer.factories.all()), [factory])

    def test_a_buyer_can_have_several_factories(self):
        buyer = make_buyer()
        make_factory(buyer, name="A")
        make_factory(buyer, name="B")
        self.assertEqual(buyer.factories.count(), 2)

    def test_preferred_biomass_types_and_quality_limits(self):
        factory = make_factory(make_buyer(), minimum_gcv=Decimal("3200"), maximum_moisture_percent=Decimal("15"))
        factory.preferred_biomass_types.add(BiomassType.objects.get(name="Paddy straw"))
        factory.full_clean()
        self.assertEqual(factory.preferred_biomass_types.count(), 1)

    def test_moisture_cannot_exceed_100_percent(self):
        factory = make_factory(make_buyer(), maximum_moisture_percent=Decimal("120"))
        with self.assertRaises(ValidationError):
            factory.full_clean()


class ProcessingAndProductTests(TestCase):
    def setUp(self):
        self.paddy_straw = BiomassType.objects.get(name="Paddy straw")
        self.pelletising = ProcessingType.objects.get(name="Pelletising")

    def test_starter_processing_types_exist(self):
        names = set(ProcessingType.objects.values_list("name", flat=True))
        self.assertTrue({"Baling", "Pelletising", "Shredding", "Briquetting"} <= names)

    def test_processing_type_lists_the_biomass_it_accepts(self):
        self.pelletising.input_biomass_types.add(self.paddy_straw)
        self.assertIn(self.pelletising, self.paddy_straw.processing_types.all())

    def test_a_processed_product_needs_a_processing_type(self):
        product = Product(name="Pellets", form="processed", biomass_type=self.paddy_straw)
        with self.assertRaises(ValidationError) as caught:
            product.clean()
        self.assertIn("processing_type", caught.exception.message_dict)
        with self.assertRaises(IntegrityError), transaction.atomic():
            product.save()

    def test_a_raw_product_has_no_processing_type(self):
        product = Product(name="Loose straw", form="raw", biomass_type=self.paddy_straw, processing_type=self.pelletising)
        with self.assertRaises(ValidationError):
            product.clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            product.save()

    def test_products_come_in_grades_and_names_are_unique_per_grade(self):
        Product.objects.create(
            name="Paddy pellets", form="processed", biomass_type=self.paddy_straw,
            processing_type=self.pelletising, grade="A", minimum_gcv=3500,
        )
        Product.objects.create(
            name="Paddy pellets", form="processed", biomass_type=self.paddy_straw,
            processing_type=self.pelletising, grade="B",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.create(
                name="Paddy pellets", form="processed", biomass_type=self.paddy_straw,
                processing_type=self.pelletising, grade="A",
            )
        self.assertEqual(self.pelletising.products.count(), 2)

    def test_gcv_range_must_be_in_order(self):
        self.paddy_straw.gcv_min, self.paddy_straw.gcv_max = 3000, 2000
        with self.assertRaises(ValidationError):
            self.paddy_straw.clean()
