"""Rhythm and pattern views: circadian ribbon, punch card, streak quality,
hypnogram wall, body battery, and cumulative training volume per muscle.

These share a shape — they take a series that is already in the payload and
arrange it so the pattern in it becomes visible rather than statistical.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from .formatting import parse_iso, week_start

DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _dow_index(d: date) -> int:
    """Sunday-first index, matching the calendars elsewhere in the app."""
    return (d.weekday() + 1) % 7


def build_circadian(payload: dict, today: date, *, days: int = 28) -> dict | None:
    """Sleep blocks and session times on a 24-hour clock, night by night.

    Bedtime consistency is the strongest signal in this athlete's data and it
    currently exists only as a standard deviation. This is what it looks like.
    """
    sleep = {s["date"]: s for s in payload.get("sleep_trend") or [] if s.get("date")}
    sessions = [s for s in (payload.get("training") or {}).get("sessions") or [] if s.get("date")]
    sessions_by_date: dict[str, list] = {}
    for s in sessions:
        if s.get("hour") is not None:
            sessions_by_date.setdefault(s["date"], []).append(s)

    rows = []
    bedtimes = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        iso = d.isoformat()
        night = sleep.get(iso)
        entry = {"date": iso, "dow": DOW[_dow_index(d)], "sleep": None, "sessions": []}
        if night and night.get("bedtime_hour") is not None and night.get("hours"):
            # bedtime_hour is carried past 24 for after-midnight starts so the
            # evening stays contiguous; keep that convention for plotting.
            start = night["bedtime_hour"]
            entry["sleep"] = {
                "start": round(start, 2),
                "end": round(start + night["hours"], 2),
                "hours": night["hours"],
                "score": night.get("score"),
            }
            bedtimes.append(start)
        for s in sessions_by_date.get(iso, []):
            entry["sessions"].append({
                "hour": s["hour"],
                "type": s.get("type"),
                "duration_min": s.get("duration_min") or 45,
            })
        rows.append(entry)

    if not bedtimes:
        return None
    spread = statistics.pstdev(bedtimes) if len(bedtimes) > 1 else 0
    median = statistics.median(bedtimes)
    return {
        "rows": rows,
        "bedtime_spread_h": round(spread, 2),
        "median_bedtime_h": round(median, 2),
        "consistent": spread < 1.0,
        "nights": len(bedtimes),
    }


def build_punch_card(payload: dict, today: date) -> dict | None:
    """Day-of-week by hour grid of when training actually happens."""
    sessions = [
        s for s in (payload.get("training") or {}).get("sessions") or []
        if s.get("date") and s.get("hour") is not None
    ]
    if not sessions:
        return None
    grid: dict[tuple[int, int], int] = {}
    for s in sessions:
        d = parse_iso(s["date"])
        if not d:
            continue
        key = (_dow_index(d), s["hour"])
        grid[key] = grid.get(key, 0) + 1
    cells = [{"dow": k[0], "hour": k[1], "count": v} for k, v in sorted(grid.items())]
    peak = max((c["count"] for c in cells), default=0)
    by_hour: dict[int, int] = {}
    for c in cells:
        by_hour[c["hour"]] = by_hour.get(c["hour"], 0) + c["count"]
    favourite_hour = max(by_hour, key=by_hour.get) if by_hour else None
    return {
        "cells": cells,
        "peak": peak,
        "sessions": len(sessions),
        "favourite_hour": favourite_hour,
        "dow_labels": DOW,
    }


def build_streak_quality(payload: dict, today: date, *, days: int = 63) -> dict | None:
    """The streak grid, shaded by how much work each day actually held."""
    sessions = [s for s in (payload.get("training") or {}).get("sessions") or [] if s.get("date")]
    if not sessions:
        return None
    by_date: dict[str, dict] = {}
    for s in sessions:
        entry = by_date.setdefault(s["date"], {"minutes": 0, "types": [], "count": 0})
        entry["minutes"] += s.get("duration_min") or 0
        entry["count"] += 1
        if s.get("type"):
            entry["types"].append(s["type"])

    cells = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        iso = d.isoformat()
        e = by_date.get(iso)
        minutes = e["minutes"] if e else 0
        # Four bands rather than a continuous ramp: at a glance you want to see
        # "hard day / normal day / light day / off", not a precise gradient.
        level = 0 if not e else 1 if minutes < 30 else 2 if minutes < 60 else 3 if minutes < 100 else 4
        cells.append({
            "date": iso,
            "dow": _dow_index(d),
            "level": level,
            "minutes": minutes,
            "types": (e or {}).get("types", []),
        })
    trained = [c for c in cells if c["level"] > 0]
    return {
        "cells": cells,
        "weeks": (days + 6) // 7,
        "days_trained": len(trained),
        "days": days,
        "avg_minutes": round(statistics.fmean([c["minutes"] for c in trained])) if trained else 0,
    }


def build_hypnogram(payload: dict, *, nights: int = 21) -> dict | None:
    """Sleep architecture per night — the shape behind the score."""
    rows = [
        s for s in payload.get("sleep_trend") or []
        if s.get("date") and (s.get("deep_min") or s.get("rem_min") or s.get("light_min"))
    ]
    if not rows:
        return None
    rows = sorted(rows, key=lambda s: s["date"])[-nights:]
    out = []
    for s in rows:
        deep = s.get("deep_min") or 0
        light = s.get("light_min") or 0
        rem = s.get("rem_min") or 0
        awake = s.get("awake_min") or 0
        total = deep + light + rem + awake
        out.append({
            "date": s["date"],
            "deep_min": deep, "light_min": light, "rem_min": rem, "awake_min": awake,
            "total_min": total,
            "deep_pct": round(deep / total * 100) if total else 0,
            "rem_pct": round(rem / total * 100) if total else 0,
            "score": s.get("score"),
        })
    deep_avg = statistics.fmean([r["deep_pct"] for r in out])
    rem_avg = statistics.fmean([r["rem_pct"] for r in out])
    return {
        "nights": out,
        # Healthy adult ranges: deep roughly 13-23%, REM roughly 20-25%.
        "avg_deep_pct": round(deep_avg),
        "avg_rem_pct": round(rem_avg),
        "deep_verdict": "low" if deep_avg < 13 else "high" if deep_avg > 23 else "normal",
        "rem_verdict": "low" if rem_avg < 18 else "high" if rem_avg > 27 else "normal",
    }


def build_body_battery(payload: dict, *, days: int = 21) -> dict | None:
    """Overnight recharge per night — how much the night actually paid back."""
    rows = [
        s for s in payload.get("sleep_trend") or []
        if s.get("date") and s.get("body_battery_change") is not None
    ]
    if len(rows) < 3:
        return None
    rows = sorted(rows, key=lambda s: s["date"])[-days:]
    series = [
        {
            "date": s["date"],
            "recharge": s["body_battery_change"],
            "hours": s.get("hours"),
            "score": s.get("score"),
        }
        for s in rows
    ]
    values = [s["recharge"] for s in series]
    avg = statistics.fmean(values)
    # A good night should return roughly 50+ points of battery.
    return {
        "series": series,
        "avg_recharge": round(avg),
        "best": max(values),
        "worst": min(values),
        "verdict": "good" if avg >= 50 else "warn" if avg >= 35 else "bad",
        "poor_nights": sum(1 for v in values if v < 35),
    }


def build_volume_map(payload: dict, today: date, *, weeks: int = 8) -> dict | None:
    """Cumulative training exposure per muscle — what you are actually growing.

    Distinct from the recovery heatmap, which asks "what is sore right now".
    This asks "what has been trained enough to adapt", which is the question
    that matters for keeping muscle through a deficit.
    """
    sessions = [s for s in (payload.get("training") or {}).get("sessions") or [] if s.get("date")]
    cutoff = today - timedelta(weeks=weeks)
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for s in sessions:
        d = parse_iso(s["date"])
        if not d or d < cutoff:
            continue
        minutes = s.get("duration_min") or 45
        for muscle, intensity in (s.get("muscle_groups") or {}).items():
            totals[muscle] = totals.get(muscle, 0) + intensity * minutes
            counts[muscle] = counts.get(muscle, 0) + 1
    if not totals:
        return None
    peak = max(totals.values())
    muscles = sorted(
        (
            {
                "muscle": m,
                "load": round(v),
                "share": round(v / peak, 3),
                "sessions": counts[m],
                "per_week": round(counts[m] / weeks, 1),
            }
            for m, v in totals.items()
        ),
        key=lambda x: -x["load"],
    )
    # Twice a week is the usual floor for a muscle to actually progress.
    undertrained = [m for m in muscles if m["per_week"] < 1.0]
    return {
        "muscles": muscles,
        "weeks": weeks,
        "peak_load": round(peak),
        "undertrained": [m["muscle"] for m in undertrained],
        "well_trained": [m["muscle"] for m in muscles if m["per_week"] >= 2.0],
    }
