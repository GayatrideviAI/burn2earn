from pathlib import Path

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from apps.core.models import Status
from apps.customers import services as stock
from apps.customers.models import Batch, Pile
from apps.field.jscatalog import PHOTOS_JS, js_catalog_json

from . import risk, services
from .access import yard_required
from .forms import CountForm, HeatForm, InspectionForm, MoistureForm, SizeForm
APP_JS = Path(__file__).parent / "static" / "yardops" / "app.js"

from .models import HeatReading, PileInspection, RiskAlert


def _piles_of(yards):
    return Pile.objects.filter(yard__in=yards, status=Status.ACTIVE).select_related("yard")


@yard_required
def home(request):
    now = timezone.now()
    alerts = list(services.open_alerts(request.yards).order_by("-raised_at"))
    for a in alerts:
        a.is_overdue = services.overdue(a, now)
    yards = []
    for yard in request.yards:
        rows = [a for a in risk.assess_piles(_piles_of([yard]), now) if a.has_stock]
        rows.sort(key=lambda a: (-a.level, a.pile.label))
        for a in rows:
            a.tonnes = sum(stock.book_tonnes(b) for b in a.batches)
        yards.append({"yard": yard, "rows": rows})
    return render(request, "yardops/home.html", {"operator": request.operator, "alerts": alerts, "yards": yards})


@yard_required
def pile_detail(request, pk):
    pile = get_object_or_404(_piles_of(request.yards), pk=pk)
    batches = Batch.objects.filter(pile=pile, status=Status.ACTIVE)
    by = request.operator.name
    forms = {
        "heat": HeatForm(prefix="heat"),
        "inspect": InspectionForm(prefix="inspect"),
        "count": CountForm(prefix="count", batches=batches),
        "moisture": MoistureForm(prefix="moisture", batches=batches),
        "size": SizeForm(prefix="size", initial={"length_m": pile.length_m, "width_m": pile.width_m, "height_m": pile.height_m, "cover_type": pile.cover_type}),
    }
    if request.method == "POST":
        action = request.POST.get("action")
        if action in forms:
            extra = {"batches": batches} if action in ("count", "moisture") else {}
            form = {"heat": HeatForm, "inspect": InspectionForm, "count": CountForm, "moisture": MoistureForm, "size": SizeForm}[action](
                request.POST, prefix=action, **extra
            )
            forms[action] = form
            if form.is_valid():
                d = form.cleaned_data
                try:
                    if action == "heat":
                        services.record_heat(pile, d["temperature_c"], spot=d["spot"], depth_cm=d["depth_cm"], taken_by=by)
                        messages.success(request, _("Temperature saved."))
                    elif action == "inspect":
                        services.record_inspection(
                            pile, looks_wet=d["looks_wet"], mould=d["mould"], steam_or_smell=d["steam_or_smell"],
                            cover_in_place=d["cover_in_place"], notes=d["notes"], inspected_by=by,
                        )
                        messages.success(request, _("Inspection saved."))
                    elif action == "count":
                        services.record_count(d["batch"], d["tonnes"], d["method"], counted_by=by)
                        messages.success(request, _("Count saved."))
                    elif action == "moisture":
                        services.record_moisture(d["batch"], d["percent"], method=d["method"], tested_by=by)
                        messages.success(request, _("Moisture saved."))
                    else:
                        services.update_pile_size(pile, length_m=d["length_m"], width_m=d["width_m"], height_m=d["height_m"], cover_type=d["cover_type"])
                        messages.success(request, _("Pile details saved."))
                except ValidationError as error:
                    form.add_error(None, "; ".join(error.messages))
                else:
                    return redirect("yardops:pile", pk=pile.pk)
    now = timezone.now()
    assessment = risk.assess(pile, now)
    return render(
        request,
        "yardops/pile.html",
        {
            "operator": request.operator, "pile": pile, "a": assessment, "forms": forms,
            "readings": HeatReading.objects.filter(pile=pile, status=Status.ACTIVE)[:10],
            "inspections": PileInspection.objects.filter(pile=pile, status=Status.ACTIVE)[:5],
            "batches": [(b, stock.book_tonnes(b)) for b in batches],
            "alerts": RiskAlert.objects.filter(pile=pile, status=Status.ACTIVE)[:5],
        },
    )


@yard_required
@require_POST
def acknowledge(request, pk):
    alert = get_object_or_404(services.open_alerts(request.yards), pk=pk)
    services.acknowledge(alert, request.user, note=request.POST.get("note", "").strip())
    messages.success(request, _("Alert acknowledged."))
    return redirect("yardops:home")


@yard_required
@ensure_csrf_cookie
def offline_app(request):
    """The page that installs the offline app. After the first visit it opens without a signal."""
    return render(request, "yardops/app.html", {"catalog_json": js_catalog_json((APP_JS, PHOTOS_JS))})


def service_worker(request):
    response = render(request, "yardops/sw.js", content_type="text/javascript")
    response["Service-Worker-Allowed"] = "/yard/"
    response["Cache-Control"] = "no-cache"
    return response


def manifest(request):
    return render(request, "yardops/manifest.webmanifest", content_type="application/manifest+json")
