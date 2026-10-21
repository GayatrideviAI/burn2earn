"""All stock changes go through here, so each one is validated and written to the ledger."""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import Status
from apps.ledger import chain

from .models import (
    Basis,
    Batch,
    InventoryTransaction,
    QualityObservation,
    Reservation,
    StockCount,
    TransactionKind,
    unreceived_tonnes,
)

ZERO = Decimal("0")
TENTH = Decimal("0.1")
LEAVING = {TransactionKind.CONSUMPTION, TransactionKind.LOSS, TransactionKind.RETURN, TransactionKind.DISPOSAL}


def verification_days():
    return getattr(settings, "STOCK_VERIFICATION_DAYS", 14)


def lead_time_days():
    return getattr(settings, "STOCK_REPLENISH_LEAD_DAYS", 14)


# ---- changes ----------------------------------------------------------------------------------


def book_tonnes(batch):
    total = InventoryTransaction.objects.filter(batch=batch, status=Status.ACTIVE).aggregate(t=Sum("tonnes_change"))["t"]
    return total or ZERO


def signed_change(kind, tonnes):
    """Turn what a person types into the signed change. Everything is typed as a positive weight except adjustments."""
    if kind == TransactionKind.TRANSFER:
        return ZERO
    if tonnes in (None, ""):
        raise ValidationError("Enter the weight.")
    tonnes = Decimal(tonnes)
    if kind == TransactionKind.ADJUSTMENT:
        if tonnes == 0:
            raise ValidationError("An adjustment cannot be zero.")
        return tonnes
    if tonnes <= 0:
        raise ValidationError("The weight must be more than zero.")
    return -tonnes if kind in LEAVING else tonnes


def validate_transaction(batch, kind, tonnes=None, loss_cause="", to_pile=None):
    """Return the signed change, or raise ValidationError."""
    change = signed_change(kind, tonnes)
    if kind == TransactionKind.LOSS and not loss_cause:
        raise ValidationError("Say what caused the loss, so losses can be split by cause.")
    if kind == TransactionKind.TRANSFER:
        if to_pile is None:
            raise ValidationError("Choose the pile it is moving to.")
        if to_pile.pk == batch.pile_id:
            raise ValidationError("The batch is already in that pile.")
    if book_tonnes(batch) + change < 0:
        raise ValidationError(f"Only {book_tonnes(batch)} t is on the books for this batch.")
    return change


@transaction.atomic
def record_transaction(batch, kind, tonnes=None, *, loss_cause="", to_pile=None, occurred_at=None, note=""):
    batch = Batch.objects.select_for_update().get(pk=batch.pk)
    change = validate_transaction(batch, kind, tonnes, loss_cause, to_pile)
    entry_row = InventoryTransaction.objects.create(
        batch=batch,
        kind=kind,
        tonnes_change=change,
        loss_cause=loss_cause if kind == TransactionKind.LOSS else "",
        to_pile=to_pile if kind == TransactionKind.TRANSFER else None,
        occurred_at=occurred_at or timezone.now(),
        note=note,
    )
    from_pile = batch.pile
    if kind == TransactionKind.TRANSFER:
        batch.pile = to_pile
        batch.save(update_fields=["pile"])
    entry = chain.append(
        f"stock.{kind}",
        batch,
        {
            "batch": batch.code,
            "customer": batch.customer.code,
            "source_dispatch": batch.source_dispatch.code if batch.source_dispatch_id else None,
            "kind": kind,
            "tonnes_change": change,
            "book_after_tonnes": book_tonnes(batch),
            "from_pile": f"{from_pile.yard.code}/{from_pile.label}",
            "to_pile": f"{to_pile.yard.code}/{to_pile.label}" if kind == TransactionKind.TRANSFER else None,
            "loss_cause": entry_row.loss_cause,
            "occurred_at": entry_row.occurred_at,
            "note": note,
        },
    )
    InventoryTransaction.objects.filter(pk=entry_row.pk).update(ledger_seq=entry.seq)
    entry_row.ledger_seq = entry.seq
    return entry_row


@transaction.atomic
def receive_delivery(dispatch, pile, form, *, tonnes=None, moisture=None, received_on=None):
    """Put (all or part of) a delivered load into a yard pile as a new batch, linked back to the load."""
    from apps.trade.models import Dispatch

    dispatch = Dispatch.objects.select_for_update().get(pk=dispatch.pk)
    left = unreceived_tonnes(dispatch)
    batch = Batch(
        customer=dispatch.factory.buyer, pile=pile, biomass_type=dispatch.product.biomass_type, form=form,
        source_dispatch=dispatch, received_on=received_on or date.today(),
        intake_tonnes=left if tonnes in (None, "") else Decimal(tonnes),
        intake_moisture_percent=None if moisture in (None, "") else Decimal(moisture),
    )
    batch.clean()
    batch.save()
    receive_batch(batch)
    return batch


@transaction.atomic
def receive_batch(batch):
    """Record the receipt of a newly created batch, and its intake moisture reading if there is one."""
    received = timezone.make_aware(datetime.combine(batch.received_on, time.min))
    row = record_transaction(
        batch, TransactionKind.RECEIPT, batch.intake_tonnes, occurred_at=received, note="Received at the yard"
    )
    if batch.intake_moisture_percent is not None:
        record_quality(batch, moisture_percent=batch.intake_moisture_percent, method="Intake check", basis=Basis.MEASURED)
    return row


@transaction.atomic
def record_count(batch, counted_tonnes, method, *, counted_on=None, counted_by=""):
    counted_tonnes = Decimal(counted_tonnes)
    if counted_tonnes < 0:
        raise ValidationError("A count cannot be negative.")
    count = StockCount.objects.create(
        batch=batch, counted_tonnes=counted_tonnes, method=method, counted_on=counted_on or date.today(), counted_by=counted_by
    )
    entry = chain.append(
        "stock.counted",
        batch,
        {
            "batch": batch.code,
            "counted_tonnes": count.counted_tonnes,
            "book_tonnes": book_tonnes(batch),
            "method": method,
            "counted_on": count.counted_on,
            "counted_by": counted_by,
        },
    )
    StockCount.objects.filter(pk=count.pk).update(ledger_seq=entry.seq)
    count.ledger_seq = entry.seq
    return count


@transaction.atomic
def record_quality(batch, *, moisture_percent=None, ash_percent=None, gcv=None, basis=Basis.MEASURED,
                   observed_at=None, method="", tested_by=""):
    obs = QualityObservation(
        batch=batch, basis=basis, observed_at=observed_at or timezone.now(), moisture_percent=moisture_percent,
        ash_percent=ash_percent, gcv=gcv, method=method, tested_by=tested_by,
    )
    obs.clean()
    obs.save()
    entry = chain.append(
        "quality.observed",
        batch,
        {
            "batch": batch.code,
            "basis": basis,
            "moisture_percent": moisture_percent,
            "ash_percent": ash_percent,
            "gcv": gcv,
            "method": method,
            "tested_by": tested_by,
            "observed_at": obs.observed_at,
        },
    )
    QualityObservation.objects.filter(pk=obs.pk).update(ledger_seq=entry.seq)
    obs.ledger_seq = entry.seq
    return obs


@transaction.atomic
def reserve(batch, factory, tonnes, note=""):
    batch = Batch.objects.select_for_update().get(pk=batch.pk)
    tonnes = Decimal(tonnes)
    if factory.buyer_id != batch.customer_id:
        raise ValidationError("A batch can only be reserved for its own customer's plant.")
    free = book_tonnes(batch) - reserved_tonnes(batch)
    if tonnes <= 0 or tonnes > free:
        raise ValidationError(f"Only {free} t of this batch is not already reserved.")
    reservation = Reservation.objects.create(batch=batch, factory=factory, tonnes=tonnes, note=note)
    chain.append(
        "stock.reserved", batch,
        {"batch": batch.code, "plant": factory.code, "tonnes": tonnes, "note": note},
    )
    return reservation


def reserved_tonnes(batch):
    total = Reservation.objects.filter(batch=batch, status=Status.ACTIVE).aggregate(t=Sum("tonnes"))["t"]
    return total or ZERO


# ---- the numbers a customer sees ---------------------------------------------------------------


@dataclass
class BatchView:
    batch: Batch
    book: Decimal
    physical: Decimal = None  # None until someone has counted it
    reserved: Decimal = ZERO
    usable: Decimal = ZERO
    available: Decimal = ZERO
    confidence: str = "Calculated"
    quality: str = "no_reading"  # ok, over_limit, no_reading
    moisture: Decimal = None
    moisture_basis: str = ""
    last_count: StockCount = None

    @property
    def gap(self):
        """Counted minus book. Negative means stock is missing."""
        return None if self.physical is None else self.physical - self.book


def plant_limit(buyer):
    """The strictest maximum moisture across the customer's plants, or None if none is set."""
    from apps.demand.models import Factory

    limits = [
        f.maximum_moisture_percent
        for f in Factory.objects.filter(buyer=buyer, status=Status.ACTIVE)
        if f.maximum_moisture_percent is not None
    ]
    return min(limits) if limits else None


def batch_view(batch, *, limit=None, today=None):
    today = today or date.today()
    view = BatchView(batch=batch, book=book_tonnes(batch), reserved=reserved_tonnes(batch))
    count = StockCount.objects.filter(batch=batch, status=Status.ACTIVE).order_by("-counted_on", "-created_at").first()
    if count:
        since = InventoryTransaction.objects.filter(
            batch=batch, status=Status.ACTIVE, occurred_at__date__gt=count.counted_on
        ).aggregate(t=Sum("tonnes_change"))["t"] or ZERO
        view.physical = count.counted_tonnes + since
        view.last_count = count
        if (today - count.counted_on).days > verification_days():
            view.confidence = "Overdue"
        elif count.method == "survey":
            view.confidence = "Estimated"
        else:
            view.confidence = "Verified"
    reading = (
        QualityObservation.objects.filter(batch=batch, status=Status.ACTIVE, basis=Basis.MEASURED, moisture_percent__isnull=False)
        .order_by("-observed_at").first()
    )
    if reading:
        view.moisture, view.moisture_basis = reading.moisture_percent, reading.get_basis_display()
    if limit is None:
        view.quality = "ok"
    elif reading is None:
        view.quality = "no_reading"
    else:
        view.quality = "ok" if reading.moisture_percent <= limit else "over_limit"
    if view.physical is not None and view.quality == "ok":
        view.usable = max(view.physical, ZERO)
    view.available = max(view.usable - view.reserved, ZERO)
    return view


@dataclass
class Summary:
    rows: list = field(default_factory=list)
    yards: list = field(default_factory=list)
    book: Decimal = ZERO
    physical: Decimal = ZERO
    usable: Decimal = ZERO
    reserved: Decimal = ZERO
    available: Decimal = ZERO
    exposed: Decimal = ZERO
    daily_burn: Decimal = None
    fuel_cover_days: Decimal = None
    actions: list = field(default_factory=list)


def summary(buyer, today=None):
    from apps.demand.models import Factory

    today = today or date.today()
    limit = plant_limit(buyer)
    batches = Batch.objects.filter(customer=buyer, status=Status.ACTIVE).select_related("pile__yard", "biomass_type")
    s = Summary()
    by_yard = {}
    for batch in batches:
        v = batch_view(batch, limit=limit, today=today)
        if v.book == 0 and v.physical in (None, ZERO):
            continue
        s.rows.append(v)
        s.book += v.book
        s.physical += v.physical if v.physical is not None else ZERO
        s.usable += v.usable
        s.reserved += v.reserved
        s.available += v.available
        if batch.pile.exposure == "open":
            s.exposed += v.book
        y = by_yard.setdefault(batch.pile.yard_id, {"yard": batch.pile.yard, "book": ZERO, "physical": ZERO, "usable": ZERO,
                                                    "available": ZERO, "exposed": ZERO, "uncounted": 0})
        y["book"] += v.book
        y["physical"] += v.physical if v.physical is not None else ZERO
        y["usable"] += v.usable
        y["available"] += v.available
        if batch.pile.exposure == "open":
            y["exposed"] += v.book
        if v.physical is None:
            y["uncounted"] += 1
    s.yards = sorted(by_yard.values(), key=lambda y: y["yard"].code)
    burns = [
        f.profile.daily_consumption_tonnes
        for f in Factory.objects.filter(buyer=buyer, status=Status.ACTIVE).select_related("profile")
        if hasattr(f, "profile")
    ]
    if burns and sum(burns) > 0:
        s.daily_burn = sum(burns)
        s.fuel_cover_days = (s.available / s.daily_burn).quantize(TENTH)
    s.actions = build_actions(s, limit)
    return s


def build_actions(s, limit):
    actions = []
    for v in s.rows:
        c = v.batch.code
        where = _("%(yard)s, pile %(pile)s") % {"yard": v.batch.pile.yard.name, "pile": v.batch.pile.label}
        if v.confidence == "Overdue":
            days = (date.today() - v.last_count.counted_on).days
            actions.append(("warn", _("Verification overdue"), _("%(code)s (%(where)s) was last counted %(days)s days ago.") % {"code": c, "where": where, "days": days}, v.batch))
        elif v.physical is None:
            actions.append(("warn", _("Not counted yet"), _("%(code)s (%(where)s) has never been physically counted, so it is not usable stock yet.") % {"code": c, "where": where}, v.batch))
        if v.quality == "no_reading":
            actions.append(("warn", _("Check moisture"), _("%(code)s (%(where)s) has no measured moisture reading.") % {"code": c, "where": where}, v.batch))
        elif v.quality == "over_limit":
            actions.append(("bad", _("Over moisture limit"), _("%(code)s (%(where)s) is at %(moisture)s%%, above your %(limit)s%% limit.") % {"code": c, "where": where, "moisture": v.moisture, "limit": limit}, v.batch))
        gap = v.gap
        if gap is not None and v.book and abs(gap) / v.book > Decimal("0.005"):
            actions.append(("warn", _("Reconcile"), _("%(code)s (%(where)s): books say %(book)s t, counted %(counted)s t.") % {"code": c, "where": where, "book": v.book, "counted": v.physical}, v.batch))
    if s.fuel_cover_days is not None and s.fuel_cover_days < lead_time_days():
        actions.append(("bad", _("Low fuel cover"), _("%(days)s days of cover is less than the %(lead)s-day replenishment lead time.") % {"days": s.fuel_cover_days, "lead": lead_time_days()}, None))
    order = {"bad": 0, "warn": 1}
    return sorted(actions, key=lambda a: order.get(a[0], 2))
