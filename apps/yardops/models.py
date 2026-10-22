"""Measurements taken at the yard, and the alerts they raise.

Rules shared with the customer stock records: a reading is never overwritten (a correction is a
new reading), and every reading and alert is also written to the tamper-evident ledger.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Role
from apps.core.codes import next_code
from apps.core.models import BaseModel
from apps.customers.models import Pile, Stockyard


class YardOperator(BaseModel):
    """A login for the people who work at a yard. They see only the yards they are linked to."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="yard_operator",
        limit_choices_to={"role": Role.YARD.value},
    )
    name = models.CharField(max_length=200)
    yards = models.ManyToManyField(Stockyard, related_name="operators", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.user_id and self.user.role != Role.YARD:
            raise ValidationError({"user": "This login must have the Yard operator role."})


class ReadingMethod(models.TextChoices):
    MANUAL_PROBE = "manual_probe", _("Manual probe")
    FIXED_SENSOR = "fixed_sensor", _("Fixed sensor")


class HeatReading(BaseModel):
    """The temperature inside a stack at one spot and time. A probe only speaks for its own spot."""

    pile = models.ForeignKey(Pile, on_delete=models.PROTECT, related_name="heat_readings")
    taken_at = models.DateTimeField(default=timezone.now)
    temperature_c = models.DecimalField(
        max_digits=5, decimal_places=1, validators=[MinValueValidator(Decimal("-20")), MaxValueValidator(Decimal("200"))],
        verbose_name="Temperature (°C)",
    )
    depth_cm = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(500)])
    spot = models.CharField(max_length=80, blank=True, help_text="For example north face, 1 m deep")
    method = models.CharField(max_length=12, choices=ReadingMethod.choices, default=ReadingMethod.MANUAL_PROBE)
    taken_by = models.CharField(max_length=100, blank=True)
    ledger_seq = models.PositiveBigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-taken_at"]

    def __str__(self):
        return f"{self.pile} {self.temperature_c} °C at {self.taken_at:%d %b %H:%M}"


class PileInspection(BaseModel):
    """A walk-round of a pile: what the inspector saw."""

    pile = models.ForeignKey(Pile, on_delete=models.PROTECT, related_name="inspections")
    inspected_at = models.DateTimeField(default=timezone.now)
    looks_wet = models.BooleanField(default=False)
    mould = models.BooleanField(default=False)
    steam_or_smell = models.BooleanField(default=False, help_text="Steam, or a burnt or musty smell")
    cover_in_place = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    inspected_by = models.CharField(max_length=100, blank=True)
    ledger_seq = models.PositiveBigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-inspected_at"]

    def __str__(self):
        return f"{self.pile} inspected {self.inspected_at:%d %b %H:%M}"


class AlertLevel(models.TextChoices):
    WATCH = "watch", _("Watch closely")
    ACT = "act", _("Check twice a day")
    EMERGENCY = "emergency", _("Fire likely")


class RiskAlert(BaseModel):
    """Raised when a pile reaches 'watch closely' or worse. Someone must acknowledge it."""

    code = models.CharField(max_length=20, unique=True, editable=False)
    pile = models.ForeignKey(Pile, on_delete=models.PROTECT, related_name="risk_alerts")
    level = models.CharField(max_length=10, choices=AlertLevel.choices)
    reasons = models.TextField(help_text="Why the alert was raised, one reason per line")
    raised_at = models.DateTimeField(default=timezone.now)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+", editable=False
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True, editable=False)
    resolved_at = models.DateTimeField(null=True, blank=True, editable=False)
    note = models.TextField(blank=True, help_text="What was done")
    ledger_seq = models.PositiveBigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-raised_at"]

    def __str__(self):
        return f"{self.code} {self.pile} {self.level}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("risk_alert", "ALR")
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.resolved_at is None

    @property
    def response_minutes(self):
        if self.acknowledged_at is None:
            return None
        return int((self.acknowledged_at - self.raised_at).total_seconds() // 60)
