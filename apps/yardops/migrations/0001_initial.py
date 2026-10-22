import uuid
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]
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
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("customers", "0004_pile_dimensions"),
    ]

    operations = [
        migrations.CreateModel(
            name="YardOperator",
            fields=base_fields()
            + [
                ("name", models.CharField(max_length=200)),
                (
                    "user",
                    models.OneToOneField(
                        limit_choices_to={"role": "yard"},
                        on_delete=PROTECT,
                        related_name="yard_operator",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("yards", models.ManyToManyField(blank=True, related_name="operators", to="customers.stockyard")),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="HeatReading",
            fields=base_fields()
            + [
                ("taken_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "temperature_c",
                    models.DecimalField(
                        decimal_places=1,
                        max_digits=5,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("-20")),
                            django.core.validators.MaxValueValidator(Decimal("200")),
                        ],
                        verbose_name="Temperature (°C)",
                    ),
                ),
                (
                    "depth_cm",
                    models.PositiveSmallIntegerField(
                        blank=True, null=True, validators=[django.core.validators.MaxValueValidator(500)]
                    ),
                ),
                ("spot", models.CharField(blank=True, help_text="For example north face, 1 m deep", max_length=80)),
                (
                    "method",
                    models.CharField(
                        choices=[("manual_probe", "Manual probe"), ("fixed_sensor", "Fixed sensor")],
                        default="manual_probe",
                        max_length=12,
                    ),
                ),
                ("taken_by", models.CharField(blank=True, max_length=100)),
                ("ledger_seq", models.PositiveBigIntegerField(blank=True, editable=False, null=True)),
                ("pile", fk("customers.pile", "heat_readings")),
            ],
            options={"ordering": ["-taken_at"]},
        ),
        migrations.CreateModel(
            name="PileInspection",
            fields=base_fields()
            + [
                ("inspected_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("looks_wet", models.BooleanField(default=False)),
                ("mould", models.BooleanField(default=False)),
                ("steam_or_smell", models.BooleanField(default=False, help_text="Steam, or a burnt or musty smell")),
                ("cover_in_place", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
                ("inspected_by", models.CharField(blank=True, max_length=100)),
                ("ledger_seq", models.PositiveBigIntegerField(blank=True, editable=False, null=True)),
                ("pile", fk("customers.pile", "inspections")),
            ],
            options={"ordering": ["-inspected_at"]},
        ),
        migrations.CreateModel(
            name="RiskAlert",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                (
                    "level",
                    models.CharField(
                        choices=[("watch", "Watch closely"), ("act", "Check twice a day"), ("emergency", "Fire likely")],
                        max_length=10,
                    ),
                ),
                ("reasons", models.TextField(help_text="Why the alert was raised, one reason per line")),
                ("raised_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("acknowledged_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("note", models.TextField(blank=True, help_text="What was done")),
                ("ledger_seq", models.PositiveBigIntegerField(blank=True, editable=False, null=True)),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        blank=True, editable=False, null=True, on_delete=PROTECT, related_name="+", to=settings.AUTH_USER_MODEL
                    ),
                ),
                ("pile", fk("customers.pile", "risk_alerts")),
            ],
            options={"ordering": ["-raised_at"]},
        ),
    ]
