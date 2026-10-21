import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0002_contracts"),
        ("trade", "0002_dispatch_purchase_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="source_dispatch",
            field=models.ForeignKey(
                blank=True,
                help_text="The delivered load this batch came from, so it can be traced back to its farmers",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="yard_batches",
                to="trade.dispatch",
            ),
        ),
    ]
