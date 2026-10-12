from django.core.management.base import BaseCommand, CommandError

from apps.territory.models import Region
from apps.territory.services import generate_panchayat_cells


class Command(BaseCommand):
    help = "Create one GeoCell per panchayat for a Region (safe to re-run)."

    def add_arguments(self, parser):
        parser.add_argument("region_code", help="Region code, for example REG-HR-AMB-001")

    def handle(self, region_code, **options):
        try:
            region = Region.objects.get(code=region_code)
        except Region.DoesNotExist:
            raise CommandError(f"No Region with code {region_code}.")
        result = generate_panchayat_cells(region)
        self.stdout.write(
            self.style.SUCCESS(
                f"{region.code}: {result.created} cells created, "
                f"{result.already_existing} already existed."
            )
        )
        if result.missing_boundary:
            self.stdout.write(
                self.style.WARNING(
                    f"{result.missing_boundary} panchayats have no boundary yet and were skipped."
                )
            )
