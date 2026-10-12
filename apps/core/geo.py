"""Spatial helpers. Land area is always handled in acres."""

from decimal import ROUND_HALF_UP, Decimal

# WGS 84 / NSIDC EASE-Grid 2.0 Global: a cylindrical equal-area projection, so
# polygon areas measured in it are correct anywhere on Earth.
EQUAL_AREA_SRID = 6933
SQUARE_METRES_PER_ACRE = Decimal("4046.8564224")


def area_acres(geometry):
    """Area of a lon/lat (EPSG:4326) geometry in acres, rounded to 2 decimals."""
    if geometry.srid is None:
        raise ValueError("Geometry needs an SRID to measure its area.")
    projected = geometry.transform(EQUAL_AREA_SRID, clone=True)
    acres = Decimal(str(projected.area)) / SQUARE_METRES_PER_ACRE
    return acres.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
