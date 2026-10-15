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
    gcv_min = models.DecimalField(
        max_digits=7,
        decimal_places=0,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name="GCV minimum (kcal/kg)",
    )
    gcv_max = models.DecimalField(
        max_digits=7,
        decimal_places=0,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name="GCV maximum (kcal/kg)",
    )
    processing_requirement = models.TextField(
        blank=True, help_text="What this biomass needs before it can be sold, for example drying"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.gcv_min is not None and self.gcv_max is not None and self.gcv_max < self.gcv_min:
            from django.core.exceptions import ValidationError

            raise ValidationError({"gcv_max": "Maximum cannot be below the minimum."})
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


class ProcessingType(BaseModel):
    """A way of turning raw biomass into something sellable, such as baling or pelletising."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    input_biomass_types = models.ManyToManyField(
        BiomassType,
        blank=True,
        related_name="processing_types",
        help_text="Biomass this process can take in. Empty = not restricted yet.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(BaseModel):
    """Something Regenerix sells: raw biomass, or the output of a processing type, in a grade."""

    class Form(models.TextChoices):
        RAW = "raw", "Raw"
        PROCESSED = "processed", "Processed"

    name = models.CharField(max_length=150)
    form = models.CharField(max_length=10, choices=Form.choices)
    biomass_type = models.ForeignKey(BiomassType, on_delete=models.PROTECT, related_name="products")
    # The process that makes this product; a raw product has none. A processing type's
    # outputs are the products that point at it.
    processing_type = models.ForeignKey(
        ProcessingType, on_delete=models.PROTECT, null=True, blank=True, related_name="products"
    )
    grade = models.CharField(max_length=50, blank=True, help_text="For example A, B or Premium")
    minimum_gcv = models.DecimalField(
        max_digits=7,
        decimal_places=0,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name="Minimum GCV (kcal/kg)",
    )

    class Meta:
        ordering = ["name", "grade"]
        constraints = [
            models.UniqueConstraint(fields=["name", "grade"], name="uniq_product_name_grade"),
            models.CheckConstraint(
                condition=(
                    models.Q(form="raw", processing_type__isnull=True)
                    | models.Q(form="processed", processing_type__isnull=False)
                ),
                name="product_form_matches_processing_type",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.grade})" if self.grade else self.name

    def clean(self):
        super().clean()
        if self.form == self.Form.PROCESSED and not self.processing_type_id:
            from django.core.exceptions import ValidationError

            raise ValidationError({"processing_type": "A processed product needs a processing type."})
        if self.form == self.Form.RAW and self.processing_type_id:
            from django.core.exceptions import ValidationError

            raise ValidationError({"processing_type": "A raw product has no processing type."})
