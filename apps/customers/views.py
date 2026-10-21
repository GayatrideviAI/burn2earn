from django.http import Http404
from django.shortcuts import get_object_or_404, render

from apps.core.models import Status
from apps.ledger.chain import entries_for

from . import services
from .access import customer_required
from .models import Batch


@customer_required
def dashboard(request):
    s = services.summary(request.buyer)
    return render(
        request,
        "customers/dashboard.html",
        {"buyer": request.buyer, "member": request.member, "s": s, "lead_days": services.lead_time_days(),
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
