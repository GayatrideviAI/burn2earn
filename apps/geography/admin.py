from django.contrib import admin

from apps.core.admin import ReadOnlyAdminMixin

from .models import Block, District, Panchayat, State, Village


class GeographyAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    search_fields = ("name", "lgd_code")
    list_filter = ("status",)


@admin.register(State)
class StateAdmin(GeographyAdmin):
    list_display = ("name", "lgd_code", "status")


@admin.register(District)
class DistrictAdmin(GeographyAdmin):
    list_display = ("name", "lgd_code", "state", "status")
    list_filter = ("status", "state")


@admin.register(Block)
class BlockAdmin(GeographyAdmin):
    list_display = ("name", "lgd_code", "district", "status")
    list_filter = ("status", "district__state")


@admin.register(Panchayat)
class PanchayatAdmin(GeographyAdmin):
    list_display = ("name", "lgd_code", "block", "has_boundary", "status")
    list_filter = ("status", "block__district")

    @admin.display(boolean=True, description="Boundary loaded")
    def has_boundary(self, obj):
        return obj.boundary is not None


@admin.register(Village)
class VillageAdmin(GeographyAdmin):
    list_display = ("name", "lgd_code", "panchayat", "status")
    list_filter = ("status",)
