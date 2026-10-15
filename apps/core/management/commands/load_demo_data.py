"""Fill an empty database with small, made-up networks for testing.

Three sites are available: Ambala (Haryana), Kanchipuram (Tamil Nadu) and Talwandi Sabo (Punjab). Each gets geography
with panchayats and villages, a Region with one GeoCell per panchayat, a Hub, a Grid holding
all the cells, a pelletizer, and a Mitra who can log in at /mitra/.

The panchayat shapes are plain squares and the names, other than the state, district and
block names, are samples, not official LGD data. Safe to re-run.
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

SIDE = 0.03
COLUMNS = 4
MITRA_PASSWORD = "mitra-demo-123"

SITES = {
    "haryana": {
        "state": ("6", "Haryana"),
        "district": ("43", "Ambala"),
        "block": ("401", "Ambala I"),
        "panchayat_prefix": "90",
        "origin": (76.70, 30.30),
        "villages": ["Khera", "Kalan", "Majra", "Nagla", "Sultanpur", "Rampur", "Bhodi", "Dhanana"],
        "region": ("REG-HR-AMB-001", "Ambala Pilot"),
        "hub": ("HUB-HR-AMB-001", "Ambala Hub"),
        "grid": ("GRID-HR-AMB-001", "Ambala Grid 1"),
        "mitra": ("MITRA-DEMO-1", "Demo Mitra", "mitra1", "9876500000", "Ambala, Haryana"),
        "equipment": "EQ-DEMO-1",
    },
    "tamilnadu": {
        "state": ("33", "Tamil Nadu"),
        "district": ("demo-kpm", "Kanchipuram"),
        "block": ("demo-kpm-1", "Kanchipuram"),
        "panchayat_prefix": "91",
        "origin": (79.62, 12.78),
        "villages": ["Thimmasamudram", "Sirunaiperugal", "Kalakattoor", "Orikkai", "Pallur", "Thenambakkam"],
        "region": ("REG-TN-KAN-001", "Kanchipuram Pilot"),
        "hub": ("HUB-TN-KAN-001", "Kanchipuram Hub"),
        "grid": ("GRID-TN-KAN-001", "Kanchipuram Grid 1"),
        "mitra": ("MITRA-DEMO-2", "Demo Mitra Kanchipuram", "mitra2", "9876500001", "Kanchipuram, Tamil Nadu"),
        "equipment": "EQ-DEMO-2",
    },
    "punjab": {
        "state": ("3", "Punjab"),
        "district": ("demo-bti", "Bathinda"),
        "block": ("demo-bti-1", "Talwandi Sabo"),
        "panchayat_prefix": "92",
        "origin": (75.05, 29.96),
        "villages": ["Talwandi Sabo", "Jajjal", "Bangi", "Giana", "Maiser Khana", "Lehra"],
        "region": ("REG-PB-TAL-001", "Talwandi Sabo Pilot"),
        "hub": ("HUB-PB-TAL-001", "Talwandi Sabo Hub"),
        "grid": ("GRID-PB-TAL-001", "Talwandi Sabo Grid 1"),
        "mitra": ("MITRA-DEMO-3", "Demo Mitra Talwandi", "mitra3", "9876500002", "Talwandi Sabo, Punjab"),
        "equipment": "EQ-DEMO-3",
    },
}


def square(origin, col, row):
    x, y = origin[0] + col * SIDE, origin[1] + row * SIDE
    ring = ((x, y), (x + SIDE, y), (x + SIDE, y + SIDE), (x, y + SIDE), (x, y))
    return MultiPolygon(Polygon(ring, srid=4326), srid=4326)


class Command(BaseCommand):
    help = "Load small demo networks (Ambala, Kanchipuram, Talwandi Sabo) for testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--site",
            choices=[*SITES, "all"],
            default="all",
            help="Which demo network to load (default: all)",
        )

    @transaction.atomic
    def handle(self, *args, site="all", **options):
        names = list(SITES) if site == "all" else [site]
        for name in names:
            self.load_site(SITES[name])
        self.stdout.write(self.style.SUCCESS("Demo data is ready."))

    def load_site(self, site):
        origin = site["origin"]
        state, _ = State.objects.get_or_create(
            lgd_code=site["state"][0], defaults={"name": site["state"][1]}
        )
        district, _ = District.objects.get_or_create(
            lgd_code=site["district"][0], defaults={"name": site["district"][1], "state": state}
        )
        block, _ = Block.objects.get_or_create(
            lgd_code=site["block"][0], defaults={"name": site["block"][1], "district": district}
        )
        for index, village_name in enumerate(site["villages"]):
            code = f"{site['panchayat_prefix']}{index + 1:02d}"
            panchayat, _ = Panchayat.objects.get_or_create(
                lgd_code=code,
                defaults={
                    "name": f"{village_name} Panchayat",
                    "block": block,
                    "boundary": square(origin, index % COLUMNS, index // COLUMNS),
                },
            )
            for number in (1, 2):
                Village.objects.get_or_create(
                    lgd_code=f"{code}{number}",
                    defaults={
                        "name": village_name if number == 1 else f"{village_name} Colony",
                        "panchayat": panchayat,
                    },
                )

        region, _ = Region.objects.get_or_create(
            code=site["region"][0],
            defaults={"name": site["region"][1], "state": state, "district": district},
        )
        generate_panchayat_cells(region)

        centre = Point(origin[0] + SIDE, origin[1] + SIDE / 2, srid=4326)
        hub, _ = Hub.objects.get_or_create(
            code=site["hub"][0],
            defaults={"name": site["hub"][1], "region": region, "location": centre, "storage_capacity_t": 500},
        )
        grid, _ = Grid.objects.get_or_create(
            code=site["grid"][0],
            defaults={
                "name": site["grid"][1],
                "region": region,
                "location": centre,
                "hub": hub,
                "processing_capacity_tpd": 40,
            },
        )
        for cell in GeoCell.objects.filter(region=region, grid__isnull=True):
            cell.grid = grid
            cell.save()

        code, name, username, mobile, address = site["mitra"]
        user, made = User.objects.get_or_create(username=username, defaults={"role": Role.MITRA})
        if made:
            user.set_password(MITRA_PASSWORD)
            user.save()
        mitra, _ = Mitra.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "mobile": mobile,
                "address": address,
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
            Equipment.objects.create(code=site["equipment"], equipment_type=pelletizer, grid=grid)

        self.stdout.write(
            f"{site['region'][1]}: Mitra page /mitra/  username: {username}  password: {MITRA_PASSWORD}"
        )
