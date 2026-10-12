"""Writes an AuditLog row whenever a master record is created or changed."""

import hashlib
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.contrib.gis.geos import GEOSGeometry
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .current_user import get_current_user_id
from .models import AuditLog, BaseModel

# Bookkeeping fields that would only add noise to the log.
IGNORED_FIELDS = {"id", "created_at", "created_by", "updated_at", "updated_by"}


def _serialize(value):
    if value is None:
        return None
    if isinstance(value, GEOSGeometry):
        # Geometries are large; a short fingerprint is enough to show they changed.
        return "<geometry %s>" % hashlib.sha1(bytes(value.wkb)).hexdigest()[:12]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _snapshot(instance):
    return {
        field.name: _serialize(field.value_from_object(instance))
        for field in instance._meta.concrete_fields
        if field.name not in IGNORED_FIELDS
    }


@receiver(pre_save)
def capture_previous_state(sender, instance, raw=False, **kwargs):
    if raw or not isinstance(instance, BaseModel):
        return
    instance._audit_before = None
    if not instance._state.adding:
        previous = sender._base_manager.filter(pk=instance.pk).first()
        if previous is not None:
            instance._audit_before = _snapshot(previous)


@receiver(post_save)
def write_audit_log(sender, instance, created, raw=False, **kwargs):
    if raw or not isinstance(instance, BaseModel):
        return
    after = _snapshot(instance)
    if created:
        action = AuditLog.Action.CREATE
        changes = {
            name: [None, value]
            for name, value in after.items()
            if value not in (None, "")
        }
    else:
        action = AuditLog.Action.UPDATE
        before = getattr(instance, "_audit_before", None) or {}
        changes = {
            name: [before.get(name), value]
            for name, value in after.items()
            if before.get(name) != value
        }
        if not changes:
            return
    # Personal data (a farmer's name or mobile) must never be copied into the log,
    # so the log only shows that such a field was set or changed.
    for name in getattr(instance, "audit_redacted_fields", ()):
        if name in changes:
            changes[name] = [
                None if value is None else "<redacted>" for value in changes[name]
            ]
    AuditLog.objects.create(
        actor_id=get_current_user_id(),
        action=action,
        model_label=sender._meta.label,
        object_id=str(instance.pk),
        changes=changes,
    )
