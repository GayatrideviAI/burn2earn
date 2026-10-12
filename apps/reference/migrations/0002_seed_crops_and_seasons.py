from django.db import migrations

STARTER_CROPS = ["Paddy", "Wheat", "Maize", "Cotton", "Mustard", "Sugarcane"]
# Indicative sowing-to-harvest windows. Admin can edit them, or add more seasons.
STARTER_SEASONS = [("Kharif", 6, 10), ("Rabi", 11, 4)]


def add_starters(apps, schema_editor):
    Crop = apps.get_model("reference", "Crop")
    Season = apps.get_model("reference", "Season")
    for name in STARTER_CROPS:
        Crop.objects.get_or_create(name=name)
    for name, start, end in STARTER_SEASONS:
        Season.objects.get_or_create(name=name, defaults={"start_month": start, "end_month": end})


class Migration(migrations.Migration):
    dependencies = [
        ("reference", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_starters, migrations.RunPython.noop),
    ]
