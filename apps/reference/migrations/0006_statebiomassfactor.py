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
        ("geography", "0001_initial"),
        ("reference", "0005_seed_biomass_types"),
    ]

    operations = [
        migrations.CreateModel(
            name="StateBiomassFactor",
            fields=base_fields()
            + [
                (
                    "estimated_tonnes_per_acre",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Collectable biomass per acre in this state. Empty = use the Biomass Type's own figure.",
                        max_digits=6,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "pilferage_percent",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text="Share of the estimate expected to be lost before it reaches the Mitra (theft, diversion, burning).",
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                    ),
                ),
                (
                    "biomass_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="state_factors",
                        to="reference.biomasstype",
                    ),
                ),
                (
                    "state",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="biomass_factors",
                        to="geography.state",
                    ),
                ),
            ],
            options={
                "ordering": ["state__name", "biomass_type__name"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("biomass_type", "state"), name="uniq_biomass_type_state"
                    )
                ],
            },
        ),
    ]
