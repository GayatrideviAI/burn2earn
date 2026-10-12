from dataclasses import dataclass

from django.db import transaction

from apps.core.models import Status
from apps.geography.models import Panchayat

from .models import GeoCell


@dataclass
class GenerationResult:
    created: int
    already_existing: int
    missing_boundary: int


def generate_panchayat_cells(region):
    """Create one GeoCell per panchayat in the Region's district.

    Panchayats that already have an active cell are left alone, and panchayats
    without a boundary are counted so the caller can report them. Safe to re-run.
    """
    in_district = Panchayat.objects.filter(
        block__district=region.district, status=Status.ACTIVE
    )
    with_boundary = in_district.filter(boundary__isnull=False).order_by("lgd_code")
    already_have_cell = set(
        GeoCell.objects.filter(status=Status.ACTIVE, panchayat__in=with_boundary).values_list(
            "panchayat_id", flat=True
        )
    )

    created = 0
    with transaction.atomic():
        for panchayat in with_boundary:
            if panchayat.pk in already_have_cell:
                continue
            GeoCell(
                code=f"GC-{panchayat.lgd_code}",
                region=region,
                panchayat=panchayat,
                origin=GeoCell.Origin.PANCHAYAT,
                boundary=panchayat.boundary,
            ).save()
            created += 1

    return GenerationResult(
        created=created,
        already_existing=len(already_have_cell),
        missing_boundary=in_district.filter(boundary__isnull=True).count(),
    )
