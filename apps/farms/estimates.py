"""Supply estimate: how much crop residue the registered land should yield.

Nothing here is stored. The estimate is worked out from plots, the crops recorded for them
and the figures on the Biomass Type, so it changes as soon as any of those do.

    gross  = plot area (acres) x tonnes per acre for that crop's biomass type
    tonnes = gross x (1 - pilferage %)         <- what the Mitra can expect to collect

The tonnes-per-acre figure and the pilferage percentage can be set separately for each state
(Reference > Biomass types). A state with no row uses the Biomass Type's own figure and 0% loss.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from apps.core.models import Status
from apps.reference.models import BiomassType, StateBiomassFactor

from .models import PlotSeason

ZERO = Decimal("0")


@dataclass
class Row:
    label: str
    plots: int = 0
    acres: Decimal = ZERO
    gross: Decimal = ZERO
    tonnes: Decimal = ZERO
    obj: object = None


@dataclass
class Estimate:
    year: int
    cells: list = field(default_factory=list)
    grids: list = field(default_factory=list)
    crops: list = field(default_factory=list)
    total: Row = field(default_factory=lambda: Row("Total"))
    outside_cells: Row = field(default_factory=lambda: Row("Outside every GeoCell"))
    crops_without_figure: list = field(default_factory=list)


def _add(row, acres, gross, tonnes):
    row.plots += 1
    row.acres += acres
    row.gross += gross
    row.tonnes += tonnes


def supply_estimate(year, *, season=None, region=None, grid=None):
    """Estimated collectable biomass for crops sown in `year` (optionally one season)."""
    records = PlotSeason.objects.filter(
        year=year,
        status=Status.ACTIVE,
        plot__status=Status.ACTIVE,
        plot__farmer__status=Status.ACTIVE,
    ).select_related(
        "plot",
        "plot__geocell",
        "plot__geocell__grid",
        "plot__geocell__region",
        "plot__farmer__village__panchayat__block__district",
        "crop",
    )
    if season is not None:
        records = records.filter(season=season)
    if region is not None:
        records = records.filter(plot__geocell__region=region)
    if grid is not None:
        records = records.filter(plot__geocell__grid=grid)

    types_by_crop = {}
    for biomass_type in BiomassType.objects.filter(status=Status.ACTIVE):
        types_by_crop.setdefault(biomass_type.crop_id, []).append(biomass_type)
    state_rows = {
        (row.biomass_type_id, row.state_id): row
        for row in StateBiomassFactor.objects.filter(status=Status.ACTIVE)
    }

    def figures_for(crop_id, state_id):
        """(tonnes per acre, pilferage %) for each biomass type of the crop that has a figure."""
        found = []
        for biomass_type in types_by_crop.get(crop_id, []):
            state_row = state_rows.get((biomass_type.pk, state_id))
            per_acre = biomass_type.estimated_tonnes_per_acre
            loss = ZERO
            if state_row is not None:
                loss = state_row.pilferage_percent
                if state_row.estimated_tonnes_per_acre is not None:
                    per_acre = state_row.estimated_tonnes_per_acre
            if per_acre is not None:
                found.append((per_acre, loss))
        return found

    result = Estimate(year=year)
    cells, grids, crops, missing = {}, {}, {}, set()
    for record in records:
        plot = record.plot
        cell = plot.geocell
        if cell is not None:
            state_id = cell.region.state_id
        else:
            state_id = plot.farmer.village.panchayat.block.district.state_id
        figures = figures_for(record.crop_id, state_id)
        if not figures:
            missing.add(record.crop.name)
            continue
        gross = sum((plot.area_acres * per_acre for per_acre, _ in figures), ZERO)
        net = sum((plot.area_acres * per_acre * (1 - loss / 100) for per_acre, loss in figures), ZERO)
        gross, net = gross.quantize(Decimal("0.01")), net.quantize(Decimal("0.01"))
        _add(result.total, plot.area_acres, gross, net)
        _add(crops.setdefault(record.crop.name, Row(record.crop.name)), plot.area_acres, gross, net)
        if cell is None:
            _add(result.outside_cells, plot.area_acres, gross, net)
            continue
        _add(cells.setdefault(cell.pk, Row(cell.code, obj=cell)), plot.area_acres, gross, net)
        if cell.grid_id:
            _add(grids.setdefault(cell.grid_id, Row(cell.grid.code, obj=cell.grid)), plot.area_acres, gross, net)

    result.cells = sorted(cells.values(), key=lambda row: row.label)
    result.grids = sorted(grids.values(), key=lambda row: row.label)
    result.crops = sorted(crops.values(), key=lambda row: row.label)
    result.crops_without_figure = sorted(missing)
    return result
