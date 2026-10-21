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
        until = delivered_on(d) or date.today()
        rows = (
            CollectionRecord.objects.filter(
                grid=d.grid, biomass_type=d.product.biomass_type, status=Status.ACTIVE, collected_on__lte=until
            )
            .values("farmer").annotate(t=Sum("quantity_tonnes"))
        )
        total = sum((r["t"] for r in rows), ZERO)
        if total == 0:
            result.unattributed += qty
            continue
        from apps.farms.models import Farmer

        farmers = Farmer.objects.in_bulk([r["farmer"] for r in rows])
        for r in rows:
            f = farmers[r["farmer"]]
            result.farmers[f] = result.farmers.get(f, ZERO) + qty * r["t"] / total
    return result


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
    for contract in Contract.objects.filter(customer=buyer, status=Status.ACTIVE, end_date__gte=today):
        cp = contract_progress(contract, today)
        if cp.at_risk:
            out.append(("warn", "Contract behind", f"{contract.code} has had {cp.percent}% delivered with {int(cp.elapsed * 100)}% of the period gone.", contract))
    return out
