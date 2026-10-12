"""Administrative geography, loaded from LGD (Local Government Directory) codes.

State > District > Block > Panchayat > Village. This is reference data: it is
imported with the management commands, not typed in by hand.
"""

from django.contrib.gis.db import models as gis_models
from django.db import models

from apps.core.models import BaseModel


class State(BaseModel):
    lgd_code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class District(BaseModel):
    lgd_code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=200)
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="districts")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Block(BaseModel):
    lgd_code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=200)
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="blocks")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Panchayat(BaseModel):
    lgd_code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=200)
    block = models.ForeignKey(Block, on_delete=models.PROTECT, related_name="panchayats")
    # Boundary polygons are imported separately and may be missing at first.
    boundary = gis_models.MultiPolygonField(srid=4326, null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Village(BaseModel):
    lgd_code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=200)
    panchayat = models.ForeignKey(
        Panchayat, on_delete=models.PROTECT, related_name="villages"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
