from django.contrib import admin

from apps.core.admin import NoDeleteAdminMixin

from .models import CollectionRecord, ProcessedOutput


@admin.register(CollectionRecord)
class CollectionRecordAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "collected_on", "farmer", "mitra", "grid", "biomass_type", "quantity_tonnes", "price_paid", "status")
    list_filter = ("status", "grid", "biomass_type", "collected_on")
    search_fields = ("code", "farmer__code", "farmer__name", "mitra__name")
    readonly_fields = ("code",)
    date_hierarchy = "collected_on"


@admin.register(ProcessedOutput)
class ProcessedOutputAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "produced_on", "grid", "mitra", "product", "quantity_tonnes", "biomass_used_tonnes", "status")
    list_filter = ("status", "grid", "product", "produced_on")
    search_fields = ("code", "mitra__name", "product__name")
    readonly_fields = ("code",)
    date_hierarchy = "produced_on"
