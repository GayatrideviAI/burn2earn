from django.contrib import admin, messages

from .chain import verify
from .models import LedgerEntry


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("seq", "created_at", "entry_type", "subject_type", "subject_id", "created_by")
    list_filter = ("entry_type", "subject_type")
    search_fields = ("subject_id", "entry_type", "payload_text")
    readonly_fields = [f.name for f in LedgerEntry._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        result = verify()
        if result.ok:
            messages.success(request, f"Ledger check: intact ({result.checked} entries).")
        else:
            messages.error(request, f"LEDGER PROBLEM: {result.problem}")
        return super().changelist_view(request, extra_context)
