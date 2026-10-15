from django import forms
from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from apps.core.admin import NoDeleteAdminMixin

from .models import Equipment, EquipmentType, Grid, Hub, Mitra, MitraGridAssignment


class EquipmentInline(admin.TabularInline):
    """Add and edit the equipment at a Grid or Hub right on its page."""

    model = Equipment
    extra = 0
    can_delete = False
    fields = (
        "code",
        "equipment_type",
        "serial_number",
        "manufacturer",
        "capacity",
        "capacity_unit",
        "installation_date",
        "operating_status",
    )


class GridEquipmentInline(EquipmentInline):
    fk_name = "grid"
    exclude = ("hub",)


class HubEquipmentInline(EquipmentInline):
    fk_name = "hub"
    exclude = ("grid",)


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
    inlines = [HubEquipmentInline]


class GridAdminForm(forms.ModelForm):
    """A Grid must say what it can make, but only the admin form enforces it."""

    class Meta:
        model = Grid
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["processing_types"].required = True


@admin.register(Grid)
class GridAdmin(NoDeleteAdminMixin, GISModelAdmin):
    form = GridAdminForm
    filter_horizontal = ("processing_types",)
    list_display = (
        "code",
        "name",
        "region",
        "hub",
        "current_mitra",
        "processing_capacity_tpd",
        "operating_status",
        "cell_count",
        "status",
    )
    list_filter = ("status", "operating_status", "region", "hub")
    search_fields = ("code", "name")
    readonly_fields = ("current_mitra",)
    inlines = [GridEquipmentInline]

    @admin.display(description="GeoCells")
    def cell_count(self, obj):
        note = obj.geocell_count_note
        return f"{obj.geocell_count} ({note})" if note else obj.geocell_count


class MitraGridAssignmentInline(admin.TabularInline):
    """To change a Mitra's Grid: set the end date on the old row, then add a new row."""

    model = MitraGridAssignment
    extra = 0
    can_delete = False
    fields = ("grid", "from_date", "to_date")


@admin.register(Mitra)
class MitraAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "mobile",
        "region",
        "current_grid",
        "onboarding_status",
        "operating_status",
        "status",
    )
    list_filter = ("status", "onboarding_status", "operating_status", "region")
    search_fields = ("code", "name", "mobile")
    readonly_fields = ("current_grid", "cells_covered", "equipment_count")
    inlines = [MitraGridAssignmentInline]

    @admin.display(description="GeoCells covered")
    def cells_covered(self, obj):
        return obj.geocells.count() if obj.pk else "-"

    @admin.display(description="Equipment at their Grid")
    def equipment_count(self, obj):
        return obj.equipment.count() if obj.pk else "-"


@admin.register(EquipmentType)
class EquipmentTypeAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "status")
    search_fields = ("name",)


@admin.register(Equipment)
class EquipmentAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "equipment_type",
        "grid",
        "hub",
        "capacity",
        "capacity_unit",
        "operating_status",
        "next_maintenance",
    )
    list_filter = ("operating_status", "equipment_type", "grid", "hub")
    search_fields = ("code", "serial_number", "manufacturer")
