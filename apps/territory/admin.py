from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from apps.core.admin import NoDeleteAdminMixin

from .models import GeoCell, Region
from .services import generate_panchayat_cells


@admin.register(Region)
class RegionAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "state", "district", "status")
    list_filter = ("status", "state")
    search_fields = ("code", "name")
    actions = ["generate_geocells"]

    @admin.action(description="Generate one GeoCell per panchayat")
    def generate_geocells(self, request, queryset):
        for region in queryset:
            result = generate_panchayat_cells(region)
            self.message_user(
                request,
                f"{region.code}: {result.created} cells created, "
                f"{result.already_existing} already existed, "
                f"{result.missing_boundary} panchayats have no boundary yet.",
            )


@admin.register(GeoCell)
class GeoCellAdmin(NoDeleteAdminMixin, GISModelAdmin):
    list_display = ("code", "region", "panchayat", "origin", "area_acres", "status")
    list_filter = ("status", "origin", "region")
    search_fields = ("code", "panchayat__name", "panchayat__lgd_code")
    fields = (
        "code",
        "region",
        "panchayat",
        "origin",
        "boundary",
        "area_acres",
        "status",
        "notes",
    )
    readonly_fields = ("area_acres",)
