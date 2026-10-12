from django.db import migrations

STARTER_TYPES = [
    "Pelletizer",
    "Baler",
    "Shredder",
    "Tractor",
    "Collection vehicle",
    "Weighbridge",
]


def add_starter_types(apps, schema_editor):
    EquipmentType = apps.get_model("network", "EquipmentType")
    for name in STARTER_TYPES:
        EquipmentType.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("network", "0002_mitra_equipment"),
    ]

    operations = [
        # Admin can add, rename or deactivate types later; these just save typing.
        migrations.RunPython(add_starter_types, migrations.RunPython.noop),
    ]
