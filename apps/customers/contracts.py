"""Contract progress: what was contracted, ordered, sent and delivered, and who supplied it.

Delivered means a dispatch against the order reached the buyer's gate (stage Delivered); the tonnes counted are the
weight taken at the gate, after any loss on the way.

Who supplied it: a lot is made at a Grid from residue many farmers handed to the Mitra, and lots are not tagged
farmer by farmer. So each delivered dispatch is shared out between the farmers who sold that biomass type at that
Grid, in proportion to the tonnes each handed over up to the delivery date. It is a fair attribution, not lot-level proof.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.core.models import Status
from apps.operations.models import CollectionRecord
from apps.trade.models import Dispatch, DispatchEvent, DispatchStage, EventType

from .models import ContractLine, MonthlyPlan, OrderState, PurchaseOrder

ZERO = Decimal("0")
AT_RISK_GAP = Decimal("0.15")  # fall this far behind the share of the period that has passed


def live_dispatches(**filters):
    return Dispatch.objects.filter(status=Status.ACTIVE, **filters).exclude(stage=DispatchStage.CANCELLED)


def delivered_on(dispatch):
    event = DispatchEvent.objects.filter(dispatch=dispatch, event_type=EventType.DELIVERED).order_by("-occurred_at").first()
    return event.occurred_at.date() if event else None


@dataclass
class OrderProgress:
    order: PurchaseOrder
    ordered: Decimal
    delivered: Decimal = ZERO
    on_the_way: Decimal = ZERO

    @property
    def remaining(self):
        return max(self.ordered - self.delivered, ZERO)

    @property
    def over_delivered(self):
        return max(self.delivered - self.ordered, ZERO)

    @property
    def percent(self):
        return int(min(self.delivered / self.ordered, 1) * 100) if self.ordered else 0

    def overdue(self, today=None):
        return self.order.state == OrderState.OPEN and (today or date.today()) > self.order.deliver_by and self.remaining > 0


def order_progress(order):
    p = OrderProgress(order=order, ordered=order.tonnes)
    for d in live_dispatches(purchase_order=order):
        if d.stage == DispatchStage.DELIVERED:
            p.delivered += d.current_quantity_tonnes
        else:
            p.on_the_way += d.current_quantity_tonnes
    return p


def months_between(start, end):
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


@dataclass
class LineProgress:
    line: ContractLine
    ordered: Decimal = ZERO
    delivered: Decimal = ZERO
    on_the_way: Decimal = ZERO
    months: list = field(default_factory=list)  # (month, planned, delivered, delivered minus planned)

    @property
    def percent(self):
        return int(min(self.delivered / self.line.contracted_tonnes, 1) * 100)

    @property
    def not_yet_ordered(self):
        return max(self.line.contracted_tonnes - self.ordered, ZERO)


def line_progress(line, today=None):
    today = today or date.today()
    p = LineProgress(line=line)
    p.ordered = (
        PurchaseOrder.objects.filter(line=line, status=Status.ACTIVE).exclude(state=OrderState.CANCELLED)
        .aggregate(t=Sum("tonnes"))["t"] or ZERO
    )
    per_month = defaultdict(lambda: ZERO)
    for d in live_dispatches(purchase_order__line=line):
        if d.stage == DispatchStage.DELIVERED:
            p.delivered += d.current_quantity_tonnes
            when = delivered_on(d)
            if when:
                per_month[when.replace(day=1)] += d.current_quantity_tonnes
        else:
            p.on_the_way += d.current_quantity_tonnes
    planned = {m.month: m.planned_tonnes for m in MonthlyPlan.objects.filter(line=line, status=Status.ACTIVE)}
    c = line.contract
    for month in months_between(c.start_date, c.end_date):
        want, got = planned.get(month, ZERO), per_month.get(month, ZERO)
        p.months.append((month, want, got, got - want))
    return p


@dataclass
class ContractProgress:
    contract: object
    lines: list
    contracted: Decimal = ZERO
    delivered: Decimal = ZERO
    elapsed: Decimal = ZERO  # share of the period that has passed, 0 to 1

    @property
    def percent(self):
        return int(min(self.delivered / self.contracted, 1) * 100) if self.contracted else 0

    @property
    def at_risk(self):
        return self.contracted > 0 and self.delivered / self.contracted < self.elapsed - AT_RISK_GAP


def contract_progress(contract, today=None):
    today = today or date.today()
    lines = [line_progress(l, today) for l in contract.lines.filter(status=Status.ACTIVE).select_related("product")]
    days = (contract.end_date - contract.start_date).days + 1
    passed = min(max((today - contract.start_date).days + 1, 0), days)
    return ContractProgress(
        contract=contract,
        lines=lines,
        contracted=sum((l.line.contracted_tonnes for l in lines), ZERO),
        delivered=sum((l.delivered for l in lines), ZERO),
        elapsed=Decimal(passed) / Decimal(days),
    )


# ---- who supplied it ---------------------------------------------------------------------------


@dataclass
class Provenance:
    delivered: Decimal = ZERO
    unattributed: Decimal = ZERO
    mitras: dict = field(default_factory=dict)  # Mitra -> tonnes
    farmers: dict = field(default_factory=dict)  # Farmer -> tonnes
    grids: dict = field(default_factory=dict)  # Grid -> tonnes

    @property
    def farmer_rows(self):
        return sorted(self.farmers.items(), key=lambda kv: -kv[1])


def attribution(dispatch):
    """Share one delivered dispatch out among farmers. Returns ({farmer: tonnes}, unattributed_tonnes)."""
    from apps.farms.models import Farmer

    qty = dispatch.current_quantity_tonnes
    until = delivered_on(dispatch) or date.today()
    rows = list(
        CollectionRecord.objects.filter(
            grid=dispatch.grid, biomass_type=dispatch.product.biomass_type, status=Status.ACTIVE, collected_on__lte=until
        ).values("farmer").annotate(t=Sum("quantity_tonnes"))
    )
    total = sum((r["t"] for r in rows), ZERO)
    if total == 0:
        return {}, qty
    farmers = Farmer.objects.select_related("village").in_bulk([r["farmer"] for r in rows])
    return {farmers[r["farmer"]]: qty * r["t"] / total for r in rows}, ZERO


def provenance(dispatches):
    result = Provenance()
    for d in dispatches:
        if d.stage != DispatchStage.DELIVERED or d.status != Status.ACTIVE:
            continue
        qty = d.current_quantity_tonnes
        result.delivered += qty
        mitra = d.created_by_mitra or d.grid.current_mitra
        if mitra is not None:
            result.mitras[mitra] = result.mitras.get(mitra, ZERO) + qty
        result.grids[d.grid] = result.grids.get(d.grid, ZERO) + qty
        shares, unattributed = attribution(d)
        result.unattributed += unattributed
        for farmer, t in shares.items():
            result.farmers[farmer] = result.farmers.get(farmer, ZERO) + t
    return result


# ---- from delivery to yard, and the full chain ------------------------------------------------


def dispatch_receipts(dispatch):
    """What was put into yards from a delivered load: (received_tonnes, batches, still_to_receive)."""
    from .models import Batch, unreceived_tonnes

    batches = list(Batch.objects.filter(source_dispatch=dispatch, status=Status.ACTIVE).select_related("pile__yard"))
    return sum((b.intake_tonnes for b in batches), ZERO), batches, unreceived_tonnes(dispatch)


@dataclass
class Origin:
    batch: object
    dispatch: object = None
    order: object = None
    contract: object = None
    mitra: object = None
    share: Decimal = ZERO  # this batch's part of the delivered load, 0 to 1
    farmers: list = field(default_factory=list)  # (farmer, tonnes attributed to this batch)
    unattributed: Decimal = ZERO
    consumed: Decimal = ZERO
    lost: Decimal = ZERO
    lost_by_cause: dict = field(default_factory=dict)


def batch_origin(batch):
    """Everything between the farmer and this yard batch, and what has happened to it since."""
    from .models import InventoryTransaction, TransactionKind

    o = Origin(batch=batch)
    for t in InventoryTransaction.objects.filter(batch=batch, status=Status.ACTIVE):
        if t.kind == TransactionKind.CONSUMPTION:
            o.consumed += -t.tonnes_change
        elif t.kind == TransactionKind.LOSS:
            o.lost += -t.tonnes_change
            o.lost_by_cause[t.get_loss_cause_display()] = o.lost_by_cause.get(t.get_loss_cause_display(), ZERO) - t.tonnes_change
    d = batch.source_dispatch if batch.source_dispatch_id else None
    if d is None:
        return o
    o.dispatch, o.order = d, d.purchase_order
    o.contract = d.purchase_order.line.contract if d.purchase_order_id else None
    o.mitra = d.created_by_mitra or d.grid.current_mitra
    if d.current_quantity_tonnes:
        o.share = batch.intake_tonnes / d.current_quantity_tonnes
    shares, unattributed = attribution(d)
    o.farmers = sorted(((f, t * o.share) for f, t in shares.items()), key=lambda kv: -kv[1])
    o.unattributed = unattributed * o.share
    return o


def farmer_trace(farmer):
    """For staff: where a farmer's residue went. Returns a list of rows, one per delivered load it is attributed to."""
    from .models import Batch

    grid_types = set(
        CollectionRecord.objects.filter(farmer=farmer, status=Status.ACTIVE).values_list("grid", "biomass_type")
    )
    rows = []
    for grid_id, type_id in grid_types:
        for d in live_dispatches(grid_id=grid_id, product__biomass_type_id=type_id, stage=DispatchStage.DELIVERED).select_related(
            "factory__buyer", "purchase_order", "grid"
        ):
            shares, _ = attribution(d)
            mine = shares.get(farmer)
            if not mine:
                continue
            d.delivered_date = delivered_on(d)
            rows.append({"dispatch": d, "tonnes": mine, "batches": [
                (b, mine * b.intake_tonnes / d.current_quantity_tonnes, batch_origin(b))
                for b in Batch.objects.filter(source_dispatch=d, status=Status.ACTIVE).select_related("pile__yard")
            ]})
    rows.sort(key=lambda r: delivered_on(r["dispatch"]) or date.min)
    return rows


# ---- alerts ------------------------------------------------------------------------------------


def supply_actions(buyer, today=None):
    """Delayed orders and contracts that are behind, as (level, title, text, link-object) rows."""
    from .models import Contract

    today = today or date.today()
    out = []
    for order in PurchaseOrder.objects.filter(line__contract__customer=buyer, status=Status.ACTIVE, state=OrderState.OPEN).select_related("line__product", "factory"):
        p = order_progress(order)
        if p.overdue(today):
            out.append(("bad", "Delivery late", f"{order.code} ({order.line.product}) was due by {order.deliver_by:%d %b}; {p.remaining:.1f} t still to come.", order))
    for d in live_dispatches(purchase_order__line__contract__customer=buyer, stage=DispatchStage.DELIVERED).select_related("purchase_order"):
        left = dispatch_receipts(d)[2]
        if left > Decimal("0.05"):
            out.append(("warn", "Not in a yard yet", f"{d.code}: {left:.1f} t was delivered to your gate but is not recorded in any yard.", d.purchase_order))
    for contract in Contract.objects.filter(customer=buyer, status=Status.ACTIVE, end_date__gte=today):
        cp = contract_progress(contract, today)
        if cp.at_risk:
            out.append(("warn", "Contract behind", f"{contract.code} has had {cp.percent}% delivered with {int(cp.elapsed * 100)}% of the period gone.", contract))
    return out
