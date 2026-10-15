"""Configurable lists that are never hard-coded in the application."""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import BaseModel


class Crop(BaseModel):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Season(BaseModel):
    name = models.CharField(max_length=50, unique=True)
    start_month = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)], help_text="1 = January"
    )
    end_month = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="12 = December. May be earlier than the start month if the season crosses the new year.",
    )

    class Meta:
        ordering = ["start_month"]

    def __str__(self):
        return self.name


class BiomassType(BaseModel):
    """The crop residue a crop leaves behind, and how much of it can be collected per acre."""

    name = models.CharField(max_length=100, unique=True, help_text="For example Paddy straw")
    crop = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="biomass_types")
    description = models.TextField(blank=True)
    estimated_tonnes_per_acre = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Collectable biomass from one acre. Leave empty until it is known: "
        "plots of this crop are then left out of the supply estimate.",
    )
    moisture_min_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, validators=[MaxValueValidator(100)]
    )
    moisture_max_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, validators=[MaxValueValidator(100)]
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        low, high = self.moisture_min_percent, self.moisture_max_percent
        if low is not None and high is not None and high < low:
            from django.core.exceptions import ValidationError

            raise ValidationError({"moisture_max_percent": "Maximum cannot be below the minimum."})


class StateBiomassFactor(BaseModel):
    """State-specific figures for a Biomass Type: yield per acre and expected pilferage.

    Yields and losses differ between states, so each state gets its own row. Where a state has
    no row (or leaves the yield empty) the Biomass Type's own figure is used, and pilferage is 0.
    """

    biomass_type = models.ForeignKey(BiomassType, on_delete=models.PROTECT, related_name="state_factors")
    state = models.ForeignKey("geography.State", on_delete=models.PROTECT, related_name="biomass_factors")
    estimated_tonnes_per_acre = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Collectable biomass per acre in this state. Empty = use the Biomass Type's own figure.",
    )
    pilferage_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Share of the estimate expected to be lost before it reaches the Mitra (theft, diversion, burning).",
    )

    class Meta:
        ordering = ["state__name", "biomass_type__name"]
        constraints = [
            models.UniqueConstraint(fields=["biomass_type", "state"], name="uniq_biomass_type_state"),
        ]

    def __str__(self):
        return f"{self.biomass_type} in {self.state}"
