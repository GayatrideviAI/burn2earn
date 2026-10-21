from datetime import date

from django.http import Http404
from django.shortcuts import get_object_or_404, render

from apps.core.models import Status
from apps.ledger.chain import entries_for

from . import contracts, services
from .access import customer_required
from .models import Batch, Contract, PurchaseOrder


@customer_required
def dashboard(request):
    s = services.summary(request.buyer)
    supply = contracts.supply_actions(request.buyer)
    return render(
        request,
        "customers/dashboard.html",
        {"buyer": request.buyer, "member": request.member, "s": s, "supply": supply, "lead_days": services.lead_time_days(),
         "verify_days": services.verification_days()},
    )


@customer_required
def yard_detail(request, pk):
    s = services.summary(request.buyer)
    rows = [v for v in s.rows if str(v.batch.pile.yard_id) == str(pk)]
    if not rows:
        raise Http404("No stock of yours in this yard.")
    yard = rows[0].batch.pile.yard
    totals = next(y for y in s.yards if y["yard"].pk == yard.pk)
    return render(request, "customers/yard.html", {"buyer": request.buyer, "yard": yard, "rows": rows, "totals": totals})


@customer_required
def batch_detail(request, pk):
    batch = get_object_or_404(Batch.objects.select_related("pile__yard", "biomass_type"), pk=pk, customer=request.buyer)
    view = services.batch_view(batch, limit=services.plant_limit(request.buyer))
    return render(
        request,
        "customers/batch.html",
        {
            "buyer": request.buyer,
            "batch": batch,
            "v": view,
            "transactions": batch.transactions.filter(status=Status.ACTIVE),
            "counts": batch.counts.filter(status=Status.ACTIVE),
            "quality": batch.quality.filter(status=Status.ACTIVE),
            "trail": entries_for(batch),
        },
    )


@customer_required
def contract_list(request):
    contracts_ = [
        contracts.contract_progress(c)
        for c in Contract.objects.filter(customer=request.buyer, status=Status.ACTIVE).prefetch_related("lines")
    ]
    actions = contracts.supply_actions(request.buyer)
    return render(request, "customers/contracts.html", {"buyer": request.buyer, "items": contracts_, "actions": actions})


@customer_required
def contract_detail(request, pk):
    contract = get_object_or_404(Contract, pk=pk, customer=request.buyer)
    progress = contracts.contract_progress(contract)
    orders = [
        contracts.order_progress(o)
        for o in PurchaseOrder.objects.filter(line__contract=contract, status=Status.ACTIVE).select_related("factory", "line__product")
    ]
    dispatches = contracts.live_dispatches(purchase_order__line__contract=contract).select_related("grid", "product")
    return render(
        request,
        "customers/contract.html",
        {"buyer": request.buyer, "c": contract, "p": progress, "orders": orders, "who": contracts.provenance(dispatches),
         "today": date.today()},
    )


@customer_required
def order_detail(request, pk):
    order = get_object_or_404(
        PurchaseOrder.objects.select_related("factory", "line__product", "line__contract"), pk=pk, line__contract__customer=request.buyer
    )
    dispatches = list(contracts.live_dispatches(purchase_order=order).select_related("grid", "created_by_mitra").order_by("created_at"))
    for d in dispatches:
        d.delivered_date = contracts.delivered_on(d)
    return render(
        request,
        "customers/order.html",
        {"buyer": request.buyer, "o": order, "p": contracts.order_progress(order), "dispatches": dispatches,
         "who": contracts.provenance(dispatches), "today": date.today()},
    )
