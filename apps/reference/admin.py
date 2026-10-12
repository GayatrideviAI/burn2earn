from django.contrib import admin

from apps.core.admin import NoDeleteAdminMixin

from .models import Crop, Season


@admin.register(Crop)
class CropAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "status")
    list_filter = ("status",)
    search_fields = ("name",)


@admin.register(Season)
class SeasonAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "start_month", "end_month", "status")
    list_filter = ("status",)
