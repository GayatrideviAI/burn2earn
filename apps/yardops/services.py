"""Recording yard measurements and keeping alerts in step with them."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import Status
from apps.customers import services as stock
from apps.customers.models import Batch, Pile
from apps.ledger import chain

from . import risk
from .models import AlertLevel, HeatReading, PileInspection, ReadingMethod, RiskAlert


def _check_pile(pile):
    if pile.status != Status.ACTIVE:
        raise ValidationError(_("This pile is no longer in use."))


@transaction.atomic
def record_heat(pile, temperature_c, *, taken_at=None, depth_cm=None, spot="", method=ReadingMethod.MANUAL_PROBE, taken_by=""):
    _check_pile(pile)
    reading = HeatReading(
        pile=pile, taken_at=taken_at or timezone.now(), temperature_c=Decimal(temperature_c), depth_cm=depth_cm,
        spot=spot.strip(), method=method, taken_by=taken_by,
    )
    reading.full_clean(exclude=["created_by", "updated_by"])
    if reading.taken_at > timezone.now() + timedelta(minutes=5):
        raise ValidationError(_("The reading time cannot be in the future."))
    reading.save()
    entry = chain.append(
        "yard.heat",
        pile,
        {"pile": str(pile), "temperature_c": reading.temperature_c, "spot": reading.spot, "depth_cm": depth_cm,
         "method": method, "taken_by": taken_by, "taken_at": reading.taken_at},
    )
    HeatReading.objects.filter(pk=reading.pk).update(ledger_seq=entry.seq)
    reading.ledger_seq = entry.seq
    sync_alerts(pile)
    return reading


@transaction.atomic
def record_inspection(pile, *, looks_wet=False, mould=False, steam_or_smell=False, cover_in_place=True, notes="",
                      inspected_at=None, inspected_by=""):
    _check_pile(pile)
    inspection = PileInspection(
        pile=pile, inspected_at=inspected_at or timezone.now(), looks_wet=looks_wet, mould=mould,
        steam_or_smell=steam_or_smell, cover_in_place=cover_in_place, notes=notes, inspected_by=inspected_by,
    )
    inspection.save()
    entry = chain.append(
        "yard.inspected",
        pile,
        {"pile": str(pile), "looks_wet": looks_wet, "mould": mould, "steam_or_smell": steam_or_smell,
         "cover_in_place": cover_in_place, "inspected_by": inspected_by, "inspected_at": inspection.inspected_at},
    )
    PileInspection.objects.filter(pk=inspection.pk).update(ledger_seq=entry.seq)
    inspection.ledger_seq = entry.seq
    sync_alerts(pile)
    return inspection


@transaction.atomic
def update_pile_size(pile, *, length_m=None, width_m=None, height_m=None, cover_type=None):
    for name, value in (("length_m", length_m), ("width_m", width_m), ("height_m", height_m)):
        if value is not None:
            setattr(pile, name, Decimal(value))
    if cover_type is not None:
        pile.cover_type = cover_type
    pile.full_clean(exclude=["created_by", "updated_by"])
    pile.save()
    sync_alerts(pile)
    return pile


def _reasons_text(assessment):
    return "\n".join(r.text for r in assessment.reasons if r.level >= risk.WATCH)


@transaction.atomic
def sync_alerts(pile, now=None):
    """Raise, escalate or clear the alert for a pile so it matches the current assessment."""
    now = now or timezone.now()
    assessment = risk.assess(pile, now)
    open_alerts = list(RiskAlert.objects.select_for_update().filter(pile=pile, resolved_at__isnull=True, status=Status.ACTIVE))
    level = assessment.level
    if level < risk.WATCH:
        for alert in open_alerts:
            _resolve(alert, now, _("Back below the alert level."))
        return None
    key = risk.ALERT_KEYS[level]
    current = open_alerts[0] if open_alerts else None
    if current and current.level == key:
        return current
    for alert in open_alerts:
        _resolve(alert, now, _("Replaced by an alert at a different level."))
    alert = RiskAlert.objects.create(pile=pile, level=key, reasons=_reasons_text(assessment), raised_at=now)
    entry = chain.append("yard.alert.raised", alert, {"alert": alert.code, "pile": str(pile), "level": key, "reasons": alert.reasons})
    RiskAlert.objects.filter(pk=alert.pk).update(ledger_seq=entry.seq)
    alert.ledger_seq = entry.seq
    return alert


def _resolve(alert, now, note):
    alert.resolved_at = now
    alert.note = (alert.note + "\n" + note).strip() if alert.note else note
    alert.save(update_fields=["resolved_at", "note", "updated_at"])
    chain.append("yard.alert.resolved", alert, {"alert": alert.code, "note": note, "resolved_at": now})


@transaction.atomic
def acknowledge(alert, user, note=""):
    if alert.acknowledged_at is not None:
        return alert
    if alert.resolved_at is not None:
        raise ValidationError(_("This alert is already closed."))
    alert.acknowledged_by = user
    alert.acknowledged_at = timezone.now()
    if note:
        alert.note = (alert.note + "\n" + note).strip() if alert.note else note
    alert.save(update_fields=["acknowledged_by", "acknowledged_at", "note", "updated_at"])
    chain.append(
        "yard.alert.acknowledged", alert,
        {"alert": alert.code, "by": user.username, "response_minutes": alert.response_minutes, "note": note},
    )
    return alert


def open_alerts(yards=None):
    qs = RiskAlert.objects.filter(resolved_at__isnull=True, status=Status.ACTIVE).select_related("pile__yard")
    if yards is not None:
        qs = qs.filter(pile__yard__in=yards)
    return qs


def overdue(alert, now=None):
    """Not acknowledged within the allowed time."""
    from django.conf import settings

    now = now or timezone.now()
    return alert.acknowledged_at is None and (now - alert.raised_at).total_seconds() > settings.YARD_ALERT_ACK_MINUTES * 60


# Counts and moisture readings use the customer stock services, so they feed the same numbers.
def record_count(batch, tonnes, method, *, counted_by=""):
    return stock.record_count(batch, tonnes, method, counted_by=counted_by)


def record_moisture(batch, percent, *, method="handheld meter", tested_by=""):
    return stock.record_quality(batch, moisture_percent=percent, method=method, tested_by=tested_by)
