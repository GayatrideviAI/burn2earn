from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from apps.core.admin import NoDeleteAdminMixin

from .models import ConsentRecord, Farmer, FarmPlot, PlotSeason


class ConsentInline(admin.TabularInline):
    """A farmer cannot be added in the admin without at least one consent record."""

    model = ConsentRecord
    extra = 0
    min_num = 1
    validate_min = True
    can_delete = False
    fields = ("purpose", "notice_version", "language", "given_at", "captured_by_mitra", "withdrawn_at")


@admin.register(Farmer)
class FarmerAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "mobile",
        "village",
        "registered_by_mitra",
        "consent_given",
        "needs_review",
        "status",
    )
    list_filter = ("needs_review", "status", "registered_by_mitra", "preferred_language")
    search_fields = ("code", "name", "mobile")
    readonly_fields = ("code", "anonymised_at")
    inlines = [ConsentInline]
    actions = ["mark_reviewed"]

    @admin.action(description="Mark selected farmers as reviewed (clear the duplicate flag)")
    def mark_reviewed(self, request, queryset):
        for farmer in queryset.filter(needs_review=True):
            farmer.needs_review = False
            farmer.save()

    @admin.display(boolean=True, description="Consent")
    def consent_given(self, obj):
        return obj.has_consent


class PlotSeasonInline(admin.TabularInline):
    model = PlotSeason
    extra = 0
    can_delete = False
    fields = ("season", "year", "crop", "variety", "sowing_date", "expected_harvest_date")


class OutsideGeoCellsFilter(admin.SimpleListFilter):
    """Plots that landed outside every GeoCell need an Admin to look at them."""

    title = "GeoCell"
    parameter_name = "placement"

    def lookups(self, request, model_admin):
        return [("outside", "Outside every GeoCell")]

    def queryset(self, request, queryset):
        if self.value() == "outside":
            return queryset.filter(geocell__isnull=True)
        return queryset


@admin.register(FarmPlot)
class FarmPlotAdmin(NoDeleteAdminMixin, GISModelAdmin):
    list_display = ("farmer", "area_acres", "geocell", "panchayat_note", "ownership", "irrigation", "status")
    list_filter = (OutsideGeoCellsFilter, "status", "geocell__region", "ownership", "irrigation")
    search_fields = ("farmer__code", "farmer__name", "geocell__code")
    readonly_fields = ("geocell",)
    inlines = [PlotSeasonInline]

    @admin.display(description="Note")
    def panchayat_note(self, obj):
        if obj.outside_geocells:
            return "Outside every GeoCell"
        if obj.panchayat_differs_from_village:
            return "Different panchayat from farmer's village"
        return ""
