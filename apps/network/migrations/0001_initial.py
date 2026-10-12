import uuid

import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]
OPERATING_STATUS_CHOICES = [
    ("planned", "Planned"),
    ("commissioning", "Commissioning"),
    ("operating", "Operating"),
    ("paused", "Paused"),
    ("closed", "Closed"),
]


def base_fields():
    """The fields every BaseModel adds, in declaration order."""
    return [
        (
            "id",
            models.UUIDField(
                default=uuid.uuid4, editable=False, primary_key=True, serialize=False
            ),
        ),
        (
            "status",
            models.CharField(choices=STATUS_CHOICES, default="active", max_length=10),
        ),
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
        ("territory", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Hub",
            fields=base_fields()
            + [
                (
                    "code",
                    models.CharField(
                        help_text="For example HUB-HR-AMB-001", max_length=32, unique=True
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                (
                    "location",
                    django.contrib.gis.db.models.fields.PointField(srid=4326),
                ),
                (
                    "storage_capacity_t",
                    models.DecimalField(decimal_places=2, help_text="Tonnes", max_digits=12),
                ),
                (
                    "operating_status",
                    models.CharField(
                        choices=OPERATING_STATUS_CHOICES, default="planned", max_length=14
                    ),
                ),
                ("commissioning_date", models.DateField(blank=True, null=True)),
                (
                    "operator",
                    models.ForeignKey(
                        blank=True,
                        limit_choices_to={"role": "admin"},
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="operated_hubs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "region",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="hubs",
                        to="territory.region",
                    ),
                ),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="Grid",
            fields=base_fields()
            + [
                (
                    "code",
                    models.CharField(
                        help_text="For example GRID-HR-AMB-001", max_length=32, unique=True
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                (
                    "location",
                    django.contrib.gis.db.models.fields.PointField(srid=4326),
                ),
                (
                    "processing_capacity_tpd",
                    models.DecimalField(
                        decimal_places=2, help_text="Tonnes per day", max_digits=10
                    ),
                ),
                (
                    "storage_capacity_t",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Tonnes",
                        max_digits=12,
                        null=True,
                    ),
                ),
                (
                    "operating_status",
                    models.CharField(
                        choices=OPERATING_STATUS_CHOICES, default="planned", max_length=14
                    ),
                ),
                ("commissioning_date", models.DateField(blank=True, null=True)),
                (
                    "hub",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="grids",
                        to="network.hub",
                    ),
                ),
                (
                    "region",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="grids",
                        to="territory.region",
                    ),
                ),
            ],
            options={"ordering": ["code"]},
        ),
    ]
