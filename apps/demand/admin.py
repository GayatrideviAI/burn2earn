from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from apps.core.admin import NoDeleteAdminMixin

from .models import Buyer, Factory


@admin.register(Buyer)
class BuyerAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "company_name", "contact_name", "commercial_status", "factory_count", "status")
    list_filter = ("status", "commercial_status")
    search_fields = ("code", "company_name", "gst_number", "contact_name")
    readonly_fields = ("code",)

    @admin.display(description="Factories")
    def factory_count(self, obj):
        return obj.factories.count()


@admin.register(Factory)
class FactoryAdmin(NoDeleteAdminMixin, GISModelAdmin):
    list_display = ("code", "name", "buyer", "operating_status", "minimum_gcv", "maximum_moisture_percent", "status")
    list_filter = ("status", "operating_status", "buyer")
    search_fields = ("code", "name", "buyer__company_name")
    readonly_fields = ("code",)
    filter_horizontal = ("preferred_biomass_types",)
