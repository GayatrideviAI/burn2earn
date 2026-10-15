from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from apps.network.models import Grid, Hub

from .services import tally


@staff_member_required
def stock_report(request):
    """Admin-only: running tallies per Hub (with its Grids) and for Grids without a Hub."""
    hubs = [
        {"hub": hub, "total": tally(hub=hub), "grids": [(g, tally(grid=g)) for g in hub.grids.all()]}
        for hub in Hub.objects.all()
    ]
    loose = [(g, tally(grid=g)) for g in Grid.objects.filter(hub__isnull=True)]
    context = {
        **admin.site.each_context(request),
        "title": "Collection and output tally",
        "hubs": hubs,
        "loose": loose,
        "everything": tally(),
    }
    return render(request, "operations/stock_report.html", context)
