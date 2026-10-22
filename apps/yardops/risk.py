"""Rule-based risk for each pile: heating (fire) and wet or damp storage.

This is deliberately plain rules, not a trained model. The product spec says a prediction model
should wait until there is real yard data, and that the temperature steps and other limits must be
validated for baled paddy straw with a qualified fire-safety partner. The numbers live in
settings.py (YARD_*), so they can be changed without touching this file.

Every result lists its reasons, so the person looking at a pile can see why it is flagged. A pile
with no recent reading is never shown as safe: it shows as "needs attention".
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.models import Status
from apps.customers import services as stock
from apps.customers.models import Batch

from .models import HeatReading, PileInspection

OK, ATTENTION, WATCH, ACT, EMERGENCY = range(5)

LABELS = [
    gettext_lazy("Normal"),
    gettext_lazy("Needs attention"),
    gettext_lazy("Watch closely"),
    gettext_lazy("Check twice a day"),
    gettext_lazy("Fire likely"),
]
TAGS = ["good", "warn", "warn", "bad", "bad"]
ACTIONS = [
    "",
    gettext_lazy("Probe the stack today and look it over."),
    gettext_lazy("Inspect the stack today and probe it twice a day."),
    gettext_lazy("Check twice a day and open up the stack. Keep the fire service number ready."),
    gettext_lazy("Fire is likely. Call the fire service before disturbing the stack."),
]
ALERT_KEYS = {WATCH: "watch", ACT: "act", EMERGENCY: "emergency"}

HISTORY_DAYS = 7
INSPECTION_VALID_DAYS = 14


@dataclass
class Reason:
    level: int
    text: str


@dataclass
class Assessment:
    pile: object
    has_stock: bool = True
    reasons: list = field(default_factory=list)
    latest: object = None          # the most recent HeatReading, whatever its age
    hottest: object = None         # the hottest of the latest reading at each spot
    rise_per_day: float = None
    days_to_watch: float = None
    oldest_received: object = None
    batches: list = field(default_factory=list)

    @property
    def level(self):
        return max([r.level for r in self.reasons], default=OK)

    @property
    def label(self):
        return str(LABELS[self.level])

    @property
    def tag(self):
        return TAGS[self.level]

    @property
    def action(self):
        return str(ACTIONS[self.level])

    @property
    def top_reason(self):
        top = sorted(self.reasons, key=lambda r: -r.level)
        return top[0].text if top else ""

    @property
    def projection(self):
        if self.days_to_watch is None:
            return ""
        return _("At this rate it reaches %(limit)s °C in about %(days)s days (an estimate from the last readings).") % {
            "limit": settings.YARD_HEAT_WATCH_C, "days": max(round(self.days_to_watch), 0) or 1,
        }


def _fmt(value):
    return f"{value:.1f}".rstrip("0").rstrip(".")


def slope_per_day(readings):
    """Straight-line rise in °C per day through readings that are oldest-first, or None if too few."""
    if len(readings) < 2:
        return None
    start = readings[0].taken_at
    xs = [(r.taken_at - start).total_seconds() / 86400 for r in readings]
    ys = [float(r.temperature_c) for r in readings]
    if xs[-1] < 0.25:  # readings under six hours apart say little about a trend
        return None
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / spread


def _age_text(then, now):
    days = (now - then).days
    if days >= 1:
        return _("%(n)s days ago") % {"n": days}
    hours = int((now - then).total_seconds() // 3600)
    return _("%(n)s hours ago") % {"n": hours} if hours >= 1 else _("just now")


def assess(pile, now=None):
    now = now or timezone.now()
    batches = [b for b in Batch.objects.filter(pile=pile, status=Status.ACTIVE) if stock.book_tonnes(b) > 0]
    result = Assessment(pile=pile, has_stock=bool(batches), batches=batches)
    if not batches:
        return result
    result.oldest_received = min(b.received_on for b in batches)
    reasons = result.reasons
    s = settings

    recent = list(
        HeatReading.objects.filter(pile=pile, status=Status.ACTIVE, taken_at__gte=now - timedelta(days=HISTORY_DAYS), taken_at__lte=now)
        .order_by("taken_at")
    )
    result.latest = (
        HeatReading.objects.filter(pile=pile, status=Status.ACTIVE, taken_at__lte=now).order_by("-taken_at").first()
    )

    # Temperature: the hottest of the latest reading at each spot. A probe only speaks for its own spot.
    by_spot = {}
    for r in recent:
        by_spot[r.spot] = r
    if by_spot:
        hottest = max(by_spot.values(), key=lambda r: r.temperature_c)
        result.hottest = hottest
        t = hottest.temperature_c
        when = _age_text(hottest.taken_at, now)
        steps = [
            (EMERGENCY, s.YARD_HEAT_EMERGENCY_C, _("Temperature is %(t)s °C (%(when)s), at or above %(limit)s °C: fire is likely.")),
            (ACT, s.YARD_HEAT_ACT_C, _("Temperature is %(t)s °C (%(when)s), at or above %(limit)s °C.")),
            (WATCH, s.YARD_HEAT_WATCH_C, _("Temperature is %(t)s °C (%(when)s), at or above %(limit)s °C.")),
            (ATTENTION, s.YARD_HEAT_WARM_C, _("Temperature is %(t)s °C (%(when)s), at or above %(limit)s °C.")),
        ]
        for level, limit, text in steps:
            if t >= limit:
                reasons.append(Reason(level, text % {"t": _fmt(t), "when": when, "limit": limit}))
                break
        series = [r for r in recent if r.spot == hottest.spot]
        rise = slope_per_day(series)
        if rise is not None:
            result.rise_per_day = round(rise, 1)
            if rise >= s.YARD_HEAT_RISE_C_PER_DAY:
                reasons.append(Reason(
                    WATCH if t >= 40 else ATTENTION,
                    _("Temperature is rising by about %(rise)s °C a day.") % {"rise": _fmt(rise)},
                ))
            elif rise >= 0.5 and t < s.YARD_HEAT_WATCH_C:
                days = (s.YARD_HEAT_WATCH_C - float(t)) / rise
                if days <= 14:
                    result.days_to_watch = days

    # A pile nobody has probed recently is never read as safe.
    if result.latest is None:
        reasons.append(Reason(ATTENTION, _("No temperature reading has been taken yet.")))
    elif now - result.latest.taken_at > timedelta(days=s.YARD_READING_MAX_AGE_DAYS):
        reasons.append(Reason(ATTENTION, _("No temperature reading for %(n)s days.") % {"n": (now - result.latest.taken_at).days}))

    # Walk-round findings. The latest inspection speaks until a newer one replaces it.
    inspection = (
        PileInspection.objects.filter(pile=pile, status=Status.ACTIVE, inspected_at__lte=now,
                                      inspected_at__gte=now - timedelta(days=INSPECTION_VALID_DAYS))
        .order_by("-inspected_at").first()
    )
    if inspection:
        if inspection.steam_or_smell:
            reasons.append(Reason(ACT, _("The last inspection found steam or a burnt or musty smell.")))
        if inspection.looks_wet:
            reasons.append(Reason(WATCH, _("The last inspection found the stack wet.")))
        if inspection.mould:
            reasons.append(Reason(ATTENTION, _("The last inspection found mould.")))
        if not inspection.cover_in_place and pile.exposure != "protected":
            reasons.append(Reason(ATTENTION, _("The cover was not in place at the last inspection.")))

    # How the stack was built.
    damp = [b for b in batches if b.intake_moisture_percent is not None and b.intake_moisture_percent > s.YARD_DAMP_INTAKE_PERCENT]
    if damp:
        worst = max(b.intake_moisture_percent for b in damp)
        reasons.append(Reason(ATTENTION, _("Stacked damp: %(m)s%% moisture at intake, above %(limit)s%%.") % {"m": _fmt(worst), "limit": s.YARD_DAMP_INTAKE_PERCENT}))
    if pile.height_m is not None and pile.height_m > s.YARD_MAX_STACK_HEIGHT_M:
        reasons.append(Reason(ATTENTION, _("The stack is %(h)s m high, above the %(limit)s m limit.") % {"h": _fmt(pile.height_m), "limit": s.YARD_MAX_STACK_HEIGHT_M}))

    reasons.sort(key=lambda r: -r.level)
    return result


def assess_piles(piles, now=None):
    return [assess(p, now) for p in piles]


def assessments_for_buyer(buyer, now=None):
    """Every pile holding this customer's stock, riskiest first (oldest stock first among equals)."""
    piles = {}
    for batch in Batch.objects.filter(customer=buyer, status=Status.ACTIVE).select_related("pile__yard"):
        piles[batch.pile_id] = batch.pile
    rows = [a for a in assess_piles(piles.values(), now) if a.has_stock]
    rows.sort(key=lambda a: (-a.level, a.oldest_received))
    return rows


def use_first(buyer, limit=5, now=None):
    """Which stock to burn first: the riskiest piles, then the oldest. Not plain first-in-first-out."""
    return assessments_for_buyer(buyer, now)[:limit]


def risk_actions(buyer, now=None):
    """Rows for the customer's 'what to do next' list: (tag, title, text, batch)."""
    rows = []
    for a in assessments_for_buyer(buyer, now):
        if a.level >= ATTENTION and a.reasons:
            batch = next((b for b in a.batches if b.customer_id == buyer.pk), None)
            rows.append((a.tag, a.label, f"{a.pile}: {a.top_reason}", batch))
    return rows


def spark_points(readings, width=240, height=48):
    """Points for a small SVG line of temperature over time. Readings may be in any order."""
    pts = sorted(readings, key=lambda r: r.taken_at)
    if len(pts) < 2:
        return ""
    t0, t1 = pts[0].taken_at.timestamp(), pts[-1].taken_at.timestamp()
    low, high = min(float(r.temperature_c) for r in pts), max(float(r.temperature_c) for r in pts)
    span_t, span_v = (t1 - t0) or 1, (high - low) or 1
    pad = 4
    out = []
    for r in pts:
        x = pad + (r.taken_at.timestamp() - t0) / span_t * (width - 2 * pad)
        y = height - pad - (float(r.temperature_c) - low) / span_v * (height - 2 * pad)
        out.append(f"{x:.1f},{y:.1f}")
    return " ".join(out)
