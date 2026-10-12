import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("network", "0001_initial"),
        ("territory", "0002_geocell_no_overlap_trigger"),
    ]

    operations = [
        migrations.AddField(
            model_name="geocell",
            name="grid",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="geocells",
                to="network.grid",
            ),
        ),
    ]
