from django.core.management.base import BaseCommand

from apps.weightphotos import services


class Command(BaseCommand):
    help = "How many weight photos have been collected, and how many have a weighbridge weight."

    def handle(self, *args, **options):
        for row in services.coverage():
            ready = "enough to start" if row["enough"] else f"{row['target'] - row['weighed']} more needed"
            self.stdout.write(f"{row['label']}: {row['photos']} photos, {row['weighed']} with a weighed figure ({ready}).")
        self.stdout.write("The target is an assumption (WEIGHT_PHOTO_TARGET_PER_SUBJECT in settings); a data scientist should confirm it.")
