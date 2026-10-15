"""Fill an empty database with a small, made-up Ambala (Haryana) network for testing.

Creates: geography with 8 panchayats and 16 villages, a Region with 8 GeoCells, a Hub, a
Grid holding all 8 cells, equipment, and a Mitra who can log in at /mitra/.

The panchayat shapes are plain squares, not real boundaries. Safe to re-run.
"""

from datetime import date

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role, User
from apps.geography.models import Block, District, Panchayat, State, Village
from apps.network.models import (
    Equipment,
    EquipmentType,
    Grid,
    Hub,
    Mitra,
    MitraGridAssignment,
    MitraOperatingStatus,
    OnboardingStatus,
)
from apps.territory.models import GeoCell, Region
from apps.territory.services import generate_panchayat_cells

ORIGIN_LON, ORIGIN_LAT, SIDE = 76.70, 30.30, 0.03
COLUMNS = 4
MITRA_USERNAME, MITRA_PASSWORD = "mitra1", "mitra-demo-123"
VILLAGE_NAMES = ["Khera", "Kalan", "Majra", "Nagla", "Sultanpur", "Rampur", "Bhodi", "Dhanana"]


def square(col, row):
    x, y = ORIGIN_LON + col * SIDE, ORIGIN_LAT + row * SIDE
    ring = ((x, y), (x + SIDE, y), (x + SIDE, y + SIDE), (x, y + SIDE), (x, y))
    return MultiPolygon(Polygon(ring, srid=4326), srid=4326)


class Command(BaseCommand):
    help = "Load a small demo network (Ambala, Haryana) for testing."

    @transaction.atomic
    def handle(self, *args, **options):
        state, _ = State.objects.get_or_create(lgd_code="6", defaults={"name": "Haryana"})
        district, _ = District.objects.get_or_create(
            lgd_code="43", defaults={"name": "Ambala", "state": state}
        )
        block, _ = Block.objects.get_or_create(
            lgd_code="401", defaults={"name": "Ambala I", "district": district}
        )
        for index in range(8):
            code = f"90{index + 1:02d}"
            panchayat, _ = Panchayat.objects.get_or_create(
                lgd_code=code,
                defaults={
                    "name": f"{VILLAGE_NAMES[index]} Panchayat",
                    "block": block,
                    "boundary": square(index % COLUMNS, index // COLUMNS),
                },
            )
            for number in (1, 2):
                Village.objects.get_or_create(
                    lgd_code=f"{code}{number}",
                    defaults={
                        "name": f"{VILLAGE_NAMES[index]} {'Kalan' if number == 1 else 'Khurd'}",
                        "panchayat": panchayat,
                    },
                )

        region, _ = Region.objects.get_or_create(
            code="REG-HR-AMB-001",
            defaults={"name": "Ambala Pilot", "state": state, "district": district},
        )
        generate_panchayat_cells(region)

        centre = Point(ORIGIN_LON + 2 * SIDE, ORIGIN_LAT + SIDE, srid=4326)
        hub, _ = Hub.objects.get_or_create(
            code="HUB-HR-AMB-001",
            defaults={"name": "Ambala Hub", "region": region, "location": centre, "storage_capacity_t": 500},
        )
        grid, _ = Grid.objects.get_or_create(
            code="GRID-HR-AMB-001",
            defaults={
                "name": "Ambala Grid 1",
                "region": region,
                "location": centre,
                "hub": hub,
                "processing_capacity_tpd": 40,
            },
        )
        for cell in GeoCell.objects.filter(region=region, grid__isnull=True):
            cell.grid = grid
            cell.save()

        user, made = User.objects.get_or_create(username=MITRA_USERNAME, defaults={"role": Role.MITRA})
        if made:
            user.set_password(MITRA_PASSWORD)
            user.save()
        mitra, _ = Mitra.objects.get_or_create(
            code="MITRA-DEMO-1",
            defaults={
                "name": "Demo Mitra",
                "mobile": "9876500000",
                "address": "Ambala, Haryana",
                "region": region,
                "user": user,
                "onboarding_status": OnboardingStatus.VERIFIED,
                "operating_status": MitraOperatingStatus.ACTIVE,
                "activated_on": date.today(),
            },
        )
        if not MitraGridAssignment.objects.filter(mitra=mitra, to_date__isnull=True).exists():
            MitraGridAssignment.objects.create(mitra=mitra, grid=grid, from_date=date.today())

        pelletizer = EquipmentType.objects.filter(name="Pelletizer").first()
        if pelletizer and not Equipment.objects.filter(grid=grid).exists():
            Equipment.objects.create(code="EQ-DEMO-1", equipment_type=pelletizer, grid=grid)

        self.stdout.write(self.style.SUCCESS("Demo data is ready."))
        self.stdout.write(f"Mitra page: /mitra/  username: {MITRA_USERNAME}  password: {MITRA_PASSWORD}")
