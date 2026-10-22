"""JSON endpoints for the offline yard app.

`bootstrap` gives the phone the operator's piles, batches, latest readings and open alerts so they
can be read with no signal. `sync` takes the changes made while offline and applies them one by one.
Every change carries an id chosen on the phone and used as the record's own id, so sending a change
twice never saves it twice. The risk level is worked out on the server; the phone shows the last one
it downloaded, raised on the phone if a new temperature is higher.
"""
import json
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import Status
from apps.customers import services as stock
from apps.customers.models import Batch, CountMethod, Pile, StockCount, QualityObservation

from . import risk, services
from .access import yard_required
from .forms import CountForm, HeatForm, InspectionForm, MoistureForm, SizeForm
from .models import HeatReading, PileInspection, RiskAlert

MAX_OPERATIONS = 200


class OperationError(Exception):
    """A change that cannot be applied; the message is shown to the operator."""


def _errors(form):
    return "; ".join(
        f"{(form.fields[name].label if name in form.fields else name)}: {' '.join(str(e) for e in errs)}"
        if name != "__all__"
        else " ".join(errs)
        for name, errs in form.errors.items()
    )


def _uuid(value, what):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise OperationError(_("%(what)s is not a valid id.") % {"what": what})


def _when(value, what):
    """A moment sent by the phone. Missing means now; anything unreadable is refused."""
    if not value:
        return timezone.now()
    moment = parse_datetime(str(value))
    if moment is None or timezone.is_naive(moment):
        raise OperationError(_("%(what)s is not a valid date and time.") % {"what": what})
    return moment


def _pile_for(operator, value):
    try:
        return Pile.objects.get(pk=_uuid(value, _("The pile")), yard__in=operator.yards.all(), status=Status.ACTIVE)
    except Pile.DoesNotExist:
        raise OperationError(_("The pile was not found in your yards."))


def _batch_for(operator, value):
    try:
        return Batch.objects.get(pk=_uuid(value, _("The batch")), pile__yard__in=operator.yards.all(), status=Status.ACTIVE)
    except Batch.DoesNotExist:
        raise OperationError(_("The batch was not found in your yards."))


def _assessment_row(a, now):
    stale = a.latest is None or (now - a.latest.taken_at).days > settings.YARD_READING_MAX_AGE_DAYS
    return {
        "level": a.level,
        "stale": stale,
        "reasons": [r.text for r in a.reasons],
        "rise_per_day": a.rise_per_day,
        "projection": a.projection,
    }


@yard_required
@require_GET
def bootstrap(request):
    operator = request.operator
    now = timezone.now()
    piles = Pile.objects.filter(yard__in=request.yards, status=Status.ACTIVE).select_related("yard").order_by("yard__name", "label")
    rows = []
    for pile in piles:
        a = risk.assess(pile, now)
        if not a.has_stock:
            continue
        readings = HeatReading.objects.filter(pile=pile, status=Status.ACTIVE, taken_at__lte=now).order_by("-taken_at")[:6]
        inspection = PileInspection.objects.filter(pile=pile, status=Status.ACTIVE).order_by("-inspected_at").first()
        rows.append(
            {
                "id": str(pile.pk),
                "label": pile.label,
                "yard_id": str(pile.yard_id),
                "yard": pile.yard.name,
                "length_m": str(pile.length_m) if pile.length_m is not None else "",
                "width_m": str(pile.width_m) if pile.width_m is not None else "",
                "height_m": str(pile.height_m) if pile.height_m is not None else "",
                "cover_type": pile.cover_type,
                "assessment": _assessment_row(a, now),
                "batches": [
                    {"id": str(b.pk), "code": b.code, "book_tonnes": str(stock.book_tonnes(b)), "received_on": b.received_on.isoformat()}
                    for b in a.batches
                ],
                "readings": [
                    {"at": r.taken_at.isoformat(), "temperature_c": str(r.temperature_c), "spot": r.spot} for r in readings
                ],
                "last_inspection": None
                if inspection is None
                else {
                    "at": inspection.inspected_at.isoformat(),
                    "looks_wet": inspection.looks_wet,
                    "mould": inspection.mould,
                    "steam_or_smell": inspection.steam_or_smell,
                    "cover_in_place": inspection.cover_in_place,
                },
            }
        )
    alerts = [
        {
            "id": str(a.pk),
            "code": a.code,
            "pile_id": str(a.pile_id),
            "pile": a.pile.label,
            "yard": a.pile.yard.name,
            "level": a.level,
            "reasons": a.reasons,
            "raised_at": a.raised_at.isoformat(),
            "acknowledged": a.acknowledged_at is not None,
        }
        for a in services.open_alerts(request.yards).order_by("-raised_at")
    ]
    return JsonResponse(
        {
            "server_time": now.isoformat(),
            "operator": {"name": operator.name},
            "thresholds": {
                "warm": settings.YARD_HEAT_WARM_C,
                "watch": settings.YARD_HEAT_WATCH_C,
                "act": settings.YARD_HEAT_ACT_C,
                "emergency": settings.YARD_HEAT_EMERGENCY_C,
            },
            "count_methods": [{"id": value, "name": str(label)} for value, label in CountMethod.choices],
            "piles": rows,
            "alerts": alerts,
        }
    )


# ---- one handler per kind of change -------------------------------------------------------


def _heat(operator, op_id, data):
    pile = _pile_for(operator, data.get("pile_id"))
    form = HeatForm(data)
    if not form.is_valid():
        raise OperationError(_errors(form))
    c = form.cleaned_data
    try:
        services.record_heat(
            pile, c["temperature_c"], taken_at=_when(data.get("taken_at"), _("The reading time")), spot=c["spot"],
            depth_cm=c["depth_cm"], taken_by=operator.name, pk=op_id,
        )
    except ValidationError as error:
        raise OperationError("; ".join(error.messages))
    return "ok", ""


def _inspection(operator, op_id, data):
    pile = _pile_for(operator, data.get("pile_id"))
    flags = {name: bool(data.get(name)) for name in ("looks_wet", "mould", "steam_or_smell")}
    form = InspectionForm({**flags, "cover_in_place": "on" if data.get("cover_in_place", True) else "", "notes": data.get("notes", "")})
    if not form.is_valid():
        raise OperationError(_errors(form))
    c = form.cleaned_data
    inspected_at = _when(data.get("inspected_at"), _("The inspection time"))
    if inspected_at > timezone.now() + services.FUTURE_GRACE:
        raise OperationError(_("The reading time cannot be in the future."))
    try:
        services.record_inspection(
            pile, looks_wet=c["looks_wet"], mould=c["mould"], steam_or_smell=c["steam_or_smell"],
            cover_in_place=c["cover_in_place"], notes=c["notes"], inspected_at=inspected_at, inspected_by=operator.name, pk=op_id,
        )
    except ValidationError as error:
        raise OperationError("; ".join(error.messages))
    return "ok", ""


def _day(value, what):
    if not value:
        return timezone.localdate()
    day = parse_date(str(value))
    if day is None:
        raise OperationError(_("%(what)s is not a valid date.") % {"what": what})
    if day > timezone.localdate() + services.FUTURE_GRACE_DAYS:
        raise OperationError(_("The date cannot be in the future."))
    return day


def _count(operator, op_id, data):
    batch = _batch_for(operator, data.get("batch_id"))
    form = CountForm({"batch": batch.pk, "tonnes": data.get("tonnes"), "method": data.get("method")}, batches=Batch.objects.filter(pk=batch.pk))
    if not form.is_valid():
        raise OperationError(_errors(form))
    c = form.cleaned_data
    try:
        services.record_count(batch, c["tonnes"], c["method"], counted_by=operator.name, counted_on=_day(data.get("counted_on"), _("The count date")), pk=op_id)
    except ValidationError as error:
        raise OperationError("; ".join(error.messages))
    return "ok", ""


def _moisture(operator, op_id, data):
    batch = _batch_for(operator, data.get("batch_id"))
    form = MoistureForm(
        {"batch": batch.pk, "percent": data.get("percent"), "method": data.get("method") or "handheld meter"},
        batches=Batch.objects.filter(pk=batch.pk),
    )
    if not form.is_valid():
        raise OperationError(_errors(form))
    c = form.cleaned_data
    try:
        services.record_moisture(
            batch, c["percent"], method=c["method"], tested_by=operator.name,
            observed_at=_when(data.get("observed_at"), _("The reading time")), pk=op_id,
        )
    except ValidationError as error:
        raise OperationError("; ".join(error.messages))
    return "ok", ""


def _size(operator, op_id, data):
    pile = _pile_for(operator, data.get("pile_id"))
    form = SizeForm(data)
    if not form.is_valid():
        raise OperationError(_errors(form))
    c = form.cleaned_data
    try:
        # Only what was filled in changes; a blank box never wipes a saved measurement.
        services.update_pile_size(
            pile, length_m=c["length_m"], width_m=c["width_m"], height_m=c["height_m"],
            cover_type=c["cover_type"] if c["cover_type"] else None,
        )
    except ValidationError as error:
        raise OperationError("; ".join(error.messages))
    return "ok", ""


def _acknowledge(operator, op_id, data):
    try:
        alert = RiskAlert.objects.select_related("pile").get(
            pk=_uuid(data.get("alert_id"), _("The alert")), pile__yard__in=operator.yards.all(), status=Status.ACTIVE
        )
    except RiskAlert.DoesNotExist:
        raise OperationError(_("The alert was not found in your yards."))
    if alert.acknowledged_at is not None:
        return "exists", ""
    if alert.resolved_at is not None:
        return "flagged", _("This alert had already closed before your acknowledgement arrived.")
    services.acknowledge(alert, operator.user, note=str(data.get("note") or "").strip()[:500], at=_when(data.get("acknowledged_at"), _("The time")))
    return "ok", ""


# type -> (model to look for a repeat in, handler). Changes that are naturally repeatable have no model.
HANDLERS = {
    "heat.create": (HeatReading, _heat),
    "inspection.create": (PileInspection, _inspection),
    "count.create": (StockCount, _count),
    "moisture.create": (QualityObservation, _moisture),
    "size.update": (None, _size),
    "alert.acknowledge": (None, _acknowledge),
}


def _owned(operator, model, existing):
    """A saved record with this id must belong to this operator's yards, or the id is someone else's."""
    yards = operator.yards.all()
    if model in (HeatReading, PileInspection):
        return existing.pile.yard_id in {y.pk for y in yards}
    return existing.batch.pile.yard_id in {y.pk for y in yards}


def apply_operation(operator, operation):
    """Apply one change. Returns {"id", "status", "message"}; status is ok, exists, flagged or error."""
    raw_id = operation.get("id")
    try:
        op_id = _uuid(raw_id, _("The change id"))
        handler = HANDLERS.get(operation.get("type"))
        if handler is None:
            raise OperationError(_("Unknown kind of change."))
        model, function = handler
        data = operation.get("data")
        if not isinstance(data, dict):
            raise OperationError(_("The change has no data."))
        if model is not None:
            existing = model.objects.filter(pk=op_id).first()
            if existing is not None:
                if not _owned(operator, model, existing):
                    raise OperationError(_("This id is already used by someone else's record."))
                return {"id": str(op_id), "status": "exists", "message": ""}
        with transaction.atomic():
            status, message = function(operator, op_id, data)
        return {"id": str(op_id), "status": status, "message": message}
    except OperationError as error:
        return {"id": str(raw_id), "status": "error", "message": str(error)}
    except (IntegrityError, DataError):
        return {
            "id": str(raw_id),
            "status": "error",
            "message": _("The record could not be saved because some details are not allowed."),
        }


@yard_required
@require_POST
def sync(request):
    try:
        body = json.loads(request.body or b"{}")
        operations = body["operations"]
        if not isinstance(operations, list) or len(operations) > MAX_OPERATIONS:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": _("Send up to %(max)s changes as a list.") % {"max": MAX_OPERATIONS}}, status=400)
    results = [apply_operation(request.operator, op if isinstance(op, dict) else {}) for op in operations]
    return JsonResponse({"results": results, "server_time": timezone.now().isoformat()})
