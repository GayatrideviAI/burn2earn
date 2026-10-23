"""JSON endpoints for the offline Mitra app.

`bootstrap` gives the phone everything it needs to work without a signal. `sync` takes the
changes made while offline and applies them one by one. Every change carries an id chosen on
the phone and used as the record's own id, so sending a change twice never creates it twice.
"""

import json
import uuid
from django.core.exceptions import ValidationError
from django.contrib.gis.geos import Point
from django.db import DataError, IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import Status
from apps.farms.models import Farmer, FarmPlot, PlotSeason
from apps.farms.services import possible_duplicates, register_farmer
from apps.customers.models import Pile
from apps.geography.models import Village
from apps.operations.models import CollectionRecord, ProcessedOutput
from apps.operations.services import NoGridAssigned, log_collection, submit_output
from apps.reference.models import BiomassType, Crop, Product, Season

from apps.weightphotos import api as photo_api
from apps.weightphotos.models import Source

from .access import farmers_visible_to
from .forms import CollectionForm, FarmerForm, OutputForm, PlotForm, SeasonForm
from .access import mitra_required
from .views import _villages_for

MAX_OPERATIONS = 200


class OperationError(Exception):
    """A change that cannot be applied; the message is shown to the Mitra."""


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


@mitra_required
@require_GET
def bootstrap(request):
    mitra = request.mitra
    grid = mitra.current_grid
    villages = _villages_for(mitra)
    if villages is None:
        villages = Village.objects.all()
    farmers = (
        farmers_visible_to(mitra)
        .filter(status=Status.ACTIVE)
        .select_related("village")
        .prefetch_related("plots__geocell", "plots__seasons__crop", "plots__seasons__season")
    )
    data = {
        "server_time": timezone.now().isoformat(),
        "mitra": {"code": mitra.code, "name": mitra.name},
        "grid": {"code": grid.code} if grid else None,
        "villages": [{"id": str(v.pk), "name": v.name} for v in villages.order_by("name")],
        "biomass_types": [
            {"id": str(b.pk), "name": b.name} for b in BiomassType.objects.filter(status=Status.ACTIVE)
        ],
        "crops": [{"id": str(c.pk), "name": c.name} for c in Crop.objects.filter(status=Status.ACTIVE)],
        "seasons": [{"id": str(s.pk), "name": s.name} for s in Season.objects.filter(status=Status.ACTIVE)],
        "products": [
            {"id": str(p.pk), "name": str(p)}
            for p in Product.objects.filter(status=Status.ACTIVE, form="processed")
        ],
        "photos_to_weigh": photo_api.to_weigh(request.user),
        "farmers": [
            {
                "id": str(f.pk),
                "code": f.code,
                "name": f.name,
                "mobile": f.mobile,
                "village_id": str(f.village_id),
                "village": f.village.name,
                "plots": [
                    {
                        "id": str(p.pk),
                        "area_acres": str(p.area_acres),
                        "cell": p.geocell.code if p.geocell else None,
                        "seasons": [
                            {
                                "id": str(s.pk),
                                "season": s.season.name,
                                "year": s.year,
                                "crop": s.crop.name,
                                "variety": s.variety,
                            }
                            for s in p.seasons.all()
                            if s.status == Status.ACTIVE
                        ],
                    }
                    for p in f.plots.all()
                    if p.status == Status.ACTIVE
                ],
            }
            for f in farmers
        ],
    }
    return JsonResponse(data)


# ---- one handler per kind of change -------------------------------------------------------


def _farmer_create(mitra, op_id, data):
    form = FarmerForm({**data, "village": data.get("village_id"), "consent": "on" if data.get("consent") else ""}, villages=_villages_for(mitra))
    if not form.is_valid():
        raise OperationError(_errors(form))
    cleaned = form.cleaned_data
    consented_at = parse_datetime(data.get("consented_at") or "")
    if consented_at and consented_at > timezone.now():
        consented_at = None
    duplicates = list(possible_duplicates(cleaned["mobile"]).values_list("code", flat=True)[:5])
    register_farmer(
        mitra=mitra,
        name=cleaned["name"],
        mobile=cleaned["mobile"],
        village=cleaned["village"],
        preferred_language=cleaned["preferred_language"],
        pk=op_id,
        needs_review=bool(duplicates),
        consented_at=consented_at,
    )
    if duplicates:
        return "flagged", _("Saved. Another farmer has this mobile number (%(codes)s); an Admin will review.") % {"codes": ", ".join(duplicates)}
    return "ok", ""


def _farmer_for(mitra, value):
    try:
        return farmers_visible_to(mitra).get(pk=_uuid(value, _("The farmer")))
    except Farmer.DoesNotExist:
        raise OperationError(_("The farmer was not found. Their registration may have failed."))


def _plot_create(mitra, op_id, data):
    farmer = _farmer_for(mitra, data.get("farmer_id"))
    form = PlotForm(data)
    if not form.is_valid():
        raise OperationError(_errors(form))
    c = form.cleaned_data
    plot = FarmPlot.objects.create(
        id=op_id,
        farmer=farmer,
        location=Point(float(c["longitude"]), float(c["latitude"]), srid=4326),
        area_acres=c["area_acres"],
        ownership=c["ownership"],
        irrigation=c["irrigation"],
    )
    if plot.outside_geocells:
        return "flagged", "Saved, but the plot is outside every GeoCell. An Admin will check the location."
    return "ok", ""


def _season_create(mitra, op_id, data):
    try:
        plot = FarmPlot.objects.get(pk=_uuid(data.get("plot_id"), _("The plot")))
    except FarmPlot.DoesNotExist:
        raise OperationError(_("The plot was not found. Its creation may have failed."))
    _farmer_for(mitra, plot.farmer_id)
    form = SeasonForm({**data, "season": data.get("season_id"), "crop": data.get("crop_id")})
    if not form.is_valid():
        raise OperationError(_errors(form))
    c = form.cleaned_data
    if PlotSeason.objects.filter(plot=plot, season=c["season"], year=c["year"], crop=c["crop"]).exists():
        raise OperationError(_("This crop is already recorded for that season and year."))
    PlotSeason.objects.create(id=op_id, plot=plot, **c)
    return "ok", ""


def _collection_create(mitra, op_id, data):
    farmer = _farmer_for(mitra, data.get("farmer_id"))
    form = CollectionForm(
        {**data, "plot": data.get("plot_id") or "", "biomass_type": data.get("biomass_type_id")}, farmer=farmer
    )
    if not form.is_valid():
        raise OperationError(_errors(form))
    try:
        log_collection(mitra=mitra, farmer=farmer, pk=op_id, **form.cleaned_data)
    except NoGridAssigned:
        raise OperationError(_("You have no Grid assigned yet, so a pickup cannot be recorded."))
    except ValidationError as error:
        raise OperationError("; ".join(error.messages))
    return "ok", ""


def _output_create(mitra, op_id, data):
    form = OutputForm({**data, "product": data.get("product_id")})
    if not form.is_valid():
        raise OperationError(_errors(form))
    try:
        submit_output(mitra=mitra, pk=op_id, **form.cleaned_data)
    except NoGridAssigned:
        raise OperationError(_("You have no Grid assigned yet, so output cannot be reported."))
    except ValidationError as error:
        raise OperationError("; ".join(error.messages))
    return "ok", ""


def _photo_weigh(mitra, op_id, data):
    try:
        return photo_api.weigh_operation(mitra.user, op_id, data, may_see=lambda photo: False)
    except LookupError as error:
        raise OperationError(str(error))
    except ValidationError as error:
        raise OperationError("; ".join(error.messages))


HANDLERS = {
    "farmer.create": (Farmer, "registered_by_mitra", _farmer_create),
    "plot.create": (FarmPlot, None, _plot_create),
    "season.create": (PlotSeason, None, _season_create),
    "collection.create": (CollectionRecord, "mitra", _collection_create),
    "output.create": (ProcessedOutput, "mitra", _output_create),
    "photo.weigh": (None, None, _photo_weigh),
}


def _already_saved(mitra, model, owner_field, op_id):
    """True if this change was applied before (the phone is retrying). False if new.

    A record with this id that belongs to someone else is an error, never a match.
    """
    existing = model.objects.filter(pk=op_id).first()
    if existing is None:
        return False
    if owner_field and getattr(existing, f"{owner_field}_id") != mitra.pk:
        raise OperationError(_("This id is already used by someone else's record."))
    if model is FarmPlot and not farmers_visible_to(mitra).filter(pk=existing.farmer_id).exists():
        raise OperationError(_("This id is already used by someone else's record."))
    if model is PlotSeason and not farmers_visible_to(mitra).filter(pk=existing.plot.farmer_id).exists():
        raise OperationError(_("This id is already used by someone else's record."))
    return True


def apply_operation(mitra, operation):
    """Apply one change. Returns {"id", "status", "message"}; status is ok, exists, flagged or error."""
    op_id = operation.get("id")
    try:
        op_id = _uuid(op_id, _("The change id"))
        handler = HANDLERS.get(operation.get("type"))
        if handler is None:
            raise OperationError(_("Unknown kind of change."))
        model, owner_field, function = handler
        data = operation.get("data")
        if not isinstance(data, dict):
            raise OperationError(_("The change has no data."))
        if model is not None and _already_saved(mitra, model, owner_field, op_id):
            return {"id": str(op_id), "status": "exists", "message": ""}
        with transaction.atomic():
            status, message = function(mitra, op_id, data)
        return {"id": str(op_id), "status": status, "message": message}
    except OperationError as error:
        return {"id": str(operation.get("id")), "status": "error", "message": str(error)}
    except (IntegrityError, DataError):
        return {
            "id": str(operation.get("id")),
            "status": "error",
            "message": _("The record could not be saved because some details are not allowed."),
        }


@mitra_required
@require_POST
def sync(request):
    try:
        body = json.loads(request.body or b"{}")
        operations = body["operations"]
        if not isinstance(operations, list) or len(operations) > MAX_OPERATIONS:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": _("Send up to %(max)s changes as a list.") % {"max": MAX_OPERATIONS}}, status=400)
    results = [apply_operation(request.mitra, op if isinstance(op, dict) else {}) for op in operations]
    return JsonResponse({"results": results, "server_time": timezone.now().isoformat()})


@mitra_required
@require_POST
def photo_upload(request):
    return photo_api.handle_upload(request, source=Source.MITRA, taken_by=request.mitra.name, piles=Pile.objects.none())
