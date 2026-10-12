"""Human-readable running codes such as FRM-000042."""

from django.db import transaction

from .models import Counter


def next_code(name, prefix, width=6):
    """Return the next code in the named series (``FRM-000001``, ``FRM-000002``...).

    The counter row is locked while it is incremented, so two people registering at
    the same moment never get the same code.
    """
    with transaction.atomic():
        Counter.objects.get_or_create(name=name)
        counter = Counter.objects.select_for_update().get(name=name)
        counter.value += 1
        counter.save(update_fields=["value"])
    return f"{prefix}-{counter.value:0{width}d}"
