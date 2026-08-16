"""The single quality scale the whole app speaks.

Before this, each module invented its own vocabulary — body composition graded
things optimal/normal/fair/low/high, insights used good/info/warn, readiness
used high/moderate/low, and Garmin hands back excellent/good/fair/poor. Every
one of those was coloured by hand at the point of use, so the same idea could
appear in three different colours on three tabs.

Everything now maps onto five ranks, best to worst, and the page colours by
rank alone:

    excellent   bright green   comfortably better than it needs to be
    good        green          where you want it
    fair        orange         acceptable, worth an eye on
    bad         red            outside the range, act on it
    terrible    deep red       well outside, act now

Orange rather than yellow for `fair` is deliberate: yellow is used for the fat
macro in charts, and a status colour must never collide with a data colour.
"""
from __future__ import annotations

EXCELLENT = "excellent"
GOOD = "good"
FAIR = "fair"
BAD = "bad"
TERRIBLE = "terrible"

# Best to worst. Index doubles as a sort key for "show me the worst first".
RANKS = [EXCELLENT, GOOD, FAIR, BAD, TERRIBLE]
RANK_ORDER = {r: i for i, r in enumerate(RANKS)}

LABELS = {
    EXCELLENT: "Excellent",
    GOOD: "Good",
    FAIR: "Fair",
    BAD: "Poor",
    TERRIBLE: "Very poor",
}

# 0-100 score cutoffs, applied top-down.
SCORE_BANDS = [(85, EXCELLENT), (70, GOOD), (50, FAIR), (30, BAD)]
# Percentile cutoffs — being above average is good, not excellent.
PERCENTILE_BANDS = [(90, EXCELLENT), (65, GOOD), (35, FAIR), (15, BAD)]


def from_score(score: float | None) -> str | None:
    """Rank a 0-100 score where higher is better."""
    if score is None:
        return None
    for threshold, rank in SCORE_BANDS:
        if score >= threshold:
            return rank
    return TERRIBLE


def from_percentile(percentile: float | None) -> str | None:
    if percentile is None:
        return None
    for threshold, rank in PERCENTILE_BANDS:
        if percentile >= threshold:
            return rank
    return TERRIBLE


def from_severity(severity: str | None) -> str:
    """Findings carry a severity; map it onto the shared scale."""
    return {"good": GOOD, "info": FAIR, "warn": BAD, "bad": TERRIBLE}.get(severity, FAIR)


# The body panel's reference bands, expressed in the shared vocabulary. `normal`
# and `fair` both mean "inside the range but not notably good", which is `fair`.
_STATUS_MAP = {
    "optimal": EXCELLENT,
    "good": GOOD,
    "normal": GOOD,
    "fair": FAIR,
    "low": BAD,
    "high": BAD,
    "very_high": TERRIBLE,
    "very_low": TERRIBLE,
}


def from_status(status: str | None) -> str:
    return _STATUS_MAP.get(status, FAIR)


# Garmin's own sleep-quality words come back on every night.
_QUALITY_MAP = {
    "EXCELLENT": EXCELLENT,
    "GOOD": GOOD,
    "FAIR": FAIR,
    "POOR": BAD,
    "VERY_POOR": TERRIBLE,
}


def from_quality(quality: str | None) -> str | None:
    if not quality:
        return None
    return _QUALITY_MAP.get(str(quality).upper().replace(" ", "_"))


def worst(ranks) -> str | None:
    """The worst rank in a collection — what a summary tile should show."""
    present = [r for r in ranks if r in RANK_ORDER]
    return max(present, key=lambda r: RANK_ORDER[r]) if present else None
