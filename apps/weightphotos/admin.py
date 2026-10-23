import csv

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html

from apps.core.admin import NoDeleteAdminMixin

from . import services
from .models import WeightPhoto

CSV_COLUMNS = [
    "code", "subject", "source", "pile", "place_note", "vehicle_type", "vehicle_ref", "taken_at", "taken_by", "bale_count",
    "reference_note", "weighed_tonnes", "slip_number", "weighed_on", "width", "height", "sha256", "image",
]


def rows_for(queryset):
    for p in queryset.select_related("pile__yard"):
        yield [
            p.code, p.subject, p.source, str(p.pile) if p.pile_id else "", p.place_note, p.vehicle_type, p.vehicle_ref,
            p.taken_at.isoformat(), p.taken_by, p.bale_count if p.bale_count is not None else "", p.reference_note,
            p.weighed_tonnes if p.weighed_tonnes is not None else "", p.slip_number, p.weighed_on or "", p.width, p.height,
            p.sha256, p.image.name,
        ]


@admin.register(WeightPhoto)
class WeightPhotoAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    """Photos arrive from the phone apps. Staff add or correct the weighbridge weight here."""

    list_display = ("code", "subject", "source", "pile", "taken_at", "taken_by", "weighed_tonnes", "thumbnail")
    list_filter = ("subject", "source", "weighed_on")
    search_fields = ("code", "taken_by", "slip_number", "vehicle_ref")
    actions = ["download_csv"]
    readonly_fields = (
        "code", "subject", "source", "pile", "place_note", "vehicle_type", "vehicle_ref", "taken_at", "taken_by",
        "bale_count", "reference_note", "notes", "preview", "sha256", "width", "height", "ledger_seq",
    )
    fields = readonly_fields + ("weighed_tonnes", "slip_number", "weighed_on")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Photo")
    def thumbnail(self, obj):
        return format_html('<a href="{0}"><img src="{0}" style="height:48px"></a>', reverse("weightphotos:image", args=[obj.pk]))

    @admin.display(description="Photo")
    def preview(self, obj):
        return format_html('<img src="{}" style="max-width:480px;max-height:480px">', reverse("weightphotos:image", args=[obj.pk]))

    def save_model(self, request, obj, form, change):
        d = form.cleaned_data
        if d.get("weighed_tonnes") is None:
            return
        try:
            services.record_weight(
                obj, d["weighed_tonnes"], slip_number=d.get("slip_number", ""), weighed_on=d.get("weighed_on"),
                by=request.user.get_username(), allow_change=True,
            )
        except ValidationError as error:
            self.message_user(request, "; ".join(error.messages), messages.ERROR)

    @admin.action(description="Download the selected photos as a CSV (with weights)")
    def download_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="weight_photos.csv"'
        writer = csv.writer(response)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows_for(queryset))
        return response
