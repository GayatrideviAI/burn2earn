from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.geo import area_acres
from apps.core.models import BaseModel, Status
from apps.geography.models import District, Panchayat, State


class Region(BaseModel):
    """The operational boundary of a pilot or network, created by Admin."""

    code = models.CharField(max_length=32, unique=True, help_text="For example REG-HR-AMB-001")
    name = models.CharField(max_length=200)
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="regions")
    # One district per Region for now; kept as its own link so multi-district
    # Regions can be added later without reshaping this table's callers.
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="regions")
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    def clean(self):
        super().clean()
        if self.state_id and self.district_id and self.district.state_id != self.state_id:
            raise ValidationError({"district": "This district is not in the selected state."})


class GeoCell(BaseModel):
    """The spatial aggregation unit. In V1 each cell is one panchayat."""

    class Origin(models.TextChoices):
        PANCHAYAT = "panchayat", "Panchayat"
        MITRA_DRAWN = "mitra_drawn", "Drawn by Mitra"

    code = models.CharField(max_length=40, unique=True)
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="geocells")
    # Required for panchayat cells; empty for Mitra-drawn cells (next version).
    panchayat = models.ForeignKey(
        Panchayat,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="geocells",
    )
    origin = models.CharField(
        max_length=12, choices=Origin.choices, default=Origin.PANCHAYAT
    )
    # MultiPolygon, not Polygon, because panchayat boundaries can have several parts.
    boundary = gis_models.MultiPolygonField(srid=4326)
    center_point = gis_models.PointField(srid=4326, null=True, blank=True, editable=False)
    area_acres = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, editable=False
    )
    notes = models.TextField(blank=True)
    # The only stored link between a cell and a Grid. The Grid's cell list, its
    # catchment and (later) its Mitra's cells are all derived from this.
    grid = models.ForeignKey(
        "network.Grid",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="geocells",
    )

    class Meta:
        ordering = ["code"]
        verbose_name = "GeoCell"
        verbose_name_plural = "GeoCells"
        constraints = [
            models.UniqueConstraint(
                fields=["panchayat"],
                condition=Q(status="active", panchayat__isnull=False),
                name="uniq_active_geocell_per_panchayat",
            ),
            models.CheckConstraint(
                condition=Q(origin="mitra_drawn") | Q(panchayat__isnull=False),
                name="geocell_panchayat_origin_needs_panchayat",
            ),
        ]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        # Area and centre are always derived from the boundary, never typed in.
        if self.boundary:
            self.center_point = self.boundary.centroid
            self.area_acres = area_acres(self.boundary)
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "center_point", "area_acres"}
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if self.origin == self.Origin.PANCHAYAT and not self.panchayat_id:
            errors["panchayat"] = "A panchayat cell must be linked to a panchayat."
        if self.grid_id and self.region_id and self.grid.region_id != self.region_id:
            errors["grid"] = "This Grid belongs to a different Region."
        if self.boundary and self.status == Status.ACTIVE:
            # Cells may share an edge but not an area. The database trigger is the
            # final guard; this gives a readable message in forms.
            overlapping = GeoCell.objects.filter(
                status=Status.ACTIVE, boundary__intersects=self.boundary
            ).exclude(boundary__touches=self.boundary)
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)
            codes = list(overlapping.values_list("code", flat=True)[:5])
            if codes:
                errors["boundary"] = "Overlaps active GeoCell(s): " + ", ".join(codes)
        if errors:
            raise ValidationError(errors)
