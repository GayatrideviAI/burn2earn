"""Who may use the customer pages: a login that belongs to a customer company."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core.models import Status


def get_member(user):
    member = getattr(user, "customer_member", None)
    if member is None or member.status != Status.ACTIVE or member.buyer.status != Status.ACTIVE:
        return None
    return member


def customer_required(view):
    @wraps(view)
    @login_required(login_url="customers:login")
    def wrapper(request, *args, **kwargs):
        member = get_member(request.user)
        if member is None:
            return render(request, "customers/forbidden.html", status=403)
        request.member = member
        request.buyer = member.buyer
        return view(request, *args, **kwargs)

    return wrapper
