from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from apps.core.admin import NoDeleteAdminMixin

from .models import Grid, Hub


@admin.register(Hub)
class HubAdmin(NoDeleteAdminMixin, GISModelAdmin):
    list_display = (
        "code",
        "name",
        "region",
        "storage_capacity_t",
        "operator",
        "operating_status",
        "status",
    )
    list_filter = ("status", "operating_status", "region")
    search_fields = ("code", "name")


@admin.register(Grid)
class GridAdmin(NoDeleteAdminMixin, GISModelAdmin):
    list_display = (
        "code",
        "name",
        "region",
        "hub",
        "processing_capacity_tpd",
        "operating_status",
        "cell_count",
        "status",
    )
    list_filter = ("status", "operating_status", "region", "hub")
    search_fields = ("code", "name")

    @admin.display(description="GeoCells")
    def cell_count(self, obj):
        note = obj.geocell_count_note
        return f"{obj.geocell_count} ({note})" if note else obj.geocell_count
