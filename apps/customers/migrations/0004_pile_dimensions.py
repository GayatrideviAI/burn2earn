from decimal import Decimal

import django.core.validators
from django.db import migrations, models


def size(**extra):
    return models.DecimalField(
        decimal_places=1, null=True, blank=True, validators=[django.core.validators.MinValueValidator(Decimal("0.1"))], **extra
    )


class Migration(migrations.Migration):
    dependencies = [("customers", "0003_batch_source_dispatch")]

    operations = [
        migrations.AddField(model_name="pile", name="length_m", field=size(max_digits=5)),
        migrations.AddField(model_name="pile", name="width_m", field=size(max_digits=5)),
        migrations.AddField(
            model_name="pile", name="height_m", field=size(max_digits=4, help_text="Stack height; tall stacks hold heat")
        ),
    ]
