from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.codes import next_code
from apps.core.models import BaseModel
from apps.farms.models import Farmer, FarmPlot
from apps.network.models import Grid, Mitra
from apps.reference.models import BiomassType, Product


class CollectionRecord(BaseModel):
    """Residue a Mitra picked up from a farmer, and what was paid for it."""

    code = models.CharField(max_length=20, unique=True, editable=False)
    mitra = models.ForeignKey(Mitra, on_delete=models.PROTECT, related_name="collections")
    # The Mitra's Grid on the day, kept on the record so history survives a Grid change.
    grid = models.ForeignKey(Grid, on_delete=models.PROTECT, related_name="collections")
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="collections")
    plot = models.ForeignKey(
        FarmPlot, on_delete=models.PROTECT, null=True, blank=True, related_name="collections"
    )
    biomass_type = models.ForeignKey(BiomassType, on_delete=models.PROTECT, related_name="collections")
    quantity_tonnes = models.DecimalField(
        max_digits=10, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))]
    )
    price_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Total rupees paid to the farmer for this pickup",
    )
    collected_on = models.DateField(default=date.today)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-collected_on", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity_tonnes__gt=0), name="collection_quantity_positive"),
        ]

    def __str__(self):
        return f"{self.code} {self.quantity_tonnes} t"

    @property
    def rate_per_tonne(self):
        return (self.price_paid / self.quantity_tonnes).quantize(Decimal("0.01"))

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("collection", "COL")
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.plot_id and self.farmer_id and self.plot.farmer_id != self.farmer_id:
            raise ValidationError("This plot belongs to a different farmer.")


class ProcessedOutput(BaseModel):
    """Pellets, briquettes or other product made at a Grid, reported up by the Mitra.

    The Hub sees it through the Grid's Hub, so it is stored once, against the Grid.
    """

    code = models.CharField(max_length=20, unique=True, editable=False)
    mitra = models.ForeignKey(Mitra, on_delete=models.PROTECT, related_name="outputs")
    grid = models.ForeignKey(Grid, on_delete=models.PROTECT, related_name="outputs")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="outputs")
    quantity_tonnes = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
        help_text="A rough figure is fine",
    )
    biomass_used_tonnes = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Raw residue used up making this. Leave empty if not known; the stock tally then does not subtract it.",
    )
    produced_on = models.DateField(default=date.today)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-produced_on", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity_tonnes__gt=0), name="output_quantity_positive"),
        ]

    def __str__(self):
        return f"{self.code} {self.product} {self.quantity_tonnes} t"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("output", "OUT")
        super().save(*args, **kwargs)
