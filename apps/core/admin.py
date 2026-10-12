from django.contrib import admin

from .models import AuditLog


class NoDeleteAdminMixin:
    """Master data is deactivated (set status to Inactive), never deleted."""

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyAdminMixin(NoDeleteAdminMixin):
    """For reference data that is loaded by management commands, not typed by hand."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("at", "actor", "action", "model_label", "object_id")
    list_filter = ("action", "model_label")
    search_fields = ("object_id", "actor__username")
    date_hierarchy = "at"
