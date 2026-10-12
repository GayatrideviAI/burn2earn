"""The physical network: Hubs and Biomass Grids."""

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.db.models import Union
from django.db import models

from apps.accounts.models import Role
from apps.core.models import BaseModel, OperatingStatus, Status
from apps.territory.models import Region


class Hub(BaseModel):
    """A storage point that several Grids feed into. Run by Regenerix staff."""

    code = models.CharField(max_length=32, unique=True, help_text="For example HUB-HR-AMB-001")
    name = models.CharField(max_length=200)
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="hubs")
    location = gis_models.PointField(srid=4326)
    storage_capacity_t = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="Tonnes"
    )
    # Regenerix staff are Admin accounts in V1.
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="operated_hubs",
        limit_choices_to={"role": Role.ADMIN.value},
    )
    operating_status = models.CharField(
        max_length=14, choices=OperatingStatus.choices, default=OperatingStatus.PLANNED
    )
    commissioning_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class Grid(BaseModel):
    """The processing site run by one Biomass Mitra, covering 7 to 10 GeoCells."""

    MIN_GEOCELLS = 7
    MAX_GEOCELLS = 10

    code = models.CharField(max_length=32, unique=True, help_text="For example GRID-HR-AMB-001")
    name = models.CharField(max_length=200)
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="grids")
    location = gis_models.PointField(srid=4326)
    # Many Grids can feed one Hub; empty until the Hub exists.
    hub = models.ForeignKey(
        Hub, on_delete=models.PROTECT, null=True, blank=True, related_name="grids"
    )
    processing_capacity_tpd = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Tonnes per day"
    )
    storage_capacity_t = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="Tonnes"
    )
    operating_status = models.CharField(
        max_length=14, choices=OperatingStatus.choices, default=OperatingStatus.PLANNED
    )
    commissioning_date = models.DateField(null=True, blank=True)
    # Processing types are added with the Processing Type master in build step 4.

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def active_geocells(self):
        return self.geocells.filter(status=Status.ACTIVE)

    @property
    def geocell_count(self):
        return self.active_geocells.count()

    @property
    def geocell_count_note(self):
        """A warning when the cell count is outside the expected range, else ''."""
        count = self.geocell_count
        if self.MIN_GEOCELLS <= count <= self.MAX_GEOCELLS:
            return ""
        return f"Expected {self.MIN_GEOCELLS} to {self.MAX_GEOCELLS} GeoCells"

    @property
    def catchment(self):
        """The Grid's catchment area: the union of its active GeoCells (derived, not stored)."""
        return self.active_geocells.aggregate(area=Union("boundary"))["area"]
