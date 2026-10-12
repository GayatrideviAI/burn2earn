"""The physical network: Hubs, Biomass Grids, Mitras and equipment."""

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.db.models import Union
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.accounts.models import Role
from apps.core.models import BaseModel, OperatingStatus, Status
from apps.core.validators import mobile_validator
from apps.territory.models import GeoCell, Region


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

    @property
    def current_assignment(self):
        return (
            self.mitra_assignments.filter(to_date__isnull=True, status=Status.ACTIVE)
            .select_related("mitra")
            .first()
        )

    @property
    def current_mitra(self):
        assignment = self.current_assignment
        return assignment.mitra if assignment else None


class OnboardingStatus(models.TextChoices):
    INVITED = "invited", "Invited"
    AGREEMENT_PENDING = "agreement_pending", "Agreement pending"
    AGREEMENT_SIGNED = "agreement_signed", "Agreement signed"
    VERIFIED = "verified", "Verified"


class MitraOperatingStatus(models.TextChoices):
    PENDING = "pending", "Not started yet"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    EXITED = "exited", "Exited"


class Mitra(BaseModel):
    """The physical operator who runs a Biomass Grid.

    A Mitra has no cell or equipment list of its own: both come from the Grid it
    is currently assigned to, so there is nothing to keep in sync.
    """

    code = models.CharField(
        max_length=32, unique=True, help_text="For example MITRA-HR-AMB-001"
    )
    name = models.CharField(max_length=200, help_text="Person or organisation")
    mobile = models.CharField(max_length=16, validators=[mobile_validator])
    address = models.TextField()
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="mitras")
    # The Mitra's login, kept separate from this record. At most one account each.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="mitra",
        limit_choices_to={"role": Role.MITRA.value},
    )
    onboarding_status = models.CharField(
        max_length=20, choices=OnboardingStatus.choices, default=OnboardingStatus.INVITED
    )
    operating_status = models.CharField(
        max_length=10,
        choices=MitraOperatingStatus.choices,
        default=MitraOperatingStatus.PENDING,
    )
    activated_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    def clean(self):
        super().clean()
        errors = {}
        if self.operating_status == MitraOperatingStatus.ACTIVE and not self.activated_on:
            errors["activated_on"] = "Enter the date this Mitra was activated."
        if self.user_id and self.user.role != Role.MITRA:
            errors["user"] = "The login must be an account with the Biomass Mitra role."
        if errors:
            raise ValidationError(errors)

    @property
    def current_assignment(self):
        return (
            self.grid_assignments.filter(to_date__isnull=True, status=Status.ACTIVE)
            .select_related("grid")
            .first()
        )

    @property
    def current_grid(self):
        assignment = self.current_assignment
        return assignment.grid if assignment else None

    @property
    def geocells(self):
        """The cells this Mitra covers: the active cells of their current Grid."""
        grid = self.current_grid
        if grid is None:
            return GeoCell.objects.none()
        return grid.active_geocells

    @property
    def equipment(self):
        """The equipment at this Mitra's current Grid."""
        grid = self.current_grid
        if grid is None:
            return Equipment.objects.none()
        return grid.equipment.filter(status=Status.ACTIVE)


class MitraGridAssignment(BaseModel):
    """Which Mitra runs which Grid, and for what dates.

    An assignment with no end date is the current one. To change a Grid's Mitra,
    end the old assignment (set its end date) and add a new one, so the history
    stays. A Grid has one current Mitra and a Mitra has one current Grid.
    """

    mitra = models.ForeignKey(Mitra, on_delete=models.PROTECT, related_name="grid_assignments")
    grid = models.ForeignKey(Grid, on_delete=models.PROTECT, related_name="mitra_assignments")
    from_date = models.DateField()
    to_date = models.DateField(null=True, blank=True, help_text="Leave empty for the current assignment")

    class Meta:
        ordering = ["-from_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["grid"],
                condition=Q(status="active", to_date__isnull=True),
                name="uniq_current_mitra_per_grid",
            ),
            models.UniqueConstraint(
                fields=["mitra"],
                condition=Q(status="active", to_date__isnull=True),
                name="uniq_current_grid_per_mitra",
            ),
            models.CheckConstraint(
                condition=Q(to_date__isnull=True) | Q(to_date__gte=F("from_date")),
                name="assignment_end_not_before_start",
            ),
        ]

    def __str__(self):
        return f"{self.mitra.code} on {self.grid.code} from {self.from_date}"

    def clean(self):
        super().clean()
        errors = {}
        if self.to_date and self.from_date and self.to_date < self.from_date:
            errors["to_date"] = "The end date cannot be before the start date."
        if self.mitra_id and self.grid_id and self.mitra.region_id != self.grid.region_id:
            errors["grid"] = "This Grid is in a different Region from the Mitra."
        if errors:
            raise ValidationError(errors)
        if self.to_date is None and self.status == Status.ACTIVE:
            others = MitraGridAssignment.objects.filter(
                to_date__isnull=True, status=Status.ACTIVE
            ).exclude(pk=self.pk)
            if self.grid_id and others.filter(grid_id=self.grid_id).exists():
                raise ValidationError(
                    "This Grid already has a current Mitra. End that assignment first."
                )
            if self.mitra_id and others.filter(mitra_id=self.mitra_id).exists():
                raise ValidationError(
                    "This Mitra already has a current Grid. End that assignment first."
                )


class EquipmentType(BaseModel):
    """Configurable list of kinds of equipment (pelletizer, baler...)."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class EquipmentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    UNDER_MAINTENANCE = "under_maintenance", "Under maintenance"
    RETIRED = "retired", "Retired"


class CapacityUnit(models.TextChoices):
    TONNES_PER_HOUR = "t_per_hour", "Tonnes per hour"
    TONNES_PER_DAY = "t_per_day", "Tonnes per day"
    KG_PER_HOUR = "kg_per_hour", "Kilograms per hour"
    TONNES = "tonnes", "Tonnes (load)"


class Equipment(BaseModel):
    """A machine or vehicle. It sits at exactly one Grid or one Hub."""

    code = models.CharField(max_length=32, unique=True, help_text="Asset tag or internal ID")
    equipment_type = models.ForeignKey(
        EquipmentType, on_delete=models.PROTECT, related_name="equipment"
    )
    serial_number = models.CharField(max_length=100, blank=True)
    manufacturer = models.CharField(max_length=100, blank=True)
    capacity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    capacity_unit = models.CharField(max_length=12, choices=CapacityUnit.choices, blank=True)
    grid = models.ForeignKey(
        Grid, on_delete=models.PROTECT, null=True, blank=True, related_name="equipment"
    )
    hub = models.ForeignKey(
        Hub, on_delete=models.PROTECT, null=True, blank=True, related_name="equipment"
    )
    installation_date = models.DateField(null=True, blank=True)
    last_maintenance = models.DateField(null=True, blank=True)
    next_maintenance = models.DateField(null=True, blank=True)
    operating_status = models.CharField(
        max_length=20, choices=EquipmentStatus.choices, default=EquipmentStatus.ACTIVE
    )

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "equipment"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(grid__isnull=False, hub__isnull=True)
                    | Q(grid__isnull=True, hub__isnull=False)
                ),
                name="equipment_at_exactly_one_site",
            ),
        ]

    def __str__(self):
        return f"{self.code} ({self.equipment_type})"

    def clean(self):
        super().clean()
        if bool(self.grid_id) == bool(self.hub_id):
            raise ValidationError("Choose either a Grid or a Hub for this equipment, not both.")
        errors = {}
        if self.capacity is not None and not self.capacity_unit:
            errors["capacity_unit"] = "Choose a unit for the capacity."
        if (
            self.last_maintenance
            and self.next_maintenance
            and self.next_maintenance < self.last_maintenance
        ):
            errors["next_maintenance"] = "The next maintenance cannot be before the last one."
        if errors:
            raise ValidationError(errors)
