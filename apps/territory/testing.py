"""Shared helpers for tests that need a Region, panchayats and GeoCells."""

from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import TestCase

from apps.geography.models import Block, District, Panchayat, State

from .models import GeoCell, Region

# Binary-exact values so two squares that should share an edge really do.
SIDE = 0.015625  # 1/64 degree


def square(lon, lat, side=SIDE):
    ring = (
        (lon, lat),
        (lon + side, lat),
        (lon + side, lat + side),
        (lon, lat + side),
        (lon, lat),
    )
    return MultiPolygon(Polygon(ring), srid=4326)


class TerritoryTestCase(TestCase):
    def setUp(self):
        self.state = State.objects.create(lgd_code="6", name="Haryana")
        self.district = District.objects.create(lgd_code="43", name="Ambala", state=self.state)
        self.block = Block.objects.create(lgd_code="401", name="Ambala I", district=self.district)
        self.region = Region.objects.create(
            code="REG-HR-AMB-001", name="Ambala Pilot", state=self.state, district=self.district
        )

    def panchayat(self, code, boundary=None):
        return Panchayat.objects.create(
            lgd_code=code, name=f"P{code}", block=self.block, boundary=boundary
        )

    def cell(self, code, boundary, panchayat=None, **extra):
        return GeoCell.objects.create(
            code=code,
            region=self.region,
            panchayat=panchayat or self.panchayat(f"p-{code}"),
            boundary=boundary,
            **extra,
        )
