from django.contrib import admin

from apps.core.admin import NoDeleteAdminMixin

from .models import BiomassType, Crop, ProcessingType, Product, Season, StateBiomassFactor


@admin.register(Crop)
class CropAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "status")
    list_filter = ("status",)
    search_fields = ("name",)


@admin.register(Season)
class SeasonAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "start_month", "end_month", "status")
    list_filter = ("status",)


class StateBiomassFactorInline(admin.TabularInline):
    model = StateBiomassFactor
    extra = 0
    can_delete = False
    fields = ("state", "estimated_tonnes_per_acre", "pilferage_percent", "status")


@admin.register(StateBiomassFactor)
class StateBiomassFactorAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("state", "biomass_type", "estimated_tonnes_per_acre", "pilferage_percent", "status")
    list_filter = ("state", "status")
    search_fields = ("biomass_type__name", "state__name")


@admin.register(BiomassType)
class BiomassTypeAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    inlines = [StateBiomassFactorInline]
    list_display = ("name", "crop", "estimated_tonnes_per_acre", "gcv_min", "gcv_max", "status")
    list_filter = ("status", "crop")
    search_fields = ("name", "crop__name")


@admin.register(ProcessingType)
class ProcessingTypeAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "status")
    list_filter = ("status",)
    search_fields = ("name",)
    filter_horizontal = ("input_biomass_types",)


@admin.register(Product)
class ProductAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "grade", "form", "biomass_type", "processing_type", "minimum_gcv", "status")
    list_filter = ("status", "form", "biomass_type", "processing_type")
    search_fields = ("name", "grade")
