import uuid
from decimal import Decimal

import django.contrib.gis.db.models.fields
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]
FORMS = [("bales", "Bales"), ("loose", "Loose chopped straw"), ("pellets", "Pellets"), ("briquettes", "Briquettes")]
PERCENT = [django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)]
MIN_T = [django.core.validators.MinValueValidator(Decimal("0.001"))]
PROTECT = django.db.models.deletion.PROTECT


def base_fields():
    return [
        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
        ("status", models.CharField(choices=STATUS_CHOICES, default="active", max_length=10)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)),
        (
            "created_by",
            models.ForeignKey(
                blank=True, editable=False, null=True, on_delete=PROTECT, related_name="+", to=settings.AUTH_USER_MODEL
            ),
        ),
        (
            "updated_by",
            models.ForeignKey(
                blank=True, editable=False, null=True, on_delete=PROTECT, related_name="+", to=settings.AUTH_USER_MODEL
            ),
        ),
    ]


def fk(to, related_name, **kwargs):
    return models.ForeignKey(on_delete=PROTECT, related_name=related_name, to=to, **kwargs)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("demand", "0002_requirement"),
        ("network", "0004_grid_processing_types"),
        ("reference", "0008_seed_processing_types"),
        ("territory", "0003_geocell_grid"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerMember",
            fields=base_fields()
            + [
                (
                    "job_role",
                    models.CharField(
                        choices=[
                            ("procurement", "Procurement / fuel manager"),
                            ("operations", "Plant operations"),
                            ("finance", "Finance"),
                            ("esg", "ESG / sustainability"),
                        ],
                        max_length=12,
                    ),
                ),
                ("buyer", fk("demand.buyer", "members")),
                (
                    "user",
                    models.OneToOneField(
                        limit_choices_to={"role": "buyer"},
                        on_delete=PROTECT,
                        related_name="customer_member",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["buyer__company_name", "user__username"]},
        ),
        migrations.CreateModel(
            name="PlantProfile",
            fields=base_fields()
            + [
                (
                    "daily_consumption_tonnes",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Average tonnes burned per day",
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "factory",
                    models.OneToOneField(on_delete=PROTECT, related_name="profile", to="demand.factory"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Stockyard",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("location", django.contrib.gis.db.models.fields.PointField(srid=4326)),
                (
                    "owner_type",
                    models.CharField(
                        choices=[
                            ("regenerix", "Regenerix"),
                            ("vle", "VLE"),
                            ("third_party", "Third party"),
                            ("customer", "The customer"),
                        ],
                        default="regenerix",
                        max_length=12,
                    ),
                ),
                ("owner_name", models.CharField(blank=True, max_length=200)),
                (
                    "capacity_tonnes",
                    models.DecimalField(
                        blank=True,
                        decimal_places=0,
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "notes",
                    models.TextField(blank=True, help_text="Roofed and open areas, drainage, safety requirements"),
                ),
                ("region", fk("territory.region", "stockyards", blank=True, null=True)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="Pile",
            fields=base_fields()
            + [
                ("label", models.CharField(help_text="For example A-01", max_length=20)),
                ("form", models.CharField(choices=FORMS, max_length=10)),
                (
                    "exposure",
                    models.CharField(
                        choices=[("open", "Open to rain"), ("part", "Part covered"), ("protected", "Protected")],
                        default="open",
                        max_length=10,
                    ),
                ),
                ("cover_type", models.CharField(blank=True, help_text="For example tarp, shed, none", max_length=100)),
                ("yard", fk("customers.stockyard", "piles")),
            ],
            options={
                "ordering": ["yard__code", "label"],
                "constraints": [models.UniqueConstraint(fields=("yard", "label"), name="unique_pile_label_per_yard")],
            },
        ),
        migrations.CreateModel(
            name="Batch",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, help_text="Printed on the QR tag", max_length=20, unique=True)),
                ("form", models.CharField(choices=FORMS, max_length=10)),
                (
                    "source_note",
                    models.TextField(blank=True, help_text="Source villages and the VLE or supplier"),
                ),
                ("received_on", models.DateField(default=django.utils.timezone.localdate)),
                (
                    "intake_tonnes",
                    models.DecimalField(decimal_places=3, max_digits=10, validators=MIN_T),
                ),
                (
                    "intake_moisture_percent",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, validators=PERCENT),
                ),
                ("biomass_type", fk("reference.biomasstype", "+")),
                ("customer", fk("demand.buyer", "batches")),
                ("pile", fk("customers.pile", "batches")),
                ("source_grid", fk("network.grid", "+", blank=True, null=True)),
            ],
            options={"ordering": ["-received_on", "code"], "verbose_name_plural": "batches"},
        ),
        migrations.CreateModel(
            name="InventoryTransaction",
            fields=base_fields()
            + [
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("receipt", "Receipt"),
                            ("transfer", "Moved to another pile"),
                            ("consumption", "Burned at the plant"),
                            ("adjustment", "Adjustment"),
                            ("loss", "Loss"),
                            ("return", "Returned to supplier"),
                            ("disposal", "Disposed of"),
                        ],
                        max_length=12,
                    ),
                ),
                ("tonnes_change", models.DecimalField(decimal_places=3, editable=False, max_digits=10)),
                (
                    "loss_cause",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("rain", "Rain"),
                            ("decomposition", "Decomposition"),
                            ("contamination", "Contamination"),
                            ("handling", "Handling"),
                            ("fire", "Fire"),
                            ("other", "Other"),
                        ],
                        max_length=14,
                    ),
                ),
                ("occurred_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("note", models.TextField(blank=True)),
                ("ledger_seq", models.PositiveBigIntegerField(blank=True, editable=False, null=True)),
                ("batch", fk("customers.batch", "transactions")),
                ("to_pile", fk("customers.pile", "+", blank=True, null=True)),
            ],
            options={"ordering": ["-occurred_at", "-created_at"]},
        ),
        migrations.CreateModel(
            name="QualityObservation",
            fields=base_fields()
            + [
                (
                    "basis",
                    models.CharField(
                        choices=[("measured", "Measured"), ("estimated", "Estimated")], default="measured", max_length=10
                    ),
                ),
                ("observed_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "moisture_percent",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, validators=PERCENT),
                ),
                (
                    "ash_percent",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, validators=PERCENT),
                ),
                (
                    "gcv",
                    models.DecimalField(
                        blank=True,
                        decimal_places=0,
                        max_digits=7,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="GCV (kcal/kg)",
                    ),
                ),
                (
                    "method",
                    models.CharField(blank=True, help_text="For example handheld meter, lab test", max_length=60),
                ),
                ("tested_by", models.CharField(blank=True, max_length=100)),
                ("ledger_seq", models.PositiveBigIntegerField(blank=True, editable=False, null=True)),
                ("batch", fk("customers.batch", "quality")),
            ],
            options={"ordering": ["-observed_at"]},
        ),
        migrations.CreateModel(
            name="StockCount",
            fields=base_fields()
            + [
                (
                    "counted_tonnes",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "method",
                    models.CharField(
                        choices=[
                            ("weighbridge", "Weighbridge"),
                            ("qr_scan", "QR scan and count"),
                            ("survey", "Survey or drone estimate"),
                            ("audit", "Physical audit"),
                        ],
                        max_length=12,
                    ),
                ),
                ("counted_on", models.DateField(default=django.utils.timezone.localdate)),
                ("counted_by", models.CharField(blank=True, max_length=100)),
                ("ledger_seq", models.PositiveBigIntegerField(blank=True, editable=False, null=True)),
                ("batch", fk("customers.batch", "counts")),
            ],
            options={"ordering": ["-counted_on", "-created_at"]},
        ),
        migrations.CreateModel(
            name="Reservation",
            fields=base_fields()
            + [
                ("tonnes", models.DecimalField(decimal_places=3, max_digits=10, validators=MIN_T)),
                ("note", models.CharField(blank=True, max_length=200)),
                ("batch", fk("customers.batch", "reservations")),
                ("factory", fk("demand.factory", "reservations")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
