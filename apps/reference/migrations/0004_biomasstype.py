import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]


def base_fields():
    return [
        (
            "id",
            models.UUIDField(
                default=uuid.uuid4, editable=False, primary_key=True, serialize=False
            ),
        ),
        ("status", models.CharField(choices=STATUS_CHOICES, default="active", max_length=10)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        (
            "created_by",
            models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        (
            "updated_by",
            models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("reference", "0003_more_starter_crops"),
    ]

    operations = [
        migrations.CreateModel(
            name="BiomassType",
            fields=base_fields()
            + [
                (
                    "name",
                    models.CharField(
                        help_text="For example Paddy straw", max_length=100, unique=True
                    ),
                ),
                ("description", models.TextField(blank=True)),
                (
                    "estimated_tonnes_per_acre",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Collectable biomass from one acre. Leave empty until it is known: plots of this crop are then left out of the supply estimate.",
                        max_digits=6,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "moisture_min_percent",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=5,
                        null=True,
                        validators=[django.core.validators.MaxValueValidator(100)],
                    ),
                ),
                (
                    "moisture_max_percent",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=5,
                        null=True,
                        validators=[django.core.validators.MaxValueValidator(100)],
                    ),
                ),
                (
                    "crop",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="biomass_types",
                        to="reference.crop",
                    ),
                ),
            ],
            options={"ordering": ["name"]},
        ),
    ]
