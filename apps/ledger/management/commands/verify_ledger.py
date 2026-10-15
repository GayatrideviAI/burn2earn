from django.core.management.base import BaseCommand, CommandError

from apps.ledger.chain import verify


class Command(BaseCommand):
    help = "Check that no ledger entry has been changed, removed or reordered."

    def handle(self, *args, **options):
        result = verify()
        if not result.ok:
            raise CommandError(f"LEDGER PROBLEM after {result.checked} good entries: {result.problem}")
        self.stdout.write(self.style.SUCCESS(f"Ledger is intact ({result.checked} entries)."))
