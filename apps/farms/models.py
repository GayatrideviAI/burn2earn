from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.codes import next_code
from apps.core.geo import area_acres
from apps.core.models import BaseModel, Status
from apps.core.validators import mobile_validator
from apps.geography.models import Village
from apps.network.models import Mitra
from apps.reference.models import Crop, Season
from apps.territory.models import GeoCell

from .placement import place_in_geocell


class Farmer(BaseModel):
    """A person who supplies crop residue. Registered by a Mitra, never self-registered."""

    class Language(models.TextChoices):
        HINDI = "hi", _("Hindi")
        ENGLISH = "en", _("English")
        PUNJABI = "pa", _("Punjabi")
        OTHER = "other", _("Other")

    # Personal data is kept out of the audit log; it only records that these changed.
    audit_redacted_fields = ("name", "mobile")

    code = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=200)
    # Not unique: families share phones. Possible duplicates are flagged, not blocked.
    # Empty only after the farmer's data has been anonymised.
    mobile = models.CharField(max_length=16, blank=True, validators=[mobile_validator])
    village = models.ForeignKey(Village, on_delete=models.PROTECT, related_name="farmers")
    preferred_language = models.CharField(max_length=10, choices=Language.choices, blank=True)
    registered_by_mitra = models.ForeignKey(
        Mitra, on_delete=models.PROTECT, related_name="registered_farmers"
    )
    anonymised_at = models.DateTimeField(null=True, blank=True, editable=False)
    # Set when another active farmer has the same mobile number. Never merged automatically:
    # an Admin looks at it and clears the flag.
    needs_review = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("farmer", "FRM")
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.anonymised_at and not self.mobile:
            raise ValidationError({"mobile": "Enter the farmer's mobile number."})

    @property
    def has_consent(self):
        return self.consents.filter(withdrawn_at__isnull=True).exists()

    def withdraw_consent(self):
        """The farmer withdraws consent: record it and anonymise their personal data."""
        now = timezone.now()
        with transaction.atomic():
            # Saved one by one (not a bulk update) so each change reaches the audit log.
            for record in self.consents.filter(withdrawn_at__isnull=True):
                record.withdrawn_at = now
                record.save()
            self.anonymise(when=now)

    def anonymise(self, when=None):
        """Remove the name and mobile number. Plots and crop records stay, unlinked from the person."""
        self.name = "Anonymised farmer"
        self.mobile = ""
        self.preferred_language = ""
        self.anonymised_at = when or timezone.now()
        self.status = Status.INACTIVE
        self.save()


class ConsentRecord(BaseModel):
    """Proof that a farmer agreed to the use of their data, and when they withdrew."""

    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="consents")
    purpose = models.CharField(
        max_length=200, default="Registration and collection of crop residue"
    )
    notice_version = models.CharField(
        max_length=20, help_text="Which wording of the notice the farmer was given"
    )
    language = models.CharField(max_length=10, blank=True, help_text="Language the notice was explained in")
    given_at = models.DateTimeField(default=timezone.now)
    captured_by_mitra = models.ForeignKey(
        Mitra, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-given_at"]

    def __str__(self):
        return f"Consent {self.farmer.code} {self.given_at:%Y-%m-%d}"


class FarmPlot(BaseModel):
    """A piece of land. One farmer can have many plots, in many GeoCells."""

    class Ownership(models.TextChoices):
        OWNED = "owned", _("Owned")
        LEASED = "leased", _("Leased")
        SHARECROPPED = "sharecropped", _("Sharecropped")

    class Irrigation(models.TextChoices):
        CANAL = "canal", _("Canal")
        TUBEWELL = "tubewell", _("Tubewell")
        RAINFED = "rainfed", _("Rain-fed")
        OTHER = "other", _("Other")

    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="plots")
    location = gis_models.PointField(srid=4326)
    boundary = gis_models.PolygonField(srid=4326, null=True, blank=True)
    # Set by the system from the location and boundary, never chosen by hand.
    geocell = models.ForeignKey(
        GeoCell,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="plots",
    )
    # Worked out from the boundary when there is one; otherwise typed in.
    area_acres = models.DecimalField(max_digits=10, decimal_places=2, blank=True)
    ownership = models.CharField(max_length=14, choices=Ownership.choices, blank=True)
    irrigation = models.CharField(max_length=10, choices=Irrigation.choices, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Plot of {self.farmer.code} ({self.area_acres} acres)"

    def save(self, *args, **kwargs):
        if self.boundary:
            self.area_acres = area_acres(self.boundary)
        self.geocell = place_in_geocell(self.location, self.boundary or None)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "area_acres", "geocell"}
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.boundary and self.area_acres is None:
            raise ValidationError({"area_acres": "Enter the area, or draw the plot boundary."})

    @property
    def outside_geocells(self):
        return self.geocell_id is None

    @property
    def panchayat_differs_from_village(self):
        """True when the plot's cell is in a different panchayat from the farmer's village.

        Farmers often farm outside their own panchayat, so this is a warning only.
        """
        cell = self.geocell
        if cell is None or cell.panchayat_id is None:
            return False
        return cell.panchayat_id != self.farmer.village.panchayat_id


class PlotSeason(BaseModel):
    """What was grown on a plot in a season. Crop and season change, the plot does not."""

    plot = models.ForeignKey(FarmPlot, on_delete=models.PROTECT, related_name="seasons")
    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name="+")
    crop = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="+")
    # The year the season starts in (a Rabi crop sown in Nov 2026 is Rabi 2026).
    year = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(2000), MaxValueValidator(2100)]
    )
    variety = models.CharField(max_length=100, blank=True)
    sowing_date = models.DateField(null=True, blank=True)
    expected_harvest_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-year", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["plot", "season", "year", "crop"],
                name="uniq_plot_season_year_crop",
            ),
            models.CheckConstraint(
                condition=(
                    Q(expected_harvest_date__isnull=True)
                    | Q(sowing_date__isnull=True)
                    | Q(expected_harvest_date__gte=F("sowing_date"))
                ),
                name="harvest_not_before_sowing",
            ),
        ]

    def __str__(self):
        return f"{self.crop} {self.season} {self.year}"

    def clean(self):
        super().clean()
        if (
            self.sowing_date
            and self.expected_harvest_date
            and self.expected_harvest_date < self.sowing_date
        ):
            raise ValidationError(
                {"expected_harvest_date": "The harvest date cannot be before the sowing date."}
            )
