from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.farms.estimates import supply_estimate
from apps.farms.models import Farmer, FarmPlot, PlotSeason
from apps.farms.services import register_farmer
from apps.geography.models import Village

from .access import farmers_visible_to, mitra_required
from apps.operations.models import CollectionRecord, ProcessedOutput
from apps.operations.services import NoGridAssigned, log_collection, submit_output, tally

from .forms import CollectionForm, FarmerForm, OutputForm, PlotForm, SeasonForm


def _villages_for(mitra):
    """Villages in the panchayats the Mitra covers; all villages if they have no cells yet."""
    cells = mitra.geocells
    villages = Village.objects.filter(panchayat__geocells__in=cells).distinct() if cells.exists() else None
    return villages


@mitra_required
def dashboard(request):
    mitra = request.mitra
    farmers = farmers_visible_to(mitra)
    return render(
        request,
        "field/dashboard.html",
        {
            "mitra": mitra,
            "grid": mitra.current_grid,
            "farmer_count": farmers.count(),
            "plot_count": FarmPlot.objects.filter(farmer__in=farmers).count(),
            "recent": farmers.order_by("-created_at")[:5],
            "year": date.today().year,
            "stock": tally(grid=mitra.current_grid) if mitra.current_grid else None,
            "estimate": supply_estimate(date.today().year, grid=mitra.current_grid)
            if mitra.current_grid
            else None,
        },
    )


@mitra_required
def farmer_list(request):
    query = request.GET.get("q", "").strip()
    farmers = farmers_visible_to(request.mitra).select_related("village")
    if query:
        farmers = farmers.filter(
            Q(name__icontains=query) | Q(mobile__icontains=query) | Q(code__icontains=query)
        )
    farmers = farmers.order_by("-created_at")[:200]
    return render(request, "field/farmer_list.html", {"farmers": farmers, "query": query})


@mitra_required
def farmer_new(request):
    mitra = request.mitra
    villages = _villages_for(mitra)
    form = FarmerForm(request.POST or None, villages=villages)
    duplicates = []
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        duplicates = list(Farmer.objects.filter(mobile=data["mobile"], status="active")[:5])
        if duplicates and not request.POST.get("confirm_duplicate"):
            return render(
                request, "field/farmer_form.html", {"form": form, "duplicates": duplicates}
            )
        farmer = register_farmer(
            mitra=mitra,
            name=data["name"],
            mobile=data["mobile"],
            village=data["village"],
            preferred_language=data["preferred_language"],
        )
        messages.success(request, f"Registered {farmer.name} ({farmer.code}). Now add their land.")
        return redirect("field:farmer_detail", pk=farmer.pk)
    return render(request, "field/farmer_form.html", {"form": form, "duplicates": duplicates})


def _get_farmer(request, pk):
    return get_object_or_404(farmers_visible_to(request.mitra), pk=pk)


@mitra_required
def farmer_detail(request, pk):
    farmer = _get_farmer(request, pk)
    plots = farmer.plots.select_related("geocell").prefetch_related("seasons__crop", "seasons__season")
    return render(request, "field/farmer_detail.html", {"farmer": farmer, "plots": plots})


@mitra_required
def plot_new(request, pk):
    farmer = _get_farmer(request, pk)
    form = PlotForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        plot = FarmPlot.objects.create(
            farmer=farmer,
            location=Point(float(data["longitude"]), float(data["latitude"]), srid=4326),
            area_acres=data["area_acres"],
            ownership=data["ownership"],
            irrigation=data["irrigation"],
        )
        if plot.outside_geocells:
            messages.warning(
                request,
                "Plot saved, but it is outside every GeoCell. An Admin will check the location.",
            )
        elif plot.panchayat_differs_from_village:
            messages.info(request, "Plot saved. It is in a different panchayat from the farmer's village.")
        else:
            messages.success(request, "Plot saved.")
        return redirect("field:farmer_detail", pk=farmer.pk)
    return render(request, "field/plot_form.html", {"form": form, "farmer": farmer})


@mitra_required
def season_new(request, pk, plot_pk):
    farmer = _get_farmer(request, pk)
    plot = get_object_or_404(farmer.plots, pk=plot_pk)
    form = SeasonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                PlotSeason.objects.create(plot=plot, **data)
        except IntegrityError:
            form.add_error(None, "This crop is already recorded for that season and year.")
        else:
            messages.success(request, "Crop saved.")
            return redirect("field:farmer_detail", pk=farmer.pk)
    return render(request, "field/season_form.html", {"form": form, "farmer": farmer, "plot": plot})


@mitra_required
def collection_new(request, pk):
    farmer = _get_farmer(request, pk)
    form = CollectionForm(request.POST or None, farmer=farmer)
    if request.method == "POST" and form.is_valid():
        try:
            record = log_collection(mitra=request.mitra, farmer=farmer, **form.cleaned_data)
        except NoGridAssigned:
            form.add_error(None, "You have no Grid assigned yet, so a pickup cannot be recorded.")
        except ValidationError as error:
            form.add_error(None, "; ".join(error.messages))
        else:
            messages.success(request, f"Saved {record.quantity_tonnes} tonnes ({record.code}).")
            return redirect("field:stock")
    return render(request, "field/collection_form.html", {"form": form, "farmer": farmer})


@mitra_required
def output_new(request):
    form = OutputForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            output = submit_output(mitra=request.mitra, **form.cleaned_data)
        except NoGridAssigned:
            form.add_error(None, "You have no Grid assigned yet, so output cannot be reported.")
        except ValidationError as error:
            form.add_error(None, "; ".join(error.messages))
        else:
            messages.success(request, f"Reported {output.quantity_tonnes} tonnes ({output.code}).")
            return redirect("field:stock")
    return render(request, "field/output_form.html", {"form": form})


@mitra_required
def stock(request):
    grid = request.mitra.current_grid
    if grid is None:
        return render(request, "field/stock.html", {"grid": None})
    year = date.today().year
    this_year = tally(grid=grid, year=year)
    expected = supply_estimate(year, grid=grid).total.tonnes
    return render(
        request,
        "field/stock.html",
        {
            "grid": grid,
            "all_time": tally(grid=grid),
            "this_year": this_year,
            "year": year,
            "expected": expected,
            "share": (this_year.collected_tonnes / expected * 100).quantize(Decimal("1")) if expected else None,
            "recent_collections": CollectionRecord.objects.filter(grid=grid).select_related("farmer", "biomass_type")[:10],
            "recent_outputs": ProcessedOutput.objects.filter(grid=grid).select_related("product")[:10],
        },
    )
