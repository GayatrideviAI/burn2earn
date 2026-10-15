import datetime
import uuid

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
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("farms", "0001_initial"),
        ("network", "0004_grid_processing_types"),
        ("reference", "0008_seed_processing_types"),
    ]

    operations = [
        migrations.CreateModel(
            name="CollectionRecord",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                (
                    "quantity_tonnes",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                    ),
                ),
                (
                    "price_paid",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Total rupees paid to the farmer for this pickup",
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("collected_on", models.DateField(default=datetime.date.today)),
                ("notes", models.TextField(blank=True)),
                (
                    "biomass_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="collections",
                        to="reference.biomasstype",
                    ),
                ),
                (
                    "farmer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="collections",
                        to="farms.farmer",
                    ),
                ),
                (
                    "grid",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="collections",
                        to="network.grid",
                    ),
                ),
                (
                    "mitra",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="collections",
                        to="network.mitra",
                    ),
                ),
                (
                    "plot",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="collections",
                        to="farms.farmplot",
                    ),
                ),
            ],
            options={
                "ordering": ["-collected_on", "-created_at"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("quantity_tonnes__gt", 0)),
                        name="collection_quantity_positive",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ProcessedOutput",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                (
                    "quantity_tonnes",
                    models.DecimalField(
                        decimal_places=3,
                        help_text="A rough figure is fine",
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                    ),
                ),
                (
                    "biomass_used_tonnes",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        help_text="Raw residue used up making this. Leave empty if not known; the stock tally then does not subtract it.",
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("produced_on", models.DateField(default=datetime.date.today)),
                ("notes", models.TextField(blank=True)),
                (
                    "grid",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="outputs",
                        to="network.grid",
                    ),
                ),
                (
                    "mitra",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="outputs",
                        to="network.mitra",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="outputs",
                        to="reference.product",
                    ),
                ),
            ],
            options={
                "ordering": ["-produced_on", "-created_at"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("quantity_tonnes__gt", 0)),
                        name="output_quantity_positive",
                    )
                ],
            },
        ),
    ]
