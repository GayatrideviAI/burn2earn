"""Logging collections and outputs, and the running tallies built from them."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Count, Sum

from apps.core.models import Status

from .models import CollectionRecord, ProcessedOutput

ZERO = Decimal("0")


class NoGridAssigned(Exception):
    """The Mitra has no current Grid, so there is no site to record against."""


def log_collection(
    *, mitra, farmer, biomass_type, quantity_tonnes, price_paid, plot=None, collected_on=None, notes="", pk=None
):
    grid = mitra.current_grid
    if grid is None:
        raise NoGridAssigned("This Mitra has no Grid assigned yet.")
    record = CollectionRecord(
        **({"id": pk} if pk else {}),
        mitra=mitra,
        grid=grid,
        farmer=farmer,
        plot=plot,
        biomass_type=biomass_type,
        quantity_tonnes=quantity_tonnes,
        price_paid=price_paid,
        collected_on=collected_on or date.today(),
        notes=notes,
    )
    record.full_clean(exclude=["code"])
    record.save()
    return record


def submit_output(
    *, mitra, product, quantity_tonnes, biomass_used_tonnes=None, produced_on=None, notes="", pk=None
):
    grid = mitra.current_grid
    if grid is None:
        raise NoGridAssigned("This Mitra has no Grid assigned yet.")
    output = ProcessedOutput(
        **({"id": pk} if pk else {}),
        mitra=mitra,
        grid=grid,
        product=product,
        quantity_tonnes=quantity_tonnes,
        biomass_used_tonnes=biomass_used_tonnes,
        produced_on=produced_on or date.today(),
        notes=notes,
    )
    output.full_clean(exclude=["code"])
    output.save()
    return output


@dataclass
class Tally:
    collections: int = 0
    collected_tonnes: Decimal = ZERO
    paid: Decimal = ZERO
    used_tonnes: Decimal = ZERO
    processed_tonnes: Decimal = ZERO
    by_biomass: list = field(default_factory=list)  # (name, tonnes)
    by_product: list = field(default_factory=list)  # (name, tonnes)

    @property
    def on_hand_tonnes(self):
        """Residue collected and not yet reported as used in processing."""
        return self.collected_tonnes - self.used_tonnes

    @property
    def average_rate(self):
        if not self.collected_tonnes:
            return None
        return (self.paid / self.collected_tonnes).quantize(Decimal("0.01"))


def tally(*, grid=None, hub=None, year=None):
    """Running totals of what was collected and made, for a Grid, a Hub, or everything."""
    collections = CollectionRecord.objects.filter(status=Status.ACTIVE)
    outputs = ProcessedOutput.objects.filter(status=Status.ACTIVE)
    if grid is not None:
        collections, outputs = collections.filter(grid=grid), outputs.filter(grid=grid)
    if hub is not None:
        collections, outputs = collections.filter(grid__hub=hub), outputs.filter(grid__hub=hub)
    if year is not None:
        collections = collections.filter(collected_on__year=year)
        outputs = outputs.filter(produced_on__year=year)

    totals = collections.aggregate(n=Count("id"), tonnes=Sum("quantity_tonnes"), paid=Sum("price_paid"))
    made = outputs.aggregate(tonnes=Sum("quantity_tonnes"), used=Sum("biomass_used_tonnes"))
    result = Tally(
        collections=totals["n"] or 0,
        collected_tonnes=totals["tonnes"] or ZERO,
        paid=totals["paid"] or ZERO,
        used_tonnes=made["used"] or ZERO,
        processed_tonnes=made["tonnes"] or ZERO,
    )
    result.by_biomass = [
        (row["biomass_type__name"], row["tonnes"])
        for row in collections.values("biomass_type__name").annotate(tonnes=Sum("quantity_tonnes")).order_by("biomass_type__name")
    ]
    result.by_product = [
        (row["product__name"] + (f" ({row['product__grade']})" if row["product__grade"] else ""), row["tonnes"])
        for row in outputs.values("product__name", "product__grade").annotate(tonnes=Sum("quantity_tonnes")).order_by("product__name")
    ]
    return result
