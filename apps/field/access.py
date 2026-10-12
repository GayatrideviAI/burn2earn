"""Who may use the Mitra pages, and which farmers they may see."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from apps.farms.models import Farmer
from apps.network.models import MitraOperatingStatus


def get_mitra(user):
    """The Mitra record for this login, or None."""
    return getattr(user, "mitra", None)


def mitra_required(view):
    """Only a Mitra who is pending or active may use the pages. Others get a clear 403."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        mitra = get_mitra(request.user)
        if mitra is None:
            return render(request, "field/forbidden.html", {"reason": "no_mitra"}, status=403)
        if mitra.operating_status in (MitraOperatingStatus.SUSPENDED, MitraOperatingStatus.EXITED):
            return render(request, "field/forbidden.html", {"reason": "not_operating"}, status=403)
        request.mitra = mitra
        return view(request, *args, **kwargs)

    return wrapper


def farmers_visible_to(mitra):
    """Farmers this Mitra registered, plus farmers with land in the Mitra's cells."""
    return Farmer.objects.filter(
        Q(registered_by_mitra=mitra) | Q(plots__geocell__in=mitra.geocells)
    ).distinct()
