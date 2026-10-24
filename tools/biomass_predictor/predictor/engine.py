"""Turns what the vision model saw into tonnes of CBG and pellets, with a range.

The photo gives sizes and counts. Everything after that is plain arithmetic on the factors in
factors.py. The range comes from changing one uncertain input at a time to its low and high
value and combining the effects in quadrature (the usual way to combine independent errors).
"""

import math
from dataclasses import dataclass

from .factors import CBG_REFERENCE_MOISTURE, FACTORS, SIZE_CONFIDENCE_SPREAD

MAX_BALES = 5000
MAX_AREA_ACRES = 500
PLAUSIBLE_BALE_KG = (5, 700)


class BadReading(ValueError):
    """The vision output cannot be used; the message is safe to show the user."""


@dataclass(frozen=True)
class Q:
    """A quantity with a low, likely and high value."""

    low: float
    likely: float
    high: float

    @staticmethod
    def spread(value, fraction):
        return Q(value * (1 - fraction), value, value * (1 + fraction))


def _num(raw, name, lo, hi):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise BadReading(f"The photo reading had no usable {name}.")
    if not math.isfinite(value) or value < lo or value > hi:
        raise BadReading(f"The photo reading gave an unlikely {name} ({value:g}).")
    return value


def _factor(key):
    f = FACTORS[key]
    return Q(f.low, f.likely, f.high)


def _moisture(look):
    return _factor({"dry": "moisture_dry", "damp": "moisture_damp", "wet": "moisture_wet"}.get(look, "moisture_damp"))


def _count(reading):
    likely = _num(reading.get("count"), "bale count", 1, MAX_BALES)
    low = _num(reading.get("count_low", likely), "lowest bale count", 1, MAX_BALES)
    high = _num(reading.get("count_high", likely), "highest bale count", 1, MAX_BALES)
    return Q(min(low, likely), likely, max(high, likely))


def _bale_kg(reading, known_bale_kg):
    """Weight of one bale as a Q, and the notes about how it was got."""
    if known_bale_kg:
        return Q.spread(_num(known_bale_kg, "bale weight", *PLAUSIBLE_BALE_KG), 0.05), "Bale weight was given by you."
    spread = SIZE_CONFIDENCE_SPREAD.get(reading.get("size_confidence"), SIZE_CONFIDENCE_SPREAD["low"])
    shape = reading.get("shape")
    length = _num(reading.get("length_cm"), "bale length", 20, 400)
    width = _num(reading.get("width_cm"), "bale width", 20, 400)
    if shape == "round":
        volume = math.pi * (width / 100 / 2) ** 2 * (length / 100)
        density = _factor("density_round")
    else:
        height = _num(reading.get("height_cm"), "bale height", 20, 400)
        volume = (length / 100) * (width / 100) * (height / 100)
        density = _factor("density_rect")
    # A size error shows up in all three dimensions, so volume is about twice as uncertain.
    vol_spread = min(0.8, 2 * spread)
    volume_q = Q.spread(volume, vol_spread)
    kg = Q(volume_q.low * density.low, volume_q.likely * density.likely, volume_q.high * density.high)
    return kg, "Bale weight worked out from its size and typical density."


def _conversion(straw_kg, moisture, cbg_ratio, pellet_moisture, recovery, carbon_per_dry_t):
    """straw_kg is weight as found. Returns (cbg_tonnes, pellet_tonnes)."""
    dry_t = straw_kg * (1 - moisture) / 1000
    reference_dry_per_cbg = cbg_ratio * (1 - CBG_REFERENCE_MOISTURE)
    cbg = dry_t / reference_dry_per_cbg
    pellets = dry_t * recovery / (1 - pellet_moisture)
    return cbg, pellets, dry_t * carbon_per_dry_t


def _combine(likely_out, ups, downs):
    up = math.sqrt(sum(u * u for u in ups))
    down = math.sqrt(sum(d * d for d in downs))
    return Q(likely_out * math.exp(-down), likely_out, likely_out * math.exp(up))


def _times(a, b):
    """Product of two independent uncertain quantities."""
    down = math.sqrt(math.log(a.likely / a.low) ** 2 + math.log(b.likely / b.low) ** 2)
    up = math.sqrt(math.log(a.high / a.likely) ** 2 + math.log(b.high / b.likely) ** 2)
    likely = a.likely * b.likely
    return Q(likely * math.exp(-down), likely, likely * math.exp(up))


def _safe_times(a, b):
    if a.likely == 0 or b.likely == 0:
        return Q(0.0, 0.0, 0.0)
    return _times(a, b)


def _add(*qs):
    return Q(sum(q.low for q in qs), sum(q.likely for q in qs), sum(q.high for q in qs))


def estimate(mode, reading, known_bale_kg=None, carbon_share=0.0, straw_price=0.0, acres_given=None):
    """mode is "bales" or "field"; reading is the (already parsed) vision JSON."""
    warnings = []
    notes = []
    if mode == "bales":
        section = reading.get("bales") or reading
        count = _count(section)
        per_bale, note = _bale_kg(section, known_bale_kg)
        notes.append(note)
        kg_q = Q(count.low * per_bale.low, count.likely * per_bale.likely, count.high * per_bale.high)
        if not PLAUSIBLE_BALE_KG[0] <= per_bale.likely <= PLAUSIBLE_BALE_KG[1]:
            warnings.append(f"One bale works out at {per_bale.likely:.0f} kg, which is unusual. Check the reference size.")
        # Treat count and per-bale weight as the two uncertain inputs for straw weight.
        inputs = {"count": count, "per_bale_kg": per_bale}
        straw = lambda p: p["count"] * p["per_bale_kg"]
        likely_inputs = {"count": count.likely, "per_bale_kg": per_bale.likely}
        summary = {"bales_counted": round(count.likely), "kg_per_bale": round(per_bale.likely, 1)}
    elif mode == "field":
        section = reading.get("field") or reading
        area = _num(section.get("area_acres"), "area", 0.01, MAX_AREA_ACRES)
        area_low = _num(section.get("area_low", area), "smallest area", 0.01, MAX_AREA_ACRES)
        area_high = _num(section.get("area_high", area), "largest area", 0.01, MAX_AREA_ACRES)
        cover = _num(section.get("coverage_fraction", 1), "straw cover", 0.02, 1)
        cover_low = _num(section.get("coverage_low", cover), "lowest straw cover", 0.02, 1)
        cover_high = _num(section.get("coverage_high", cover), "highest straw cover", 0.02, 1)
        per_acre = _factor("field_t_per_acre")
        inputs = {
            "area": Q(min(area_low, area), area, max(area_high, area)),
            "cover": Q(min(cover_low, cover), cover, max(cover_high, cover)),
            "t_per_acre": per_acre,
        }
        straw = lambda p: p["area"] * p["cover"] * p["t_per_acre"] * 1000
        likely_inputs = {k: v.likely for k, v in inputs.items()}
        summary = {"area_acres": round(area, 2), "straw_cover": round(cover, 2)}
        notes.append("Field mode is much less exact than counting bales.")
    else:
        raise BadReading("Mode must be bales or field.")

    inputs.update(
        moisture=_moisture(reading.get("moisture_look")),
        cbg_ratio=_factor("cbg_straw_ratio"),
        pellet_moisture=_factor("pellet_moisture"),
        recovery=_factor("pellet_recovery"),
        carbon_per_dry_t=_factor("carbon_per_dry_tonne"),
    )
    likely_inputs.update({k: inputs[k].likely for k in ("moisture", "cbg_ratio", "pellet_moisture", "recovery", "carbon_per_dry_t")})

    def run(p):
        kg = straw(p)
        cbg, pel, co2 = _conversion(kg, p["moisture"], p["cbg_ratio"], p["pellet_moisture"], p["recovery"], p["carbon_per_dry_t"])
        return kg / 1000, cbg, pel, co2

    base = run(likely_inputs)
    ups = [[], [], [], []]
    downs = [[], [], [], []]
    for key, q in inputs.items():
        outs = []
        for end in (q.low, q.high):
            trial = dict(likely_inputs)
            trial[key] = end
            outs.append(run(trial))
        for i in range(4):
            lo, hi = min(o[i] for o in outs), max(o[i] for o in outs)
            ups[i].append(math.log(max(hi, base[i]) / base[i]))
            downs[i].append(math.log(base[i] / min(lo, base[i])))
    straw_q, cbg_q, pellet_q, co2_q = (_combine(base[i], ups[i], downs[i]) for i in range(4))

    # Money. Every part rises and falls with the straw weight, so totals add low to low and high to high.
    if acres_given:
        acres = Q.spread(_num(acres_given, "acres", 0.01, MAX_AREA_ACRES), 0.05)
        acres_from = "given"
    elif mode == "field":
        acres = inputs["area"]
        acres_from = "photo"
    else:
        per_acre = _factor("field_t_per_acre")
        acres = Q(straw_q.low / per_acre.high, straw_q.likely / per_acre.likely, straw_q.high / per_acre.low)
        acres_from = "straw weight"
    saved_rs = _safe_times(acres, _factor("clearing_cost"))
    straw_rs = _safe_times(straw_q, Q(straw_price, straw_price, straw_price))
    carbon_rs = _times(co2_q, _factor("carbon_price"))
    carbon_rs = Q(carbon_rs.low * carbon_share, carbon_rs.likely * carbon_share, carbon_rs.high * carbon_share)
    total_rs = _add(saved_rs, straw_rs, carbon_rs)

    if reading.get("moisture_look") in (None, "unknown"):
        warnings.append("The straw's dryness could not be judged, so damp was assumed.")
    if reading.get("residue_type") not in ("paddy", "wheat"):
        warnings.append("The kind of straw was not clear. The factors are based on paddy straw.")
    elif reading.get("residue_type") == "wheat":
        warnings.append("The factors are based on paddy straw; wheat straw has not been sourced yet.")

    def r(q):
        digits = 3 - int(math.floor(math.log10(abs(q.likely)))) - 1 if q.likely else 3
        digits = max(0, min(digits, 6))
        return {"low": round(q.low, digits), "likely": round(q.likely, digits), "high": round(q.high, digits)}

    def money(q):
        step = 10 if q.likely < 10000 else 100
        return {k: int(round(v / step) * step) for k, v in (("low", q.low), ("likely", q.likely), ("high", q.high))}

    return {
        "mode": mode,
        "seen": {**summary, "residue_type": reading.get("residue_type", "unknown"),
                 "moisture_look": reading.get("moisture_look", "unknown")},
        "straw_tonnes": r(straw_q),
        "cbg_tonnes": r(cbg_q),
        "pellet_tonnes": r(pellet_q),
        "co2e_tonnes": r(co2_q),
        "revenue_rs": {"clearing_saved": money(saved_rs), "straw": money(straw_rs), "carbon": money(carbon_rs),
                       "total": money(total_rs), "carbon_share": carbon_share, "straw_price": straw_price,
                       "acres": r(acres), "acres_from": acres_from},
        "warnings": warnings,
        "notes": notes + [reading.get("notes", "")[:300]] if reading.get("notes") else notes,
    }
