"""Photos of stacks and loaded vehicles, kept with the weighbridge weight so a weight-from-photo
model can be trained and checked later.

No weight is predicted from these photos yet. The aim for now is to collect enough pairs of
(photo, true weight) from real yards and routes. A photo is never replaced or deleted; a wrong
weight is corrected by staff in Admin, and every change goes to the tamper-evident ledger.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.codes import next_code
from apps.core.models import BaseModel
from apps.customers.models import Pile


def photo_path(instance, filename):
    # The server chooses the name; whatever the phone called the file is ignored.
    return f"weight_photos/{instance.taken_at:%Y/%m}/{instance.pk}.jpg"


class Subject(models.TextChoices):
    STACK = "stack", _("A stack")
    LOAD = "load", _("A loaded vehicle")


class Source(models.TextChoices):
    YARD = "yard", _("Yard app")
    MITRA = "mitra", _("Mitra app")


class VehicleType(models.TextChoices):
    TROLLEY = "tractor_trolley", _("Tractor trolley")
    TRUCK = "truck", _("Truck")
    MINI_TRUCK = "mini_truck", _("Mini truck or pickup")
    OTHER = "other", _("Other")


class WeightPhoto(BaseModel):
    code = models.CharField(max_length=20, unique=True, editable=False)
    subject = models.CharField(max_length=10, choices=Subject.choices)
    source = models.CharField(max_length=10, choices=Source.choices, editable=False)
    pile = models.ForeignKey(Pile, on_delete=models.PROTECT, null=True, blank=True, related_name="weight_photos")
    place_note = models.CharField(max_length=120, blank=True, help_text="Where it is, if it is not a pile in a yard")
    vehicle_type = models.CharField(max_length=20, choices=VehicleType.choices, blank=True)
    vehicle_ref = models.CharField(max_length=50, blank=True, help_text="Vehicle number or driver")
    taken_at = models.DateTimeField(default=timezone.now)
    taken_by = models.CharField(max_length=200, blank=True)
    taken_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+", editable=False
    )
    image = models.ImageField(upload_to=photo_path, max_length=200, editable=False)
    sha256 = models.CharField(max_length=64, db_index=True, editable=False)
    width = models.PositiveIntegerField(editable=False)
    height = models.PositiveIntegerField(editable=False)
    bale_count = models.PositiveIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(100000)], help_text="Bales visible or loaded, if counted"
    )
    reference_note = models.CharField(
        max_length=200, blank=True, help_text="Anything in the photo that shows size, such as a 2 m pole or a person"
    )
    notes = models.TextField(blank=True)
    # The true weight, from a weighbridge slip. Empty until someone enters it.
    weighed_tonnes = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(Decimal("0.001"))]
    )
    slip_number = models.CharField(max_length=50, blank=True)
    weighed_on = models.DateField(null=True, blank=True)
    ledger_seq = models.PositiveBigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-taken_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(weighed_tonnes__isnull=True) | Q(weighed_tonnes__gt=0), name="weightphoto_weight_positive"
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.get_subject_display()}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_code("weight_photo", "WPH")
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.subject == Subject.STACK and (self.vehicle_type or self.vehicle_ref):
            raise ValidationError(_("A stack has no vehicle."))
        if self.subject == Subject.LOAD and self.pile_id:
            raise ValidationError(_("A loaded vehicle is not in a pile."))
        if self.weighed_tonnes is not None and self.weighed_on is None:
            raise ValidationError(_("Enter the date the load was weighed."))

    @property
    def has_weight(self):
        return self.weighed_tonnes is not None
