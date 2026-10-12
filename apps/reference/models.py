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
