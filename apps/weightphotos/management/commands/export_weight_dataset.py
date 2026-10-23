import csv
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.weightphotos.admin import CSV_COLUMNS, rows_for
from apps.weightphotos.models import WeightPhoto


class Command(BaseCommand):
    help = "Write the photos that have a weighed figure to a folder: images/ and labels.csv, ready for training."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="A new or empty folder to write into")

    def handle(self, folder, **options):
        out = Path(folder)
        if out.exists() and any(out.iterdir()):
            raise CommandError(f"{out} is not empty.")
        (out / "images").mkdir(parents=True, exist_ok=True)
        photos = WeightPhoto.objects.filter(weighed_tonnes__isnull=False, status="active")
        with open(out / "labels.csv", "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_COLUMNS)
            writer.writerows(rows_for(photos))
        for photo in photos:
            with photo.image.open("rb") as source, open(out / "images" / f"{photo.code}.jpg", "wb") as target:
                shutil.copyfileobj(source, target)
        self.stdout.write(f"{photos.count()} photos written to {out}. In labels.csv the image column is the path under media/; the copy in images/ is named by code.")
