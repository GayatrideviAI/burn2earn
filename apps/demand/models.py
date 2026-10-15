from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

from apps.accounts.models import Role
from apps.core.codes import next_code
from apps.core.models import BaseModel, OperatingStatus
from apps.core.validators import mobile_validator
from apps.reference.models import BiomassType

gst_validator = RegexValidator(
    regex=r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$",
    message="Enter a 15-character GST number, for example 06ABCDE1234F1Z5.",
)


class CommercialStatus(models.TextChoices):
    PROSPECT = "prospect", "Prospect"
    ACTIVE = "active", "Active customer"
    ON_HOLD = "on_hold", "On hold"
    CLOSED = "closed", "Closed"


class Buyer(BaseModel):
    """The commercial company that buys biomass. Its physical sites are Factories."""

    # Contact details are personal data, so the audit log only records that they changed.
    audit_redacted_fields = ("contact_name", "contact_mobile", "contact_email")

    code = models.CharField(max_length=20, unique=True, editable=False)
    company_name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=200)
    contact_mobile = models.CharField(max_length=16, validators=[mobile_validator])
    contact_email = models.EmailField(blank=True)
    gst_number = models.CharField(max_length=15, blank=True, validators=[gst_validator])
    commercial_status = models.CharField(
        max_length=10, choices=CommercialStatus.choices, default=CommercialStatus.PROSPECT
    )
    payment_terms = models.TextField(help_text="For example: payment within 15 days of delivery")
    # The buyer's own login. Not used in V1; each login belongs to at most one Buyer.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="buyer",
        limit_choices_to={"role": Role.BUYER.value},
    )

    class Meta:
        ordering = ["company_name"]

    def __str__(self):
        return f"{self.code} {self.company_name}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("buyer", "BUY")
        self.gst_number = self.gst_number.strip().upper()
        super().save(*args, **kwargs)


class Factory(BaseModel):
    """A physical site that consumes biomass. Belongs to one Buyer."""

    code = models.CharField(max_length=20, unique=True, editable=False)
    buyer = models.ForeignKey(Buyer, on_delete=models.PROTECT, related_name="factories")
    name = models.CharField(max_length=200)
    location = gis_models.PointField(srid=4326)
    delivery_address = models.TextField()
    preferred_biomass_types = models.ManyToManyField(
        BiomassType, blank=True, related_name="preferring_factories"
    )
    # Standing quality requirement. What a factory needs in a given period is a requirement
    # posting, which is a transaction and comes later.
    minimum_gcv = models.DecimalField(
        max_digits=7,
        decimal_places=0,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name="Minimum GCV (kcal/kg)",
    )
    maximum_moisture_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    operating_status = models.CharField(
        max_length=14, choices=OperatingStatus.choices, default=OperatingStatus.PLANNED
    )

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "factories"

    def __str__(self):
        return f"{self.code} {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("factory", "FAC")
        super().save(*args, **kwargs)
