import uuid

import django.contrib.gis.db.models.fields
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
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
        ("network", "0002_mitra_equipment"),
        ("reference", "0001_initial"),
        ("territory", "0003_geocell_grid"),
    ]

    operations = [
        migrations.CreateModel(
            name="Farmer",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                ("name", models.CharField(max_length=200)),
                (
                    "mobile",
                    models.CharField(
                        blank=True,
                        max_length=16,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="Enter a mobile number with 10 to 15 digits, optionally starting with +.",
                                regex="^\\+?\\d{10,15}$",
                            )
                        ],
                    ),
                ),
                (
                    "preferred_language",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("hi", "Hindi"),
                            ("en", "English"),
                            ("pa", "Punjabi"),
                            ("other", "Other"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "anonymised_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "registered_by_mitra",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registered_farmers",
                        to="network.mitra",
                    ),
                ),
                (
                    "village",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="farmers",
                        to="geography.village",
                    ),
                ),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="ConsentRecord",
            fields=base_fields()
            + [
                (
                    "purpose",
                    models.CharField(
                        default="Registration and collection of crop residue", max_length=200
                    ),
                ),
                (
                    "notice_version",
                    models.CharField(
                        help_text="Which wording of the notice the farmer was given",
                        max_length=20,
                    ),
                ),
                (
                    "language",
                    models.CharField(
                        blank=True,
                        help_text="Language the notice was explained in",
                        max_length=10,
                    ),
                ),
                ("given_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("withdrawn_at", models.DateTimeField(blank=True, null=True)),
                (
                    "captured_by_mitra",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="network.mitra",
                    ),
                ),
                (
                    "farmer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="consents",
                        to="farms.farmer",
                    ),
                ),
            ],
            options={"ordering": ["-given_at"]},
        ),
        migrations.CreateModel(
            name="FarmPlot",
            fields=base_fields()
            + [
                ("location", django.contrib.gis.db.models.fields.PointField(srid=4326)),
                (
                    "boundary",
                    django.contrib.gis.db.models.fields.PolygonField(
                        blank=True, null=True, srid=4326
                    ),
                ),
                (
                    "area_acres",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=10),
                ),
                (
                    "ownership",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("owned", "Owned"),
                            ("leased", "Leased"),
                            ("sharecropped", "Sharecropped"),
                        ],
                        max_length=14,
                    ),
                ),
                (
                    "irrigation",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("canal", "Canal"),
                            ("tubewell", "Tubewell"),
                            ("rainfed", "Rain-fed"),
                            ("other", "Other"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "farmer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="plots",
                        to="farms.farmer",
                    ),
                ),
                (
                    "geocell",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="plots",
                        to="territory.geocell",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="PlotSeason",
            fields=base_fields()
            + [
                (
                    "year",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(2000),
                            django.core.validators.MaxValueValidator(2100),
                        ]
                    ),
                ),
                ("variety", models.CharField(blank=True, max_length=100)),
                ("sowing_date", models.DateField(blank=True, null=True)),
                ("expected_harvest_date", models.DateField(blank=True, null=True)),
                (
                    "crop",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="reference.crop",
                    ),
                ),
                (
                    "plot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="seasons",
                        to="farms.farmplot",
                    ),
                ),
                (
                    "season",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="reference.season",
                    ),
                ),
            ],
            options={
                "ordering": ["-year", "-created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("plot", "season", "year", "crop"),
                        name="uniq_plot_season_year_crop",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("expected_harvest_date__isnull", True),
                            ("sowing_date__isnull", True),
                            ("expected_harvest_date__gte", models.F("sowing_date")),
                            _connector="OR",
                        ),
                        name="harvest_not_before_sowing",
                    ),
                ],
            },
        ),
    ]
