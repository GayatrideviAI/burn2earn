"""Add a made-up power-plant customer with four yards of stock, to try the customer pages.

Log in at /customer/ as customer1 / customer-demo-123. The figures are invented. Safe to re-run.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role, User
from apps.customers import services
from apps.customers.models import (
    Batch,
    CustomerMember,
    JobRole,
    PlantProfile,
    Pile,
    Stockyard,
)
from apps.demand.models import Buyer, Factory
from apps.reference.models import BiomassType

COMPANY = "Sample Power Ltd"
PASSWORD = "customer-demo-123"

YARDS = [
    ("Yard A", Point(76.78, 30.37, srid=4326), "Ambala"),
    ("Yard B", Point(76.84, 29.97, srid=4326), "Kurukshetra"),
    ("Yard C", Point(76.99, 29.69, srid=4326), "Karnal"),
    ("Yard D", Point(76.97, 29.39, srid=4326), "Panipat"),
]
# yard index, pile label, form, exposure, cover, book t, counted t, days since count, moisture %, reserved t
BATCHES = [
    (0, "A-01", "bales", "open", "Tarp, one corner loose", 1200, 1200, 3, 14, 300),
    (0, "A-02", "bales", "protected", "Shed", 1300, 1100, 9, 12, 0),
    (0, "A-03", "loose", "part", "Half roofed", 700, 600, 12, 19, 0),
    (1, "B-01", "pellets", "protected", "Shed", 1400, 1400, 4, 9, 0),
    (1, "B-02", "bales", "part", "Tarp on top", 700, 700, 4, 15, 200),
    (1, "B-03", "bales", "open", "None", 300, 300, 4, None, 0),
    (2, "C-01", "pellets", "protected", "Roofed shed", 1550, 1500, 21, 8, 500),
    (2, "C-02", "briquettes", "protected", "Roofed shed", 1050, 1000, 21, 8, 0),
    (3, "D-01", "bales", "open", "Tarp", 900, 900, 6, 15, 200),
    (3, "D-02", "bales", "open", "Tarp", 600, 600, 6, 18, 0),
    (3, "D-03", "pellets", "protected", "Shed", 600, 500, 6, 9, 0),
]


class Command(BaseCommand):
    help = "Add a demo customer (Sample Power Ltd) with yards, piles, batches and counts."

    @transaction.atomic
    def handle(self, *args, **options):
        if Buyer.objects.filter(company_name=COMPANY).exists():
            self.stdout.write("Demo customer already exists. Log in at /customer/ as customer1 / " + PASSWORD)
            return
        buyer = Buyer.objects.create(
            company_name=COMPANY, contact_name="Anil Verma", contact_mobile="9876543210",
            payment_terms="Within 15 days of delivery", commercial_status="active",
        )
        plant = Factory.objects.create(
            buyer=buyer, name="Panipat plant", location=Point(76.97, 29.39, srid=4326),
            delivery_address="Industrial Area, Panipat", maximum_moisture_percent=Decimal("18"), operating_status="operating",
        )
        PlantProfile.objects.create(factory=plant, daily_consumption_tonnes=Decimal("300"))
        user = User.objects.create_user(username="customer1", password=PASSWORD, role=Role.BUYER)
        CustomerMember.objects.create(user=user, buyer=buyer, job_role=JobRole.PROCUREMENT)

        yards = [
            Stockyard.objects.create(name=name, location=point, owner_type="regenerix", notes=f"Sample yard near {place}")
            for name, point, place in YARDS
        ]
        straw = BiomassType.objects.get(name="Paddy straw")
        for yi, label, form, exposure, cover, book, counted, days, moisture, reserved in BATCHES:
            pile = Pile.objects.create(yard=yards[yi], label=label, form=form, exposure=exposure, cover_type=cover)
            batch = Batch.objects.create(
                customer=buyer, pile=pile, biomass_type=straw, form=form, received_on=date.today() - timedelta(days=40),
                intake_tonnes=Decimal(book), intake_moisture_percent=None if moisture is None else Decimal(moisture),
                source_note="Sample villages near Ambala, VLE sample",
            )
            services.receive_batch(batch)
            services.record_count(batch, Decimal(counted), "audit", counted_on=date.today() - timedelta(days=days), counted_by="Yard supervisor")
            if reserved:
                services.reserve(batch, plant, Decimal(reserved), "Held for the plant")
        self.stdout.write(self.style.SUCCESS(f"Demo customer ready. Log in at /customer/ as customer1 / {PASSWORD}"))
