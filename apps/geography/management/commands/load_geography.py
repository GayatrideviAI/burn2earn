"""Load State > District > Block > Panchayat > Village from one flat CSV.

Required columns:
    state_lgd, state_name, district_lgd, district_name,
    block_lgd, block_name, panchayat_lgd, panchayat_name
Optional columns:
    village_lgd, village_name

Safe to re-run: existing rows are matched on their LGD code and updated.
"""

import csv
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.geography.models import Block, District, Panchayat, State, Village

REQUIRED_COLUMNS = {
    "state_lgd",
    "state_name",
    "district_lgd",
    "district_name",
    "block_lgd",
    "block_name",
    "panchayat_lgd",
    "panchayat_name",
}


class Command(BaseCommand):
    help = "Load LGD geography (state to village) from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the CSV file")

    @transaction.atomic
    def handle(self, csv_path, **options):
        created = Counter()
        with open(csv_path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"CSV is missing columns: {', '.join(sorted(missing))}")

            for row in reader:
                state, made = State.objects.update_or_create(
                    lgd_code=row["state_lgd"].strip(),
                    defaults={"name": row["state_name"].strip()},
                )
                created["states"] += made

                district, made = District.objects.update_or_create(
                    lgd_code=row["district_lgd"].strip(),
                    defaults={"name": row["district_name"].strip(), "state": state},
                )
                created["districts"] += made

                block, made = Block.objects.update_or_create(
                    lgd_code=row["block_lgd"].strip(),
                    defaults={"name": row["block_name"].strip(), "district": district},
                )
                created["blocks"] += made

                panchayat, made = Panchayat.objects.update_or_create(
                    lgd_code=row["panchayat_lgd"].strip(),
                    defaults={"name": row["panchayat_name"].strip(), "block": block},
                )
                created["panchayats"] += made

                village_code = (row.get("village_lgd") or "").strip()
                if village_code:
                    _, made = Village.objects.update_or_create(
                        lgd_code=village_code,
                        defaults={
                            "name": (row.get("village_name") or "").strip(),
                            "panchayat": panchayat,
                        },
                    )
                    created["villages"] += made

        summary = ", ".join(f"{count} new {name}" for name, count in created.items())
        self.stdout.write(self.style.SUCCESS(f"Loaded geography: {summary or 'nothing new'}."))
