"""Dispatch, sale and fee operations. Every step is also written to the ledger."""

import json
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import Status
from apps.ledger import chain
from apps.operations.models import CollectionRecord, ProcessedOutput

from .models import (
    BuyerPayment,
    Dispatch,
    DispatchEvent,
    DispatchStage,
    EventType,
    FeeModel,
    FeeSchedule,
    LeaseCharge,
    Sale,
    money,
)

ZERO = Decimal("0")

# Which steps may follow which stage.
ALLOWED = {
    DispatchStage.AT_GRID: {EventType.RECEIVED_AT_HUB, EventType.IN_TRANSIT, EventType.CANCELLED},
    DispatchStage.AT_HUB: {EventType.IN_TRANSIT, EventType.CANCELLED},
    DispatchStage.IN_TRANSIT: {EventType.DELIVERED, EventType.CANCELLED},
}
STAGE_AFTER = {
    EventType.RECEIVED_AT_HUB: DispatchStage.AT_HUB,
    EventType.IN_TRANSIT: DispatchStage.IN_TRANSIT,
    EventType.DELIVERED: DispatchStage.DELIVERED,
    EventType.CANCELLED: DispatchStage.CANCELLED,
}


def available_to_dispatch(grid, product):
    """Tonnes of this product reported as made at the Grid and not already on a live dispatch."""
    made = (
        ProcessedOutput.objects.filter(grid=grid, product=product, status=Status.ACTIVE)
        .aggregate(t=Sum("quantity_tonnes"))["t"]
        or ZERO
    )
    sent = (
        Dispatch.objects.filter(grid=grid, product=product, status=Status.ACTIVE)
        .exclude(stage=DispatchStage.CANCELLED)
        .aggregate(t=Sum("quantity_tonnes"))["t"]
        or ZERO
    )
    return made - sent


def validate_new_dispatch(*, grid, product, factory, quantity_tonnes, requirement=None, purchase_order=None):
    quantity_tonnes = Decimal(quantity_tonnes)
    if product.form != "processed":
        raise ValidationError("Only processed products can be dispatched.")
    if quantity_tonnes <= 0:
        raise ValidationError("The quantity must be more than zero.")
    available = available_to_dispatch(grid, product)
    if quantity_tonnes > available:
        raise ValidationError(f"Only {available} t of {product} is available at this Grid.")
    if requirement is not None and (requirement.factory_id != factory.pk or requirement.product_id != product.pk):
        raise ValidationError("That requirement is for a different factory or product.")
    if purchase_order is not None:
        if purchase_order.state != "open":
            raise ValidationError(f"{purchase_order.code} is {purchase_order.get_state_display().lower()}, so nothing more can be sent against it.")
        if purchase_order.factory_id != factory.pk or purchase_order.line.product_id != product.pk:
            raise ValidationError(f"{purchase_order.code} is for a different plant or product.")


def announce_dispatch(dispatch):
    """Write the start of a dispatch's journey to the ledger."""
    return chain.append(
        "dispatch.created",
        dispatch,
        {
            "code": dispatch.code,
            "grid": dispatch.grid.code,
            "hub": dispatch.hub.code if dispatch.hub else None,
            "product": str(dispatch.product),
            "factory": dispatch.factory.code,
            "purchase_order": dispatch.purchase_order.code if dispatch.purchase_order_id else None,
            "quantity_tonnes": dispatch.quantity_tonnes,
            "vehicle_ref": dispatch.vehicle_ref,
        },
    )


@transaction.atomic
def create_dispatch(*, grid, product, factory, quantity_tonnes, mitra=None, requirement=None, purchase_order=None, vehicle_ref="", note=""):
    validate_new_dispatch(
        grid=grid, product=product, factory=factory, quantity_tonnes=quantity_tonnes, requirement=requirement,
        purchase_order=purchase_order,
    )
    dispatch = Dispatch.objects.create(
        grid=grid,
        hub=grid.hub,
        product=product,
        factory=factory,
        requirement=requirement,
        purchase_order=purchase_order,
        created_by_mitra=mitra,
        quantity_tonnes=Decimal(quantity_tonnes),
        vehicle_ref=vehicle_ref,
        note=note,
    )
    announce_dispatch(dispatch)
    return dispatch


def validate_event(dispatch, event_type, quantity_tonnes=None):
    """Check a step is allowed and return the weight to record for it."""
    if event_type not in ALLOWED.get(dispatch.stage, set()):
        raise ValidationError(f"A dispatch that is '{dispatch.get_stage_display()}' cannot take this step.")
    if event_type == EventType.CANCELLED:
        return dispatch.current_quantity_tonnes
    else:
        if quantity_tonnes in (None, ""):
            raise ValidationError("Enter the weight taken at this step.")
        weighed = Decimal(quantity_tonnes)
        if weighed <= 0:
            raise ValidationError("The weight must be more than zero.")
        if weighed > dispatch.current_quantity_tonnes:
            raise ValidationError(
                f"The weight ({weighed} t) is more than the last weight ({dispatch.current_quantity_tonnes} t). "
                "A lot cannot gain weight on the way."
            )
        return weighed


@transaction.atomic
def record_event(dispatch, event_type, *, quantity_tonnes=None, occurred_at=None, vehicle_ref="", note=""):
    dispatch = Dispatch.objects.select_for_update().get(pk=dispatch.pk)
    weighed = validate_event(dispatch, event_type, quantity_tonnes)
    loss = dispatch.current_quantity_tonnes - weighed
    event = DispatchEvent.objects.create(
        dispatch=dispatch,
        event_type=event_type,
        quantity_tonnes=None if event_type == EventType.CANCELLED else weighed,
        occurred_at=occurred_at or timezone.now(),
        vehicle_ref=vehicle_ref,
        note=note,
    )
    dispatch.stage = STAGE_AFTER[event_type]
    dispatch.current_quantity_tonnes = weighed
    dispatch.save()
    entry = chain.append(
        f"dispatch.{event_type}",
        dispatch,
        {
            "code": dispatch.code,
            "weighed_tonnes": weighed,
            "lost_since_last_step_tonnes": loss,
            "stage": dispatch.stage,
            "occurred_at": event.occurred_at,
            "vehicle_ref": vehicle_ref,
        },
    )
    DispatchEvent.objects.filter(pk=event.pk).update(ledger_seq=entry.seq)
    event.ledger_seq = entry.seq
    return event


def average_pickup_rate(grid):
    """Average rupees per tonne paid to farmers for pickups at this Grid, or None if there are none."""
    totals = CollectionRecord.objects.filter(grid=grid, status=Status.ACTIVE).aggregate(
        tonnes=Sum("quantity_tonnes"), paid=Sum("price_paid")
    )
    if not totals["tonnes"]:
        return None
    return totals["paid"] / totals["tonnes"]


def suggested_farmer_payment(dispatch):
    rate = average_pickup_rate(dispatch.grid)
    return money(rate * dispatch.current_quantity_tonnes) if rate is not None else None


def sale_numbers(dispatch, *, sale_value, farmer_payment=None):
    """Work out the money for a sale of a delivered lot. Raises ValidationError if it cannot."""
    if dispatch.stage != DispatchStage.DELIVERED:
        raise ValidationError("A sale can only be recorded once the lot has been delivered.")
    if Sale.objects.filter(dispatch=dispatch).exists():
        raise ValidationError("A sale is already recorded for this dispatch.")
    if sale_value in (None, ""):
        raise ValidationError("Enter the sale value.")
    sale_value = money(sale_value)
    if sale_value < 0:
        raise ValidationError("The sale value cannot be negative.")
    region = dispatch.grid.region
    schedule = FeeSchedule.current_for(region)
    if schedule is None:
        raise ValidationError(f"No fee schedule is in force for {region.code}. Add one under Trade > Fee schedules.")
    estimated = farmer_payment in (None, "")
    if estimated:
        farmer_payment = suggested_farmer_payment(dispatch)
        if farmer_payment is None:
            raise ValidationError("No pickups are recorded at this Grid, so enter the farmer payment by hand.")
    farmer_payment = money(farmer_payment)
    quantity = dispatch.current_quantity_tonnes
    fee = schedule.fee_for_sale(quantity, sale_value)
    return {
        "region": region,
        "quantity_tonnes": quantity,
        "sale_value": sale_value,
        "farmer_payment": farmer_payment,
        "farmer_payment_estimated": estimated,
        "platform_fee": fee,
        "mitra_margin": sale_value - farmer_payment - fee,
        "fee_model": schedule.fee_model,
        "fee_parameters": chain.canonical(schedule.parameters()),
    }


def announce_sale(sale):
    return chain.append(
        "sale.recorded",
        sale,
        {
            "code": sale.code,
            "dispatch": sale.dispatch.code,
            "factory": sale.dispatch.factory.code,
            "quantity_tonnes": sale.quantity_tonnes,
            "sale_value": sale.sale_value,
            "farmer_payment": sale.farmer_payment,
            "farmer_payment_estimated": sale.farmer_payment_estimated,
            "platform_fee": sale.platform_fee,
            "mitra_margin": sale.mitra_margin,
            "fee_model": sale.fee_model,
            "fee_parameters": json.loads(sale.fee_parameters),
        },
    )


@transaction.atomic
def record_sale(dispatch, *, sale_value, farmer_payment=None):
    dispatch = Dispatch.objects.select_for_update().get(pk=dispatch.pk)
    numbers = sale_numbers(dispatch, sale_value=sale_value, farmer_payment=farmer_payment)
    sale = Sale.objects.create(dispatch=dispatch, **numbers)
    announce_sale(sale)
    return sale


@transaction.atomic
def mark_buyer_paid(sale, *, received_on=None, reference=""):
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.buyer_payment == BuyerPayment.RECEIVED:
        raise ValidationError("The buyer's payment is already recorded.")
    sale.buyer_payment = BuyerPayment.RECEIVED
    sale.buyer_paid_on = received_on or date.today()
    sale.payment_reference = reference
    sale.save()
    chain.append(
        "payment.received",
        sale,
        {"code": sale.code, "amount": sale.sale_value, "received_on": sale.buyer_paid_on, "reference": reference},
    )
    return sale


@transaction.atomic
def mark_mitra_settled(sale, *, settled_on=None):
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.buyer_payment != BuyerPayment.RECEIVED:
        raise ValidationError("The buyer has not paid yet, so the Mitra cannot be settled.")
    if sale.mitra_settled_on:
        raise ValidationError("The Mitra has already been settled for this sale.")
    sale.mitra_settled_on = settled_on or date.today()
    sale.save()
    chain.append(
        "settlement.paid",
        sale,
        {"code": sale.code, "mitra_margin": sale.mitra_margin, "settled_on": sale.mitra_settled_on},
    )
    return sale


def lease_terms(grid, period_start, amount=None):
    """Check a lease charge is allowed and return (first day of month, amount, schedule)."""
    schedule = FeeSchedule.current_for(grid.region, period_start)
    if schedule is None or schedule.fee_model != FeeModel.LEASE:
        raise ValidationError(f"{grid.region.code} does not use the lease fee model for that month.")
    period_start = period_start.replace(day=1)
    if LeaseCharge.objects.filter(grid=grid, period_start=period_start).exists():
        raise ValidationError("This month has already been charged for that Grid.")
    amount = money(amount if amount not in (None, "") else schedule.lease_rupees_per_month)
    return period_start, amount, schedule


def announce_lease(charge, schedule):
    return chain.append(
        "lease.charged",
        charge,
        {
            "grid": charge.grid.code,
            "period_start": charge.period_start,
            "amount": charge.amount,
            "schedule": schedule.pk,
        },
    )


@transaction.atomic
def charge_lease(grid, period_start, amount=None):
    period_start, amount, schedule = lease_terms(grid, period_start, amount)
    charge = LeaseCharge.objects.create(grid=grid, period_start=period_start, amount=amount)
    announce_lease(charge, schedule)
    return charge
