"""Correlation matrix across every daily metric, plus habit rings and the
weekly digest.

The matrix is the blunt instrument that complements the curated analyses in
insights.py: those ask specific questions, this looks everywhere at once. It
is therefore also the one most likely to surface coincidences, so every cell
carries its sample size and nothing under a usable threshold is drawn at all.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from .formatting import parse_iso
from .insights import MIN_PAIRS, confidence, pearson, strength

# Each metric: how to pull a per-date value out of the payload.
METRICS = [
    ("sleep_score", "Sleep score", "sleep"),
    ("sleep_hours", "Sleep hours", "sleep"),
    ("deep_min", "Deep sleep", "sleep"),
    ("hrv", "HRV", "recovery"),
    ("resting_hr", "Resting HR", "recovery"),
    ("body_battery", "Battery recharge", "recovery"),
    ("training_min", "Training minutes", "training"),
    ("run_km", "Run distance", "training"),
    ("atl", "Acute load", "training"),
    ("intake_kcal", "Calories in", "nutrition"),
    ("protein_g", "Protein", "nutrition"),
    ("burn_kcal", "Calories out", "nutrition"),
]


def _series(payload: dict) -> dict[str, dict[str, float]]:
    """metric -> {date: value}."""
    out: dict[str, dict[str, float]] = {k: {} for k, _, _ in METRICS}
    for s in payload.get("sleep_trend") or []:
        d = s.get("date")
        if not d:
            continue
        if s.get("score") is not None:
            out["sleep_score"][d] = s["score"]
        if s.get("hours") is not None:
            out["sleep_hours"][d] = s["hours"]
        if s.get("deep_min") is not None:
            out["deep_min"][d] = s["deep_min"]
        if s.get("avg_overnight_hrv") is not None:
            out["hrv"][d] = s["avg_overnight_hrv"]
        if s.get("resting_hr") is not None:
            out["resting_hr"][d] = s["resting_hr"]
        if s.get("body_battery_change") is not None:
            out["body_battery"][d] = s["body_battery_change"]
    for r in payload.get("rhr_trend") or []:
        if r.get("date") and r.get("rhr") is not None:
            out["resting_hr"].setdefault(r["date"], r["rhr"])
    for l in payload.get("load_trend") or []:
        if l.get("date") and l.get("atl") is not None:
            out["atl"][l["date"]] = l["atl"]
    for s in (payload.get("training") or {}).get("sessions") or []:
        d = s.get("date")
        if d and s.get("duration_min"):
            out["training_min"][d] = out["training_min"].get(d, 0) + s["duration_min"]
    for r in payload.get("recent_runs") or []:
        d = r.get("date")
        if d and r.get("distance_km"):
            out["run_km"][d] = out["run_km"].get(d, 0) + r["distance_km"]
    for n in payload.get("nutrition") or []:
        d = n.get("date")
        if not d:
            continue
        out["intake_kcal"][d] = out["intake_kcal"].get(d, 0) + (n.get("calories") or 0)
        out["protein_g"][d] = out["protein_g"].get(d, 0) + (n.get("protein_g") or 0)
    for c in payload.get("calorie_trend") or []:
        if c.get("date") and c.get("total_kcal"):
            out["burn_kcal"][c["date"]] = c["total_kcal"]
    return out


def build_matrix(payload: dict) -> dict | None:
    series = _series(payload)
    usable = [(k, label, group) for k, label, group in METRICS if len(series[k]) >= MIN_PAIRS]
    if len(usable) < 2:
        return None

    labels = [{"key": k, "label": label, "group": group} for k, label, group in usable]
    cells = []
    strongest = []
    for i, (a, a_label, _) in enumerate(usable):
        for j, (b, b_label, _) in enumerate(usable):
            if j <= i:
                continue
            shared = sorted(set(series[a]) & set(series[b]))
            if len(shared) < MIN_PAIRS:
                cells.append({"x": i, "y": j, "n": len(shared), "r": None})
                continue
            r = pearson([series[a][d] for d in shared], [series[b][d] for d in shared])
            cell = {
                "x": i, "y": j, "n": len(shared),
                "r": round(r, 2) if r is not None else None,
                "a": a_label, "b": b_label,
                "confidence": confidence(len(shared)),
            }
            cells.append(cell)
            if r is not None and strength(r) in ("moderate", "strong"):
                strongest.append(cell)
    strongest.sort(key=lambda c: -abs(c["r"]))
    return {
        "labels": labels,
        "cells": cells,
        "strongest": strongest[:6],
        "metrics_compared": len(usable),
    }


def build_rings(payload: dict, today: date) -> dict | None:
    """The four behaviours that actually move this athlete's goals."""
    nv = payload.get("nutrition_view") or {}
    rings = []

    sleep = [s for s in payload.get("sleep_trend") or [] if s.get("date") and s.get("hours")]
    if sleep:
        last = max(sleep, key=lambda s: s["date"])
        need = (last.get("sleep_need_min") or 480) / 60
        rings.append({
            "key": "sleep", "label": "Sleep", "value": last["hours"], "target": round(need, 1),
            "unit": "h", "pct": min(100, round(last["hours"] / need * 100)),
        })

    protein_target = nv.get("protein_target_g")
    if protein_target:
        eaten = nv.get("today_protein_g") or 0
        rings.append({
            "key": "protein", "label": "Protein", "value": eaten, "target": protein_target,
            "unit": "g", "pct": min(100, round(eaten / protein_target * 100)),
        })

    # Training: sessions this week against a five-a-week habit.
    sessions = (payload.get("training") or {}).get("sessions") or []
    week_ago = today - timedelta(days=6)
    this_week = len({
        s["date"] for s in sessions
        if parse_iso(s["date"]) and parse_iso(s["date"]) >= week_ago
    })
    rings.append({
        "key": "training", "label": "Training days", "value": this_week, "target": 5,
        "unit": "", "pct": min(100, round(this_week / 5 * 100)),
    })

    # Deficit adherence: how much of the target deficit is actually being run.
    fl = payload.get("fat_loss") or {}
    required = fl.get("required_daily_deficit_kcal")
    balance = nv.get("week_balance_kcal")
    if required and balance is not None:
        achieved = max(0, -balance)
        rings.append({
            "key": "deficit", "label": "Deficit", "value": round(achieved), "target": required,
            "unit": "kcal", "pct": min(100, round(achieved / required * 100)),
        })

    if not rings:
        return None
    return {"rings": rings, "closed": sum(1 for r in rings if r["pct"] >= 100), "total": len(rings)}


def build_digest(payload: dict, today: date) -> dict | None:
    """The week in twenty seconds."""
    week_ago = today - timedelta(days=6)

    def in_week(iso_date):
        d = parse_iso(iso_date)
        return d is not None and d >= week_ago

    sessions = [s for s in (payload.get("training") or {}).get("sessions") or [] if in_week(s.get("date"))]
    runs = [r for r in payload.get("recent_runs") or [] if in_week(r.get("date"))]
    sleep = [s for s in payload.get("sleep_trend") or [] if in_week(s.get("date")) and s.get("hours")]
    nutrition_days = {n["date"] for n in payload.get("nutrition") or [] if in_week(n.get("date"))}

    stats = [
        {"label": "Sessions", "value": len({s["date"] for s in sessions}), "unit": "days"},
        {"label": "Training time", "value": sum(s.get("duration_min") or 0 for s in sessions), "unit": "min"},
        {"label": "Distance run", "value": round(sum(r.get("distance_km") or 0 for r in runs), 1), "unit": "km"},
        {"label": "Avg sleep", "value": round(statistics.fmean([s["hours"] for s in sleep]), 1) if sleep else 0, "unit": "h"},
        {"label": "Days logged", "value": len(nutrition_days), "unit": "of 7"},
    ]

    # One line of praise and one of pressure, both drawn from real numbers.
    wins, watch = [], []
    if len({s["date"] for s in sessions}) >= 5:
        wins.append(f"trained on {len({s['date'] for s in sessions})} of the last 7 days")
    if sleep and statistics.fmean([s["hours"] for s in sleep]) >= 7:
        wins.append("kept sleep above seven hours")
    if runs:
        wins.append(f"covered {round(sum(r.get('distance_km') or 0 for r in runs), 1)}km")
    if len(nutrition_days) < 3:
        watch.append(f"only {len(nutrition_days)} day(s) of food logged — the energy balance can't work without it")
    if sleep and statistics.fmean([s["hours"] for s in sleep]) < 7:
        watch.append(f"sleep averaged {round(statistics.fmean([s['hours'] for s in sleep]), 1)}h")
    for f in (payload.get("insights") or {}).get("findings", [])[:2]:
        if f["severity"] == "warn":
            watch.append(f["headline"].lower())

    return {
        "from": week_ago.isoformat(),
        "to": today.isoformat(),
        "stats": stats,
        "wins": wins[:3],
        "watch": watch[:3],
    }
