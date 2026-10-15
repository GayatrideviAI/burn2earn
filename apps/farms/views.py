from datetime import date

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from apps.reference.models import Season
from apps.territory.models import Region

from .estimates import supply_estimate


@staff_member_required
def supply_report(request):
    """Admin-only report: estimated biomass by GeoCell, Grid and crop."""
    try:
        year = int(request.GET.get("year") or date.today().year)
    except ValueError:
        year = date.today().year
    season = Season.objects.filter(pk=request.GET.get("season")).first() if request.GET.get("season") else None
    region = Region.objects.filter(pk=request.GET.get("region")).first() if request.GET.get("region") else None
    context = {
        **admin.site.each_context(request),
        "title": "Biomass supply estimate",
        "estimate": supply_estimate(year, season=season, region=region),
        "year": year,
        "season": season,
        "region": region,
        "seasons": Season.objects.all(),
        "regions": Region.objects.all(),
    }
    return render(request, "farms/supply_report.html", context)
