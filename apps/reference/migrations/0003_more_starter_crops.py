from django.db import migrations

MORE_CROPS = ["Soybean", "Millets"]


def add_crops(apps, schema_editor):
    Crop = apps.get_model("reference", "Crop")
    for name in MORE_CROPS:
        Crop.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("reference", "0002_seed_crops_and_seasons"),
    ]

    operations = [
        migrations.RunPython(add_crops, migrations.RunPython.noop),
    ]
