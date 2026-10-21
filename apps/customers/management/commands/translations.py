from django.core.management.base import BaseCommand, CommandError

from apps.customers import i18n_tools as t


class Command(BaseCommand):
    help = "Manage the Hindi and Punjabi translations: extract, export, import, compile."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["extract", "export", "import", "compile"])
        parser.add_argument("--file", help="Spreadsheet path (default: locale/translations.xlsx)")

    def handle(self, action, file=None, **options):
        if action == "extract":
            found = t.extract()
            self.stdout.write(f"{len(found)} phrases found; .po files updated.")
        elif action == "export":
            n = t.export_sheet(file or t.SHEET)
            self.stdout.write(f"{n} phrases written to {file or t.SHEET}.")
        elif action == "import":
            problems, unknown = t.import_sheet(file or t.SHEET)
            for p in problems:
                self.stderr.write(p)
            if unknown:
                self.stdout.write(f"{len(unknown)} rows in the sheet are no longer used and were ignored.")
            t.compile_all()
            self.stdout.write("Translations loaded and compiled.")
            if problems:
                raise CommandError("Some translations were skipped; see above.")
        else:
            t.compile_all()
            self.stdout.write("Compiled.")
