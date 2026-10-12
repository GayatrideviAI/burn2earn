import uuid

import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.conf import settings
from django.contrib.postgres.operations import CreateExtension
from django.db import migrations, models

STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]


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
    ]

    operations = [
        CreateExtension("postgis"),
        migrations.CreateModel(
            name="State",
            fields=base_fields()
            + [
                ("lgd_code", models.CharField(max_length=12, unique=True)),
                ("name", models.CharField(max_length=200)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="District",
            fields=base_fields()
            + [
                ("lgd_code", models.CharField(max_length=12, unique=True)),
                ("name", models.CharField(max_length=200)),
                (
                    "state",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="districts",
                        to="geography.state",
                    ),
                ),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Block",
            fields=base_fields()
            + [
                ("lgd_code", models.CharField(max_length=12, unique=True)),
                ("name", models.CharField(max_length=200)),
                (
                    "district",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="blocks",
                        to="geography.district",
                    ),
                ),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Panchayat",
            fields=base_fields()
            + [
                ("lgd_code", models.CharField(max_length=12, unique=True)),
                ("name", models.CharField(max_length=200)),
                (
                    "boundary",
                    django.contrib.gis.db.models.fields.MultiPolygonField(
                        blank=True, null=True, srid=4326
                    ),
                ),
                (
                    "block",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="panchayats",
                        to="geography.block",
                    ),
                ),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Village",
            fields=base_fields()
            + [
                ("lgd_code", models.CharField(max_length=12, unique=True)),
                ("name", models.CharField(max_length=200)),
                (
                    "panchayat",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="villages",
                        to="geography.panchayat",
                    ),
                ),
            ],
            options={"ordering": ["name"]},
        ),
    ]
