"""Saving a weight photo and its weighbridge weight."""
import hashlib
import io
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ledger import chain

from .models import Source, Subject, WeightPhoto

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MIN_SIDE, MAX_SIDE = 320, 8000
FUTURE_GRACE = timedelta(minutes=5)  # phone clocks drift a little


def read_image(data):
    """Check the bytes really are a photo and return (jpeg bytes, width, height, sha256 of the original).

    Everything is saved as a JPEG with the orientation applied and no metadata, so a phone's
    location and camera details are never kept.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not data:
        raise ValidationError(_("No photo was sent."))
    if len(data) > settings.WEIGHT_PHOTO_MAX_BYTES:
        raise ValidationError(_("The photo is too large."))
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in ALLOWED_FORMATS:
            raise ValidationError(_("Send a JPEG, PNG or WEBP photo."))
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ValidationError(_("This file is not a photo."))
    image = ImageOps.exif_transpose(image).convert("RGB")
    if min(image.size) < MIN_SIDE or max(image.size) > MAX_SIDE:
        raise ValidationError(_("The photo should be between %(lo)s and %(hi)s pixels on each side.") % {"lo": MIN_SIDE, "hi": MAX_SIDE})
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue(), image.size[0], image.size[1], hashlib.sha256(data).hexdigest()


@transaction.atomic
def store_photo(*, pk, source, subject, data, taken_by="", taken_by_user=None, taken_at=None, pile=None, place_note="",
                vehicle_type="", vehicle_ref="", bale_count=None, reference_note="", notes="",
                weighed_tonnes=None, slip_number="", weighed_on=None):
    jpeg, width, height, digest = read_image(data)
    photo = WeightPhoto(
        id=pk, source=source, subject=subject, pile=pile, place_note=place_note, vehicle_type=vehicle_type,
        vehicle_ref=vehicle_ref, taken_at=taken_at or timezone.now(), taken_by=taken_by, taken_by_user=taken_by_user,
        sha256=digest, width=width, height=height, bale_count=bale_count, reference_note=reference_note, notes=notes,
        weighed_tonnes=weighed_tonnes, slip_number=slip_number, weighed_on=weighed_on,
    )
    if photo.taken_at > timezone.now() + FUTURE_GRACE:
        raise ValidationError(_("The photo time cannot be in the future."))
    if weighed_tonnes is not None and weighed_on is None:
        photo.weighed_on = timezone.localdate()
    photo.image.save(f"{pk}.jpg", ContentFile(jpeg), save=False)
    photo.full_clean(exclude=["created_by", "updated_by", "code"])
    photo.save()
    entry = chain.append(
        "weightphoto.captured",
        photo,
        {
            "photo": photo.code, "subject": subject, "source": source, "pile": str(pile) if pile else "",
            "sha256": digest, "taken_by": taken_by, "taken_at": photo.taken_at,
            "weighed_tonnes": weighed_tonnes, "slip_number": slip_number,
        },
    )
    WeightPhoto.objects.filter(pk=photo.pk).update(ledger_seq=entry.seq)
    photo.ledger_seq = entry.seq
    return photo


@transaction.atomic
def record_weight(photo, tonnes, *, slip_number="", weighed_on=None, by="", allow_change=False):
    """Attach the weighbridge weight. Returns True if it was saved, False if the same figure was already there.

    A different figure on a photo that already has one is refused, except for staff correcting it
    (`allow_change`), which is recorded in the ledger with the old and new figure.
    """
    tonnes = Decimal(tonnes)
    if tonnes <= 0:
        raise ValidationError(_("The weight must be above zero."))
    weighed_on = weighed_on or timezone.localdate()
    if weighed_on > timezone.localdate() + timedelta(days=1):
        raise ValidationError(_("The weighing date cannot be in the future."))
    photo = WeightPhoto.objects.select_for_update().get(pk=photo.pk)
    previous = photo.weighed_tonnes
    if previous is not None:
        if previous == tonnes and photo.slip_number == slip_number:
            return False
        if not allow_change:
            raise ValidationError(_("This photo already has a weighed figure. Ask Regenerix staff to correct it."))
    photo.weighed_tonnes, photo.slip_number, photo.weighed_on = tonnes, slip_number, weighed_on
    photo.full_clean(exclude=["created_by", "updated_by"])
    photo.save(update_fields=["weighed_tonnes", "slip_number", "weighed_on", "updated_at"])
    chain.append(
        "weightphoto.weighed", photo,
        {"photo": photo.code, "weighed_tonnes": tonnes, "previous": previous, "slip_number": slip_number,
         "weighed_on": weighed_on, "by": by},
    )
    return True


def coverage():
    """Photos collected so far and how many are ready for training (they have a weighed figure)."""
    rows = []
    for subject, label in Subject.choices:
        qs = WeightPhoto.objects.filter(subject=subject, status="active")
        total, ready = qs.count(), qs.filter(weighed_tonnes__isnull=False).count()
        rows.append({"subject": subject, "label": str(label), "photos": total, "weighed": ready,
                     "target": settings.WEIGHT_PHOTO_TARGET_PER_SUBJECT,
                     "enough": ready >= settings.WEIGHT_PHOTO_TARGET_PER_SUBJECT})
    return rows
