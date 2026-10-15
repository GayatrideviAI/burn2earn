from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from apps.core.admin import NoDeleteAdminMixin

from django.db.models import Sum

from apps.operations.models import ProcessedOutput

from .models import Buyer, Factory, Requirement


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


@admin.register(Requirement)
class RequirementAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "factory",
        "product",
        "volume_tonnes",
        "volume_met_tonnes",
        "needed_by",
        "target_gcv",
        "fulfilment",
        "produced_so_far",
        "status",
    )
    list_filter = ("fulfilment", "status", "product", "factory__buyer")
    search_fields = ("code", "factory__name", "factory__buyer__company_name", "product__name")
    readonly_fields = ("code",)
    date_hierarchy = "needed_by"

    @admin.display(description="Produced so far (t)")
    def produced_so_far(self, obj):
        """Everything reported for this product across the network, as a rough guide for a person."""
        total = ProcessedOutput.objects.filter(product=obj.product, status="active").aggregate(t=Sum("quantity_tonnes"))["t"]
        return total or 0
