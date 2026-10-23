"""Photo upload for the offline Yard and Mitra apps.

A phone sends each photo on its own (multipart), after its photo id has been chosen on the phone,
and that id becomes the record's id, so a photo sent twice is only saved once. Adding the
weighbridge weight to a photo already sent goes through the apps' normal `photo.weigh` change.
"""
import uuid
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import Status

from . import services
from .models import Source, Subject, VehicleType, WeightPhoto


def _bad(message, status=400):
    return JsonResponse({"status": "error", "message": str(message)}, status=status)


def _decimal(value, what):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValidationError(_("%(what)s must be a number.") % {"what": what})


def handle_upload(request, *, source, taken_by, piles):
    """Shared by both apps. `piles` is the queryset of piles this person may photograph."""
    post = request.POST
    try:
        pk = uuid.UUID(post.get("id", ""))
    except ValueError:
        return _bad(_("The photo id is not valid."))
    existing = WeightPhoto.objects.filter(pk=pk).first()
    if existing is not None:
        if existing.taken_by_user_id != request.user.pk:
            return _bad(_("This id is already used by someone else's record."))
        return JsonResponse({"status": "exists", "message": "", "id": str(pk)})
    upload = request.FILES.get("image")
    if upload is None:
        return _bad(_("No photo was sent."))
    subject = post.get("subject", "")
    if subject not in Subject.values:
        return _bad(_("Choose whether the photo shows a stack or a loaded vehicle."))
    vehicle_type = post.get("vehicle_type", "")
    if vehicle_type and vehicle_type not in VehicleType.values:
        return _bad(_("Choose a vehicle type from the list."))
    pile = None
    if post.get("pile_id"):
        try:
            pile = piles.get(pk=uuid.UUID(post["pile_id"]), status=Status.ACTIVE)
        except (ValueError, piles.model.DoesNotExist):
            return _bad(_("The pile was not found in your yards."))
    taken_at = None
    if post.get("taken_at"):
        taken_at = parse_datetime(post["taken_at"])
        if taken_at is None or taken_at.tzinfo is None:
            return _bad(_("The photo time is not a valid date and time."))
    weighed_on = None
    if post.get("weighed_on"):
        weighed_on = parse_date(post["weighed_on"])
        if weighed_on is None:
            return _bad(_("The weighing date is not a valid date."))
    try:
        bale_count = post.get("bale_count") or None
        if bale_count is not None:
            if not bale_count.isdigit():
                raise ValidationError(_("The bale count must be a whole number."))
            bale_count = int(bale_count)
        photo = services.store_photo(
            pk=pk, source=source, subject=subject, data=upload.read(), taken_by=taken_by, taken_by_user=request.user,
            taken_at=taken_at, pile=pile, place_note=post.get("place_note", "")[:120], vehicle_type=vehicle_type,
            vehicle_ref=post.get("vehicle_ref", "")[:50], bale_count=bale_count,
            reference_note=post.get("reference_note", "")[:200], notes=post.get("notes", "")[:2000],
            weighed_tonnes=_decimal(post.get("weighed_tonnes"), _("The weight")),
            slip_number=post.get("slip_number", "")[:50], weighed_on=weighed_on,
        )
    except ValidationError as error:
        return _bad("; ".join(error.messages))
    return JsonResponse({"status": "ok", "message": "", "id": str(photo.pk)})


def weigh_operation(user, op_id, data, *, may_see):
    """The `photo.weigh` change both apps accept. Returns (status, message) like the other handlers."""
    from .models import WeightPhoto as Photo

    try:
        photo = Photo.objects.get(pk=uuid.UUID(str(data.get("photo_id"))), status=Status.ACTIVE)
    except (ValueError, Photo.DoesNotExist):
        raise LookupError(_("The photo was not found. It may not have reached the server yet."))
    if photo.taken_by_user_id != user.pk and not may_see(photo):
        raise LookupError(_("The photo was not found."))
    weighed_on = parse_date(str(data.get("weighed_on") or "")) if data.get("weighed_on") else None
    if data.get("weighed_on") and weighed_on is None:
        raise ValidationError(_("The weighing date is not a valid date."))
    saved = services.record_weight(
        photo, _decimal(data.get("weighed_tonnes"), _("The weight")) or Decimal("0"), slip_number=str(data.get("slip_number") or "")[:50],
        weighed_on=weighed_on, by=user.get_username(),
    )
    return ("ok" if saved else "exists"), ""


def to_weigh(user, limit=60):
    """This person's photos that still have no weighbridge weight, for the phone's list."""
    rows = WeightPhoto.objects.filter(taken_by_user=user, weighed_tonnes__isnull=True, status=Status.ACTIVE).order_by("-taken_at")[:limit]
    return [
        {
            "id": str(p.pk), "code": p.code, "subject": p.subject, "taken_at": p.taken_at.isoformat(),
            "label": str(p.pile) if p.pile_id else (p.vehicle_ref or p.place_note),
        }
        for p in rows
    ]


@require_GET
def image(request, pk):
    """A photo is shown only to staff and to the person who took it."""
    if not request.user.is_authenticated:
        raise Http404
    try:
        photo = WeightPhoto.objects.get(pk=pk)
    except WeightPhoto.DoesNotExist:
        raise Http404
    if not (request.user.is_staff or photo.taken_by_user_id == request.user.pk):
        raise Http404
    response = FileResponse(photo.image.open("rb"), content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=3600"
    return response
