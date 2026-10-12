import uuid

from django.conf import settings
from django.db import models

from .current_user import get_current_user_id


class DeletionNotAllowed(Exception):
    """Master data is deactivated, never deleted."""


class Status(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class OperatingStatus(models.TextChoices):
    """Life-cycle of a physical site such as a Grid or a Hub."""

    PLANNED = "planned", "Planned"
    COMMISSIONING = "commissioning", "Commissioning"
    OPERATING = "operating", "Operating"
    PAUSED = "paused", "Paused"
    CLOSED = "closed", "Closed"


class BaseModel(models.Model):
    """Housekeeping fields shared by every master record."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        user_id = get_current_user_id()
        if user_id is not None:
            if self._state.adding and self.created_by_id is None:
                self.created_by_id = user_id
            self.updated_by_id = user_id
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "updated_at", "updated_by"}
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DeletionNotAllowed(
            f"{self.__class__.__name__} records are deactivated, not deleted."
        )

    def deactivate(self):
        self.status = Status.INACTIVE
        self.save(update_fields=["status"])


class Counter(models.Model):
    """Running number behind a code series (see apps/core/codes.py)."""

    name = models.CharField(max_length=50, unique=True)
    value = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return f"{self.name}: {self.value}"


class AuditLog(models.Model):
    """One row per create or change of a master record."""

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    action = models.CharField(max_length=10, choices=Action.choices)
    model_label = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=64, db_index=True)
    # {field_name: [old_value, new_value]}
    changes = models.JSONField(default=dict)

    class Meta:
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{self.action} {self.model_label} {self.object_id}"
