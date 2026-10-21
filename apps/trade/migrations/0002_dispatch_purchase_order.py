import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0002_contracts"),
        ("trade", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="dispatch",
            name="purchase_order",
            field=models.ForeignKey(
                blank=True,
                help_text="The customer's purchase order this lot is delivered against, if any",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="dispatches",
                to="customers.purchaseorder",
            ),
        ),
    ]
