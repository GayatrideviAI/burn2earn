from decimal import Decimal

from django.contrib import admin, messages

from apps.core.admin import NoDeleteAdminMixin
from apps.customers.admin import AddOnlyMixin, adopt

from . import services
from .models import HeatReading, PileInspection, RiskAlert, YardOperator


@admin.register(YardOperator)
class YardOperatorAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "user", "status")
    filter_horizontal = ("yards",)
    search_fields = ("name", "user__username")


@admin.register(HeatReading)
class HeatReadingAdmin(AddOnlyMixin, admin.ModelAdmin):
    """Added through the service so the ledger entry and any alert follow."""

    list_display = ("pile", "temperature_c", "spot", "method", "taken_at", "taken_by", "ledger_seq")
    list_filter = ("method", "pile__yard")
    fields = ("pile", "temperature_c", "spot", "depth_cm", "method", "taken_at", "taken_by")

    def save_model(self, request, obj, form, change):
        d = form.cleaned_data
        row = services.record_heat(
            d["pile"], d["temperature_c"], taken_at=d["taken_at"], depth_cm=d.get("depth_cm"), spot=d.get("spot", ""),
            method=d["method"], taken_by=d.get("taken_by") or request.user.get_username(),
        )
        adopt(obj, row)


@admin.register(PileInspection)
class PileInspectionAdmin(AddOnlyMixin, admin.ModelAdmin):
    list_display = ("pile", "inspected_at", "looks_wet", "mould", "steam_or_smell", "cover_in_place", "inspected_by")
    list_filter = ("pile__yard",)
    fields = ("pile", "inspected_at", "looks_wet", "mould", "steam_or_smell", "cover_in_place", "notes", "inspected_by")

    def save_model(self, request, obj, form, change):
        d = form.cleaned_data
        row = services.record_inspection(
            d["pile"], looks_wet=d["looks_wet"], mould=d["mould"], steam_or_smell=d["steam_or_smell"],
            cover_in_place=d["cover_in_place"], notes=d["notes"], inspected_at=d["inspected_at"],
            inspected_by=d.get("inspected_by") or request.user.get_username(),
        )
        adopt(obj, row)


@admin.register(RiskAlert)
class RiskAlertAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    """Alerts are raised by the readings. Staff can see them, acknowledge them and add a note."""

    list_display = ("code", "pile", "level", "raised_at", "acknowledged_at", "response", "resolved_at")
    list_filter = ("level", "pile__yard")
    readonly_fields = ("code", "pile", "level", "reasons", "raised_at", "acknowledged_by", "acknowledged_at", "resolved_at", "ledger_seq")
    actions = ["acknowledge_selected"]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Response (min)")
    def response(self, obj):
        return obj.response_minutes

    @admin.action(description="Acknowledge the selected open alerts")
    def acknowledge_selected(self, request, queryset):
        done = 0
        for alert in queryset.filter(resolved_at__isnull=True, acknowledged_at__isnull=True):
            services.acknowledge(alert, request.user)
            done += 1
        self.message_user(request, f"{done} alert(s) acknowledged.", messages.SUCCESS)
