from apps.core.models import Status
from apps.territory.models import GeoCell


def place_in_geocell(location, boundary=None):
    """Find the active GeoCell a plot belongs to, or None if it is outside every cell.

    With a boundary, a plot that straddles two cells goes to the cell holding the
    larger share of its area. Without one, the cell that contains the point wins.
    """
    cells = GeoCell.objects.filter(status=Status.ACTIVE)
    if boundary is not None:
        candidates = list(cells.filter(boundary__intersects=boundary))
        if candidates:
            return max(candidates, key=lambda cell: cell.boundary.intersection(boundary).area)
    return cells.filter(boundary__covers=location).first()
