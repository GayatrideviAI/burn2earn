"""Customer-side stock: yards, piles, batches and everything that changes how much of a batch there is.

Three rules from the product spec shape this file:
* Quantities are never overwritten. A batch's book stock is the sum of its transactions.
* A measured reading is never mixed up with an estimate (QualityObservation.basis).
* A physical count (StockCount) is a separate record from the book figure, so the gap between them shows.
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.codes import next_code
from apps.core.models import BaseModel
from apps.demand.models import Buyer, Factory
from apps.network.models import Grid
from apps.reference.models import BiomassType, Product
from apps.territory.models import Region

POSITIVE_TONNES = MinValueValidator(Decimal("0.001"))
PERCENT = [MinValueValidator(0), MaxValueValidator(100)]


class JobRole(models.TextChoices):
    PROCUREMENT = "procurement", "Procurement / fuel manager"
    OPERATIONS = "operations", "Plant operations"
    FINANCE = "finance", "Finance"
    ESG = "esg", "ESG / sustainability"


class CustomerMember(BaseModel):
    """A login that belongs to a customer company. Members see only that company's stock."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="customer_member",
        limit_choices_to={"role": Role.BUYER.value},
    )
    buyer = models.ForeignKey(Buyer, on_delete=models.PROTECT, related_name="members")
    job_role = models.CharField(max_length=12, choices=JobRole.choices)

    class Meta:
        ordering = ["buyer__company_name", "user__username"]

    def __str__(self):
        return f"{self.user.username} at {self.buyer.company_name}"

    def clean(self):
        super().clean()
        if self.user_id and self.user.role != Role.BUYER:
            raise ValidationError({"user": "This login must have the Buyer role."})


class PlantProfile(BaseModel):
    """How much a plant burns. The quality limits (moisture, GCV) already sit on the Factory."""

    factory = models.OneToOneField(Factory, on_delete=models.PROTECT, related_name="profile")
    daily_consumption_tonnes = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)], help_text="Average tonnes burned per day"
    )

    def __str__(self):
        return f"{self.factory} burns {self.daily_consumption_tonnes} t/day"


class OwnerType(models.TextChoices):
    REGENERIX = "regenerix", "Regenerix"
    VLE = "vle", "VLE"
    THIRD_PARTY = "third_party", "Third party"
    CUSTOMER = "customer", "The customer"


class Stockyard(BaseModel):
    code = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=200)
    location = gis_models.PointField(srid=4326)
    owner_type = models.CharField(max_length=12, choices=OwnerType.choices, default=OwnerType.REGENERIX)
    owner_name = models.CharField(max_length=200, blank=True)
    capacity_tonnes = models.DecimalField(
        max_digits=10, decimal_places=0, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    region = models.ForeignKey(Region, on_delete=models.PROTECT, null=True, blank=True, related_name="stockyards")
    notes = models.TextField(blank=True, help_text="Roofed and open areas, drainage, safety requirements")

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("stockyard", "YRD")
        super().save(*args, **kwargs)


class BiomassForm(models.TextChoices):
    BALES = "bales", "Bales"
    LOOSE = "loose", "Loose chopped straw"
    PELLETS = "pellets", "Pellets"
    BRIQUETTES = "briquettes", "Briquettes"


class Exposure(models.TextChoices):
    OPEN = "open", "Open to rain"
    PART = "part", "Part covered"
    PROTECTED = "protected", "Protected"


class Pile(BaseModel):
    """A storage unit inside a yard: a stack, a shed bay or a bagged pallet block."""

    yard = models.ForeignKey(Stockyard, on_delete=models.PROTECT, related_name="piles")
    label = models.CharField(max_length=20, help_text="For example A-01")
    form = models.CharField(max_length=10, choices=BiomassForm.choices)
    exposure = models.CharField(max_length=10, choices=Exposure.choices, default=Exposure.OPEN)
    cover_type = models.CharField(max_length=100, blank=True, help_text="For example tarp, shed, none")

    class Meta:
        ordering = ["yard__code", "label"]
        constraints = [models.UniqueConstraint(fields=["yard", "label"], name="unique_pile_label_per_yard")]

    def __str__(self):
        return f"{self.yard.name} / {self.label}"


class Batch(BaseModel):
    """A lot of one material with a unique ID (the QR tag). It belongs to one customer."""

    code = models.CharField(max_length=20, unique=True, editable=False, help_text="Printed on the QR tag")
    customer = models.ForeignKey(Buyer, on_delete=models.PROTECT, related_name="batches")
    pile = models.ForeignKey(Pile, on_delete=models.PROTECT, related_name="batches")
    biomass_type = models.ForeignKey(BiomassType, on_delete=models.PROTECT, related_name="+")
    form = models.CharField(max_length=10, choices=BiomassForm.choices)
    source_grid = models.ForeignKey(Grid, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    # The delivery this batch was put into the yard from. One delivered load can be split into several batches.
    source_dispatch = models.ForeignKey(
        "trade.Dispatch", on_delete=models.PROTECT, null=True, blank=True, related_name="yard_batches",
        help_text="The delivered load this batch came from, so it can be traced back to its farmers",
    )
    source_note = models.TextField(blank=True, help_text="Source villages and the VLE or supplier")
    received_on = models.DateField(default=timezone.localdate)
    intake_tonnes = models.DecimalField(max_digits=10, decimal_places=3, validators=[POSITIVE_TONNES])
    intake_moisture_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, validators=PERCENT
    )

    class Meta:
        ordering = ["-received_on", "code"]
        verbose_name_plural = "batches"

    def __str__(self):
        return f"{self.code} {self.get_form_display()}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("batch", "BAT")
        d = self.source_dispatch if self.source_dispatch_id else None
        if d is not None and self._state.adding:
            if self.source_grid_id is None:
                self.source_grid = d.grid
            if not self.source_note:
                mitra = d.created_by_mitra or d.grid.current_mitra
                self.source_note = f"Load {d.code} from {d.grid.name}" + (f", Mitra {mitra.name}" if mitra else "")
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.check_source()

    def check_source(self):
        """A batch from a delivery must match that delivery and cannot be bigger than what is left of it."""
        from apps.trade.models import DispatchStage

        d = self.source_dispatch if self.source_dispatch_id else None
        if d is None or not self.customer_id:
            return
        if d.stage != DispatchStage.DELIVERED:
            raise ValidationError("That load has not been delivered yet.")
        if d.factory.buyer_id != self.customer_id:
            raise ValidationError("That load was delivered to a different company.")
        if self.biomass_type_id and d.product.biomass_type_id != self.biomass_type_id:
            raise ValidationError("The biomass type does not match the delivered load.")
        if self.intake_tonnes is not None:
            left = unreceived_tonnes(d, exclude=self.pk)
            if self.intake_tonnes > left:
                raise ValidationError(f"Only {left} t of {d.code} is still to be put into the yard.")


class TransactionKind(models.TextChoices):
    RECEIPT = "receipt", "Receipt"
    TRANSFER = "transfer", "Moved to another pile"
    CONSUMPTION = "consumption", "Burned at the plant"
    ADJUSTMENT = "adjustment", "Adjustment"
    LOSS = "loss", "Loss"
    RETURN = "return", "Returned to supplier"
    DISPOSAL = "disposal", "Disposed of"


class LossCause(models.TextChoices):
    RAIN = "rain", "Rain"
    DECOMPOSITION = "decomposition", "Decomposition"
    CONTAMINATION = "contamination", "Contamination"
    HANDLING = "handling", "Handling"
    FIRE = "fire", "Fire"
    OTHER = "other", "Other"


class InventoryTransaction(BaseModel):
    """One change to a batch. Added through apps.customers.services so the ledger sees it too."""

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="transactions")
    kind = models.CharField(max_length=12, choices=TransactionKind.choices)
    tonnes_change = models.DecimalField(max_digits=10, decimal_places=3, editable=False)
    loss_cause = models.CharField(max_length=14, choices=LossCause.choices, blank=True)
    to_pile = models.ForeignKey(Pile, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    occurred_at = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)
    ledger_seq = models.PositiveBigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-occurred_at", "-created_at"]

    def __str__(self):
        return f"{self.batch.code} {self.get_kind_display()} {self.tonnes_change} t"


class Basis(models.TextChoices):
    MEASURED = "measured", "Measured"
    ESTIMATED = "estimated", "Estimated"


class QualityObservation(BaseModel):
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="quality")
    basis = models.CharField(max_length=10, choices=Basis.choices, default=Basis.MEASURED)
    observed_at = models.DateTimeField(default=timezone.now)
    moisture_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=PERCENT)
    ash_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=PERCENT)
    gcv = models.DecimalField(
        max_digits=7, decimal_places=0, null=True, blank=True, validators=[MinValueValidator(0)],
        verbose_name="GCV (kcal/kg)",
    )
    method = models.CharField(max_length=60, blank=True, help_text="For example handheld meter, lab test")
    tested_by = models.CharField(max_length=100, blank=True)
    ledger_seq = models.PositiveBigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-observed_at"]

    def __str__(self):
        return f"{self.batch.code} quality on {self.observed_at:%d %b %Y}"

    def clean(self):
        super().clean()
        if self.moisture_percent is None and self.ash_percent is None and self.gcv is None:
            raise ValidationError("Enter at least one reading: moisture, ash or GCV.")


class CountMethod(models.TextChoices):
    WEIGHBRIDGE = "weighbridge", "Weighbridge"
    QR_SCAN = "qr_scan", "QR scan and count"
    SURVEY = "survey", "Survey or drone estimate"
    AUDIT = "audit", "Physical audit"


class StockCount(BaseModel):
    """What was physically found. Compared with the book figure, not merged into it."""

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="counts")
    counted_tonnes = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(0)])
    method = models.CharField(max_length=12, choices=CountMethod.choices)
    counted_on = models.DateField(default=timezone.localdate)
    counted_by = models.CharField(max_length=100, blank=True)
    ledger_seq = models.PositiveBigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-counted_on", "-created_at"]

    def __str__(self):
        return f"{self.batch.code} counted {self.counted_tonnes} t on {self.counted_on}"


class Reservation(BaseModel):
    """Stock set aside for a plant. Deactivate it to release the stock."""

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="reservations")
    factory = models.ForeignKey(Factory, on_delete=models.PROTECT, related_name="reservations")
    tonnes = models.DecimalField(max_digits=10, decimal_places=3, validators=[POSITIVE_TONNES])
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tonnes} t of {self.batch.code} for {self.factory.name}"


# ---- contracts and purchase orders --------------------------------------------------------------


class RiskBearer(models.TextChoices):
    REGENERIX = "regenerix", "Regenerix"
    YARD_OPERATOR = "yard_operator", "The yard operator"
    CUSTOMER = "customer", "The customer"
    SHARED = "shared", "Shared (see notes)"


class Contract(BaseModel):
    """A customer's supply agreement for a period. Quantities sit on its lines, one per product."""

    code = models.CharField(max_length=20, unique=True, editable=False)
    customer = models.ForeignKey(Buyer, on_delete=models.PROTECT, related_name="contracts")
    reference = models.CharField(max_length=100, blank=True, help_text="The customer's own contract number")
    start_date = models.DateField()
    end_date = models.DateField()
    penalties = models.TextField(blank=True, help_text="Late delivery and quality penalty terms")
    risk_bearer = models.CharField(
        max_length=14, choices=RiskBearer.choices, default=RiskBearer.REGENERIX,
        help_text="Who bears spoilage, rain and fire loss while stock is in a yard",
    )
    allocated_yards = models.ManyToManyField(Stockyard, blank=True, related_name="contracts")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-start_date", "code"]
        constraints = [
            models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")), name="contract_dates_in_order"),
        ]

    def __str__(self):
        return f"{self.code} {self.customer.company_name}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("contract", "CON")
        super().save(*args, **kwargs)


class ContractLine(BaseModel):
    """The quantity of one product a contract covers, with its price and quality limits."""

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    contracted_tonnes = models.DecimalField(max_digits=12, decimal_places=3, validators=[POSITIVE_TONNES])
    price_per_tonne = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    max_moisture_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=PERCENT)
    min_gcv = models.DecimalField(
        max_digits=7, decimal_places=0, null=True, blank=True, validators=[MinValueValidator(0)],
        verbose_name="Minimum GCV (kcal/kg)",
    )

    class Meta:
        ordering = ["contract__code", "product__name"]
        constraints = [models.UniqueConstraint(fields=["contract", "product"], name="one_line_per_product_in_contract")]

    def __str__(self):
        return f"{self.contract.code} {self.product} {self.contracted_tonnes} t"


class MonthlyPlan(BaseModel):
    """How much of a line is planned to arrive in a month (the drawdown schedule)."""

    line = models.ForeignKey(ContractLine, on_delete=models.PROTECT, related_name="plan")
    month = models.DateField(help_text="Any date in the month; saved as the first of the month")
    planned_tonnes = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ["line", "month"]
        constraints = [models.UniqueConstraint(fields=["line", "month"], name="one_plan_per_line_month")]

    def __str__(self):
        return f"{self.line.contract.code} {self.month:%b %Y}: {self.planned_tonnes} t"

    def save(self, *args, **kwargs):
        self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)


class OrderState(models.TextChoices):
    OPEN = "open", "Open"
    FULFILLED = "fulfilled", "Fulfilled"
    CANCELLED = "cancelled", "Cancelled"


class PurchaseOrder(BaseModel):
    """A call-off against a contract line: this much, to this plant, in this window."""

    code = models.CharField(max_length=20, unique=True, editable=False)
    line = models.ForeignKey(ContractLine, on_delete=models.PROTECT, related_name="orders")
    factory = models.ForeignKey(Factory, on_delete=models.PROTECT, related_name="purchase_orders")
    customer_po_number = models.CharField(max_length=60, blank=True, help_text="The customer's own PO number")
    tonnes = models.DecimalField(max_digits=12, decimal_places=3, validators=[POSITIVE_TONNES])
    deliver_from = models.DateField()
    deliver_by = models.DateField()
    state = models.CharField(max_length=10, choices=OrderState.choices, default=OrderState.OPEN)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["deliver_by", "code"]
        constraints = [
            models.CheckConstraint(condition=models.Q(deliver_by__gte=models.F("deliver_from")), name="po_dates_in_order"),
        ]

    def __str__(self):
        return f"{self.code} {self.tonnes} t {self.line.product}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("purchase_order", "PO")
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.line_id and self.factory_id and self.factory.buyer_id != self.line.contract.customer_id:
            raise ValidationError({"factory": "This plant belongs to a different company than the contract."})


def unreceived_tonnes(dispatch, exclude=None):
    """Tonnes weighed at the buyer's gate that no yard batch accounts for yet."""
    from django.db.models import Sum

    taken = Batch.objects.filter(source_dispatch=dispatch, status="active")
    if exclude is not None:
        taken = taken.exclude(pk=exclude)
    return dispatch.current_quantity_tonnes - (taken.aggregate(t=Sum("intake_tonnes"))["t"] or Decimal("0"))
