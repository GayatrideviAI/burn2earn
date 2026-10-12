import uuid

import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.conf import settings
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
        ("geography", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Region",
            fields=base_fields()
            + [
                (
                    "code",
                    models.CharField(
                        help_text="For example REG-HR-AMB-001", max_length=32, unique=True
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                (
                    "district",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="regions",
                        to="geography.district",
                    ),
                ),
                (
                    "state",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="regions",
                        to="geography.state",
                    ),
                ),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="GeoCell",
            fields=base_fields()
            + [
                ("code", models.CharField(max_length=40, unique=True)),
                (
                    "origin",
                    models.CharField(
                        choices=[("panchayat", "Panchayat"), ("mitra_drawn", "Drawn by Mitra")],
                        default="panchayat",
                        max_length=12,
                    ),
                ),
                (
                    "boundary",
                    django.contrib.gis.db.models.fields.MultiPolygonField(srid=4326),
                ),
                (
                    "center_point",
                    django.contrib.gis.db.models.fields.PointField(
                        blank=True, editable=False, null=True, srid=4326
                    ),
                ),
                (
                    "area_acres",
                    models.DecimalField(
                        blank=True, decimal_places=2, editable=False, max_digits=12, null=True
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "panchayat",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="geocells",
                        to="geography.panchayat",
                    ),
                ),
                (
                    "region",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="geocells",
                        to="territory.region",
                    ),
                ),
            ],
            options={
                "verbose_name": "GeoCell",
                "verbose_name_plural": "GeoCells",
                "ordering": ["code"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("panchayat__isnull", False), ("status", "active")),
                        fields=("panchayat",),
                        name="uniq_active_geocell_per_panchayat",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("origin", "mitra_drawn"), ("panchayat__isnull", False), _connector="OR"
                        ),
                        name="geocell_panchayat_origin_needs_panchayat",
                    ),
                ],
            },
        ),
    ]
