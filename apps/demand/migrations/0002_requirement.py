import uuid

import django.contrib.gis.db.models.fields
from decimal import Decimal

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
        ("demand", "0001_initial"),
        ("reference", "0008_seed_processing_types"),
    ]

    operations = [
        migrations.CreateModel(
            name="Requirement",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                (
                    "volume_tonnes",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                ("needed_from", models.DateField(help_text="Earliest delivery date")),
                ("needed_by", models.DateField(help_text="Latest delivery date")),
                (
                    "target_gcv",
                    models.DecimalField(
                        blank=True,
                        decimal_places=0,
                        help_text="Rough figure, entered by a person. Not checked against anything.",
                        max_digits=7,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Target GCV (kcal/kg)",
                    ),
                ),
                (
                    "quality_notes",
                    models.TextField(
                        blank=True, help_text="Moisture, size, anything else the buyer said"
                    ),
                ),
                (
                    "fulfilment",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("partly_met", "Partly met"),
                            ("fulfilled", "Fulfilled"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="open",
                        max_length=12,
                    ),
                ),
                (
                    "volume_met_tonnes",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text="Updated by hand as deliveries are agreed",
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "factory",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="requirements",
                        to="demand.factory",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="requirements",
                        to="reference.product",
                    ),
                ),
            ],
            options={
                "ordering": ["needed_by", "code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("volume_tonnes__gt", 0)),
                        name="requirement_volume_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("needed_by__gte", models.F("needed_from"))),
                        name="requirement_dates_in_order",
                    ),
                ],
            },
        ),
    ]
