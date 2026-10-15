from decimal import Decimal

from django.db import migrations

# Only paddy (1.3 tonnes per acre) and mustard (1.2) have figures so far, supplied by Regenerix. The others are
# left empty on purpose: an Admin fills them in once the numbers are agreed.
TYPES = [
    ("Paddy", "Paddy straw", Decimal("1.30")),
    ("Wheat", "Wheat straw", None),
    ("Maize", "Maize stover", None),
    ("Cotton", "Cotton stalk", None),
    ("Mustard", "Mustard stalk", Decimal("1.20")),
    ("Sugarcane", "Sugarcane trash", None),
    ("Soybean", "Soybean straw", None),
    ("Millets", "Millet stover", None),
]


def add_types(apps, schema_editor):
    Crop = apps.get_model("reference", "Crop")
    BiomassType = apps.get_model("reference", "BiomassType")
    for crop_name, name, tonnes in TYPES:
        crop = Crop.objects.filter(name=crop_name).first()
        if crop:
            BiomassType.objects.get_or_create(
                name=name, defaults={"crop": crop, "estimated_tonnes_per_acre": tonnes}
            )


class Migration(migrations.Migration):
    dependencies = [("reference", "0004_biomasstype")]

    operations = [migrations.RunPython(add_types, migrations.RunPython.noop)]
