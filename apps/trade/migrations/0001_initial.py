import uuid

from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
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


FK = django.db.models.deletion.PROTECT


def fk(to, related_name, **kwargs):
    return models.ForeignKey(on_delete=FK, related_name=related_name, to=to, **kwargs)


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
            name="FeeSchedule",
            fields=base_fields()
            + [
                (
                    "fee_model",
                    models.CharField(
                        choices=[
                            ("flat", "Flat rupees per tonne"),
                            ("percentage", "Percentage of the sale value"),
                            ("lease", "Lease (fixed per month, no fee on each sale)"),
                        ],
                        max_length=12,
                    ),
                ),
                (
                    "flat_rupees_per_tonne",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=10, null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "percentage",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=5, null=True,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                    ),
                ),
                (
                    "lease_rupees_per_month",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=12, null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("effective_from", models.DateField()),
                (
                    "effective_to",
                    models.DateField(
                        blank=True, null=True,
                        help_text="Leave empty for the schedule in force now. Set it before adding the next one.",
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("region", fk("territory.region", "fee_schedules")),
            ],
            options={
                "ordering": ["region__code", "-effective_from"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("effective_to__isnull", True), ("status", "active")),
                        fields=("region",),
                        name="one_open_fee_schedule_per_region",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("effective_to__isnull", True),
                            ("effective_to__gte", models.F("effective_from")),
                            _connector="OR",
                        ),
                        name="fee_schedule_dates_in_order",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Dispatch",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                (
                    "quantity_tonnes",
                    models.DecimalField(
                        decimal_places=3, help_text="Weight when it left the Grid", max_digits=10,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                    ),
                ),
                (
                    "current_quantity_tonnes",
                    models.DecimalField(decimal_places=3, editable=False, max_digits=10),
                ),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("at_grid", "At the Grid"),
                            ("at_hub", "At the Hub"),
                            ("in_transit", "On the way to the buyer"),
                            ("delivered", "Delivered"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="at_grid", editable=False, max_length=12,
                    ),
                ),
                ("vehicle_ref", models.CharField(blank=True, help_text="Vehicle number or driver", max_length=50)),
                ("note", models.TextField(blank=True)),
                ("created_by_mitra", fk("network.mitra", "dispatches", blank=True, null=True)),
                ("factory", fk("demand.factory", "dispatches")),
                ("grid", fk("network.grid", "dispatches")),
                ("hub", fk("network.hub", "dispatches", blank=True, null=True)),
                ("product", fk("reference.product", "dispatches")),
                ("requirement", fk("demand.requirement", "dispatches", blank=True, null=True)),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name_plural": "dispatches",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("quantity_tonnes__gt", 0)), name="dispatch_quantity_positive"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="DispatchEvent",
            fields=base_fields()
            + [
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("received_at_hub", "Received at the Hub"),
                            ("in_transit", "Left for the buyer"),
                            ("delivered", "Delivered to the buyer"),
                            ("cancelled", "Cancelled"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "quantity_tonnes",
                    models.DecimalField(
                        blank=True, decimal_places=3,
                        help_text="Weighed at this step. Not needed when cancelling.",
                        max_digits=10, null=True,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                    ),
                ),
                ("occurred_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("vehicle_ref", models.CharField(blank=True, max_length=50)),
                ("note", models.TextField(blank=True)),
                ("ledger_seq", models.PositiveBigIntegerField(blank=True, editable=False, null=True)),
                ("dispatch", fk("trade.dispatch", "events")),
            ],
            options={"ordering": ["occurred_at", "created_at"]},
        ),
        migrations.CreateModel(
            name="Sale",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                ("quantity_tonnes", models.DecimalField(decimal_places=3, editable=False, max_digits=10)),
                (
                    "sale_value",
                    models.DecimalField(
                        decimal_places=2, max_digits=14,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "farmer_payment",
                    models.DecimalField(
                        decimal_places=2, help_text="Paid to farmers for the biomass in this lot", max_digits=14,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "farmer_payment_estimated",
                    models.BooleanField(
                        default=False,
                        help_text="True when the figure came from the Grid's average pickup price, not a typed amount",
                    ),
                ),
                ("platform_fee", models.DecimalField(decimal_places=2, editable=False, max_digits=14)),
                ("mitra_margin", models.DecimalField(decimal_places=2, editable=False, max_digits=14)),
                (
                    "fee_model",
                    models.CharField(
                        choices=[
                            ("flat", "Flat rupees per tonne"),
                            ("percentage", "Percentage of the sale value"),
                            ("lease", "Lease (fixed per month, no fee on each sale)"),
                        ],
                        editable=False, max_length=12,
                    ),
                ),
                (
                    "fee_parameters",
                    models.TextField(editable=False, help_text="The fee figures used, as they were on the day"),
                ),
                (
                    "buyer_payment",
                    models.CharField(
                        choices=[("pending", "Waiting for the buyer"), ("received", "Received by Regenerix")],
                        default="pending", max_length=10,
                    ),
                ),
                ("buyer_paid_on", models.DateField(blank=True, null=True)),
                ("payment_reference", models.CharField(blank=True, max_length=100)),
                ("mitra_settled_on", models.DateField(blank=True, null=True)),
                (
                    "dispatch",
                    models.OneToOneField(
                        on_delete=FK, related_name="sale", to="trade.dispatch"
                    ),
                ),
                ("region", fk("territory.region", "sales")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="LeaseCharge",
            fields=base_fields()
            + [
                ("period_start", models.DateField(help_text="First day of the month being charged")),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2, max_digits=12,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("paid_on", models.DateField(blank=True, null=True)),
                ("grid", fk("network.grid", "lease_charges")),
            ],
            options={
                "ordering": ["-period_start"],
                "constraints": [
                    models.UniqueConstraint(fields=("grid", "period_start"), name="one_lease_charge_per_grid_month")
                ],
            },
        ),
    ]
