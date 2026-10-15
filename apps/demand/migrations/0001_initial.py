import uuid

import django.contrib.gis.db.models.fields
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
        ("reference", "0008_seed_processing_types"),
    ]

    operations = [
        migrations.CreateModel(
            name="Buyer",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                ("company_name", models.CharField(max_length=200)),
                ("contact_name", models.CharField(max_length=200)),
                (
                    "contact_mobile",
                    models.CharField(
                        max_length=16,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="Enter a mobile number with 10 to 15 digits, optionally starting with +.",
                                regex="^\\+?\\d{10,15}$",
                            )
                        ],
                    ),
                ),
                ("contact_email", models.EmailField(blank=True, max_length=254)),
                (
                    "gst_number",
                    models.CharField(
                        blank=True,
                        max_length=15,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="Enter a 15-character GST number, for example 06ABCDE1234F1Z5.",
                                regex="^\\d{2}[A-Z]{5}\\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$",
                            )
                        ],
                    ),
                ),
                (
                    "commercial_status",
                    models.CharField(
                        choices=[
                            ("prospect", "Prospect"),
                            ("active", "Active customer"),
                            ("on_hold", "On hold"),
                            ("closed", "Closed"),
                        ],
                        default="prospect",
                        max_length=10,
                    ),
                ),
                (
                    "payment_terms",
                    models.TextField(help_text="For example: payment within 15 days of delivery"),
                ),
                (
                    "user",
                    models.OneToOneField(
                        blank=True,
                        limit_choices_to={"role": "buyer"},
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="buyer",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["company_name"]},
        ),
        migrations.CreateModel(
            name="Factory",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("location", django.contrib.gis.db.models.fields.PointField(srid=4326)),
                ("delivery_address", models.TextField()),
                (
                    "minimum_gcv",
                    models.DecimalField(
                        blank=True,
                        decimal_places=0,
                        max_digits=7,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Minimum GCV (kcal/kg)",
                    ),
                ),
                (
                    "maximum_moisture_percent",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=5,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                    ),
                ),
                (
                    "operating_status",
                    models.CharField(
                        choices=[
                            ("planned", "Planned"),
                            ("commissioning", "Commissioning"),
                            ("operating", "Operating"),
                            ("paused", "Paused"),
                            ("closed", "Closed"),
                        ],
                        default="planned",
                        max_length=14,
                    ),
                ),
                (
                    "buyer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="factories",
                        to="demand.buyer",
                    ),
                ),
                (
                    "preferred_biomass_types",
                    models.ManyToManyField(
                        blank=True,
                        related_name="preferring_factories",
                        to="reference.biomasstype",
                    ),
                ),
            ],
            options={"ordering": ["code"], "verbose_name_plural": "factories"},
        ),
    ]
