from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("network", "0003_seed_equipment_types"),
        ("reference", "0008_seed_processing_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="grid",
            name="processing_types",
            field=models.ManyToManyField(
                blank=True,
                help_text="What this Grid can make. Pick at least one in the admin.",
                related_name="grids",
                to="reference.processingtype",
            ),
        ),
    ]
