"""Who may use the yard pages: a login linked to one or more yards."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core.models import Status


def get_operator(user):
    operator = getattr(user, "yard_operator", None)
    if operator is None or operator.status != Status.ACTIVE:
        return None
    return operator


def yard_required(view):
    @wraps(view)
    @login_required(login_url="yardops:login")
    def wrapper(request, *args, **kwargs):
        operator = get_operator(request.user)
        if operator is None:
            return render(request, "yardops/forbidden.html", status=403)
        request.operator = operator
        request.yards = operator.yards.filter(status=Status.ACTIVE)
        return view(request, *args, **kwargs)

    return wrapper
