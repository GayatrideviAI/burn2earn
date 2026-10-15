from django.db import migrations

STARTERS = [
    ("Baling", "Compressing loose residue into bales"),
    ("Pelletising", "Grinding and pressing residue into fuel pellets"),
    ("Shredding", "Cutting residue into small pieces"),
    ("Briquetting", "Pressing residue into solid briquettes"),
]


def add_types(apps, schema_editor):
    ProcessingType = apps.get_model("reference", "ProcessingType")
    for name, description in STARTERS:
        ProcessingType.objects.get_or_create(name=name, defaults={"description": description})


class Migration(migrations.Migration):
    dependencies = [("reference", "0007_processing_product")]

    operations = [migrations.RunPython(add_types, migrations.RunPython.noop)]
