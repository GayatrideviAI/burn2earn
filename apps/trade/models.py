from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.codes import next_code
from apps.core.models import BaseModel, Status
from apps.demand.models import Factory, Requirement
from apps.network.models import Grid, Hub, Mitra
from apps.reference.models import Product
from apps.territory.models import Region

CENT = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class FeeModel(models.TextChoices):
    FLAT = "flat", "Flat rupees per tonne"
    PERCENTAGE = "percentage", "Percentage of the sale value"
    LEASE = "lease", "Lease (fixed per month, no fee on each sale)"


class FeeSchedule(BaseModel):
    """How Regenerix earns in one Region. A Region has one current schedule at a time."""

    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="fee_schedules")
    fee_model = models.CharField(max_length=12, choices=FeeModel.choices)
    flat_rupees_per_tonne = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    lease_rupees_per_month = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    effective_from = models.DateField()
    effective_to = models.DateField(
        null=True, blank=True, help_text="Leave empty for the schedule in force now. Set it before adding the next one."
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["region__code", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["region"],
                condition=Q(effective_to__isnull=True, status="active"),
                name="one_open_fee_schedule_per_region",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="fee_schedule_dates_in_order",
            ),
        ]

    def __str__(self):
        return f"{self.region.code} {self.get_fee_model_display()} from {self.effective_from}"

    def clean(self):
        super().clean()
        needed = {
            FeeModel.FLAT: "flat_rupees_per_tonne",
            FeeModel.PERCENTAGE: "percentage",
            FeeModel.LEASE: "lease_rupees_per_month",
        }.get(self.fee_model)
        errors = {}
        if needed and getattr(self, needed) is None:
            errors[needed] = "This figure is needed for the chosen fee model."
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            errors["effective_to"] = "The end date cannot be before the start date."
        if errors:
            raise ValidationError(errors)

    @classmethod
    def current_for(cls, region, on=None):
        on = on or date.today()
        return (
            cls.objects.filter(region=region, status=Status.ACTIVE, effective_from__lte=on)
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on))
            .order_by("-effective_from")
            .first()
        )

    def fee_for_sale(self, quantity_tonnes, sale_value):
        """Regenerix's fee on one sale. Under a lease there is no per-sale fee."""
        if self.fee_model == FeeModel.FLAT:
            return money(Decimal(quantity_tonnes) * self.flat_rupees_per_tonne)
        if self.fee_model == FeeModel.PERCENTAGE:
            return money(Decimal(sale_value) * self.percentage / 100)
        return Decimal("0.00")

    def parameters(self):
        """The figures used, kept on every sale so later changes to the schedule cannot rewrite it."""
        return {
            "schedule": str(self.pk),
            "fee_model": self.fee_model,
            "flat_rupees_per_tonne": self.flat_rupees_per_tonne,
            "percentage": self.percentage,
            "lease_rupees_per_month": self.lease_rupees_per_month,
        }


class DispatchStage(models.TextChoices):
    AT_GRID = "at_grid", "At the Grid"
    AT_HUB = "at_hub", "At the Hub"
    IN_TRANSIT = "in_transit", "On the way to the buyer"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"


class Dispatch(BaseModel):
    """A lot of product moving from a Grid, usually via a Hub, to a buyer's factory."""

    code = models.CharField(max_length=20, unique=True, editable=False)
    grid = models.ForeignKey(Grid, on_delete=models.PROTECT, related_name="dispatches")
    hub = models.ForeignKey(Hub, on_delete=models.PROTECT, null=True, blank=True, related_name="dispatches")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="dispatches")
    factory = models.ForeignKey(Factory, on_delete=models.PROTECT, related_name="dispatches")
    requirement = models.ForeignKey(
        Requirement, on_delete=models.PROTECT, null=True, blank=True, related_name="dispatches"
    )
    created_by_mitra = models.ForeignKey(
        Mitra, on_delete=models.PROTECT, null=True, blank=True, related_name="dispatches"
    )
    purchase_order = models.ForeignKey(
        "customers.PurchaseOrder", on_delete=models.PROTECT, null=True, blank=True, related_name="dispatches",
        help_text="The customer's purchase order this lot is delivered against, if any",
    )
    quantity_tonnes = models.DecimalField(
        max_digits=10, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))],
        help_text="Weight when it left the Grid",
    )
    # The latest weighed figure. It can only go down along the way (loss), never up.
    current_quantity_tonnes = models.DecimalField(max_digits=10, decimal_places=3, editable=False)
    stage = models.CharField(
        max_length=12, choices=DispatchStage.choices, default=DispatchStage.AT_GRID, editable=False
    )
    vehicle_ref = models.CharField(max_length=50, blank=True, help_text="Vehicle number or driver")
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "dispatches"
        constraints = [
            models.CheckConstraint(condition=Q(quantity_tonnes__gt=0), name="dispatch_quantity_positive"),
        ]

    def __str__(self):
        return f"{self.code} {self.quantity_tonnes} t {self.product}"

    @property
    def loss_tonnes(self):
        return self.quantity_tonnes - self.current_quantity_tonnes

    @property
    def is_closed(self):
        return self.stage in (DispatchStage.DELIVERED, DispatchStage.CANCELLED)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("dispatch", "DSP")
        if self.current_quantity_tonnes is None:
            self.current_quantity_tonnes = self.quantity_tonnes
        super().save(*args, **kwargs)


class EventType(models.TextChoices):
    RECEIVED_AT_HUB = "received_at_hub", "Received at the Hub"
    IN_TRANSIT = "in_transit", "Left for the buyer"
    DELIVERED = "delivered", "Delivered to the buyer"
    CANCELLED = "cancelled", "Cancelled"


class DispatchEvent(BaseModel):
    """One step in a dispatch's journey, with the weight taken at that point. Never edited."""

    dispatch = models.ForeignKey(Dispatch, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    quantity_tonnes = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(Decimal("0.001"))],
        help_text="Weighed at this step. Not needed when cancelling.",
    )
    occurred_at = models.DateTimeField(default=timezone.now)
    vehicle_ref = models.CharField(max_length=50, blank=True)
    note = models.TextField(blank=True)
    ledger_seq = models.PositiveBigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["occurred_at", "created_at"]

    def __str__(self):
        return f"{self.dispatch.code} {self.get_event_type_display()}"


class BuyerPayment(models.TextChoices):
    PENDING = "pending", "Waiting for the buyer"
    RECEIVED = "received", "Received by Regenerix"


class Sale(BaseModel):
    """The sale of a delivered lot to a buyer, paid through the platform.

    sale value = farmer payment + platform fee + Mitra margin.
    """

    code = models.CharField(max_length=20, unique=True, editable=False)
    dispatch = models.OneToOneField(Dispatch, on_delete=models.PROTECT, related_name="sale")
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="sales")
    quantity_tonnes = models.DecimalField(max_digits=10, decimal_places=3, editable=False)
    sale_value = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    farmer_payment = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(0)],
        help_text="Paid to farmers for the biomass in this lot",
    )
    farmer_payment_estimated = models.BooleanField(
        default=False, help_text="True when the figure came from the Grid's average pickup price, not a typed amount"
    )
    platform_fee = models.DecimalField(max_digits=14, decimal_places=2, editable=False)
    mitra_margin = models.DecimalField(max_digits=14, decimal_places=2, editable=False)
    fee_model = models.CharField(max_length=12, choices=FeeModel.choices, editable=False)
    fee_parameters = models.TextField(editable=False, help_text="The fee figures used, as they were on the day")
    buyer_payment = models.CharField(max_length=10, choices=BuyerPayment.choices, default=BuyerPayment.PENDING)
    buyer_paid_on = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    mitra_settled_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} ₹{self.sale_value}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("sale", "TXN")
        super().save(*args, **kwargs)


class LeaseCharge(BaseModel):
    """A month's lease charged to a Grid in a Region that uses the lease fee model."""

    grid = models.ForeignKey(Grid, on_delete=models.PROTECT, related_name="lease_charges")
    period_start = models.DateField(help_text="First day of the month being charged")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    paid_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(fields=["grid", "period_start"], name="one_lease_charge_per_grid_month"),
        ]

    def __str__(self):
        return f"{self.grid.code} {self.period_start:%b %Y} ₹{self.amount}"
