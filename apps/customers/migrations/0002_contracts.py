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
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("customers", "0001_initial"),
        ("demand", "0002_requirement"),
        ("reference", "0008_seed_processing_types"),
    ]

    operations = [
        migrations.CreateModel(
            name="Contract",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                ("reference", models.CharField(blank=True, help_text="The customer's own contract number", max_length=100)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("penalties", models.TextField(blank=True, help_text="Late delivery and quality penalty terms")),
                (
                    "risk_bearer",
                    models.CharField(
                        choices=[
                            ("regenerix", "Regenerix"),
                            ("yard_operator", "The yard operator"),
                            ("customer", "The customer"),
                            ("shared", "Shared (see notes)"),
                        ],
                        default="regenerix",
                        help_text="Who bears spoilage, rain and fire loss while stock is in a yard",
                        max_length=14,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("allocated_yards", models.ManyToManyField(blank=True, related_name="contracts", to="customers.stockyard")),
                ("customer", fk("demand.buyer", "contracts")),
            ],
            options={
                "ordering": ["-start_date", "code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("end_date__gte", models.F("start_date"))), name="contract_dates_in_order"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ContractLine",
            fields=base_fields()
            + [
                ("contracted_tonnes", models.DecimalField(decimal_places=3, max_digits=12, validators=MIN_T)),
                (
                    "price_per_tonne",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "max_moisture_percent",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, validators=PERCENT),
                ),
                (
                    "min_gcv",
                    models.DecimalField(
                        blank=True,
                        decimal_places=0,
                        max_digits=7,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Minimum GCV (kcal/kg)",
                    ),
                ),
                ("contract", fk("customers.contract", "lines")),
                ("product", fk("reference.product", "+")),
            ],
            options={
                "ordering": ["contract__code", "product__name"],
                "constraints": [
                    models.UniqueConstraint(fields=("contract", "product"), name="one_line_per_product_in_contract")
                ],
            },
        ),
        migrations.CreateModel(
            name="MonthlyPlan",
            fields=base_fields()
            + [
                ("month", models.DateField(help_text="Any date in the month; saved as the first of the month")),
                (
                    "planned_tonnes",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                ("line", fk("customers.contractline", "plan")),
            ],
            options={
                "ordering": ["line", "month"],
                "constraints": [models.UniqueConstraint(fields=("line", "month"), name="one_plan_per_line_month")],
            },
        ),
        migrations.CreateModel(
            name="PurchaseOrder",
            fields=base_fields()
            + [
                ("code", models.CharField(editable=False, max_length=20, unique=True)),
                ("customer_po_number", models.CharField(blank=True, help_text="The customer's own PO number", max_length=60)),
                ("tonnes", models.DecimalField(decimal_places=3, max_digits=12, validators=MIN_T)),
                ("deliver_from", models.DateField()),
                ("deliver_by", models.DateField()),
                (
                    "state",
                    models.CharField(
                        choices=[("open", "Open"), ("fulfilled", "Fulfilled"), ("cancelled", "Cancelled")],
                        default="open",
                        max_length=10,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("factory", fk("demand.factory", "purchase_orders")),
                ("line", fk("customers.contractline", "orders")),
            ],
            options={
                "ordering": ["deliver_by", "code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("deliver_by__gte", models.F("deliver_from"))), name="po_dates_in_order"
                    )
                ],
            },
        ),
    ]
