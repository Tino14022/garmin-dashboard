"""Long-run progression toward the goal race.

The dashboard could already see the gap between the longest run on record and
the race distance, but planned nothing. This builds the weekly long-run ladder
that closes it, respecting the two rules that actually matter for injury risk:
grow the long run gradually, and taper before the race instead of peaking at it.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from .formatting import iso, parse_iso, week_start

# A long run should not jump more than this much week to week.
MAX_WEEKLY_GROWTH = 1.10
# Peak long run for a half is usually a little under race distance; the race-day
# taper and adrenaline cover the rest.
PEAK_FRACTION = 0.90
# Every fourth week backs off to let adaptation catch up.
CUTBACK_EVERY = 4
CUTBACK_FRACTION = 0.75
# Final weeks before the race shed volume.
TAPER = [0.70, 0.45]


def longest_run_km(runs: list[dict], since: date | None = None) -> float:
    best = 0.0
    for r in runs:
        d = parse_iso(r.get("date"))
        if since is not None and (d is None or d < since):
            continue
        best = max(best, r.get("distance_km") or 0)
    return round(best, 2)


def build_race_plan(
    runs: list[dict],
    today: date,
    *,
    race_date: date,
    race_distance_km: float,
    week_starts_on: int = 6,
) -> dict | None:
    """Weekly long-run targets from now to race day.

    Returns None once the race has passed — a finished race should not keep
    generating homework.
    """
    days_remaining = (race_date - today).days
    if days_remaining < 0:
        return None

    current = longest_run_km(runs, since=today - timedelta(days=56))
    if current <= 0:
        current = 5.0  # nothing recent to go on; start somewhere sane

    peak = race_distance_km * PEAK_FRACTION
    first_week = week_start(today, week_starts_on)
    last_week = week_start(race_date, week_starts_on)
    week_count = max(0, int((last_week - first_week).days / 7))

    # Weeks available for building, i.e. everything before the taper.
    taper_weeks = min(len(TAPER), week_count)
    build_weeks = max(0, week_count - taper_weeks)

    weeks: list[dict] = []
    distance = current
    for i in range(build_weeks):
        cutback = (i + 1) % CUTBACK_EVERY == 0
        if cutback:
            target = distance * CUTBACK_FRACTION
        else:
            remaining_builds = max(1, build_weeks - i - (build_weeks // CUTBACK_EVERY))
            # Growth needed to reach peak, capped by the safe weekly increase.
            needed = (peak / distance) ** (1 / remaining_builds) if distance > 0 else 1
            target = distance * min(MAX_WEEKLY_GROWTH, max(1.0, needed))
            distance = target
        weeks.append(
            {
                "week_start": iso(first_week + timedelta(weeks=i)),
                "long_run_km": round(min(target, peak), 1),
                "kind": "cutback" if cutback else "build",
            }
        )

    for j, fraction in enumerate(TAPER[len(TAPER) - taper_weeks :]):
        weeks.append(
            {
                "week_start": iso(first_week + timedelta(weeks=build_weeks + j)),
                "long_run_km": round(peak * fraction, 1),
                "kind": "taper",
            }
        )

    weeks.append(
        {
            "week_start": iso(last_week),
            "long_run_km": round(race_distance_km, 1),
            "kind": "race",
        }
    )

    planned_peak = max((w["long_run_km"] for w in weeks if w["kind"] != "race"), default=0)
    # Is the ladder actually reachable at a safe growth rate, or is the athlete
    # already too far behind to arrive at the peak without over-jumping?
    safe_weeks_needed = (
        math.ceil(math.log(peak / current) / math.log(MAX_WEEKLY_GROWTH))
        if current > 0 and peak > current
        else 0
    )
    on_track = build_weeks >= safe_weeks_needed

    return {
        "current_longest_km": current,
        "race_distance_km": race_distance_km,
        "peak_long_run_km": round(peak, 1),
        "planned_peak_km": planned_peak,
        "days_remaining": days_remaining,
        "build_weeks": build_weeks,
        "weeks_needed_at_safe_growth": safe_weeks_needed,
        "on_track": on_track,
        "next_long_run_km": weeks[0]["long_run_km"] if weeks else None,
        "weeks": weeks,
    }
