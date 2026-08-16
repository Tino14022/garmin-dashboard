"""Where you sit against published population norms.

A number alone rarely tells you whether to act. 52bpm resting means nothing
until you know it is better than roughly 85% of men your age.

Ranges are from widely published reference tables (ACSM body-fat standards,
Cooper Institute VO2max norms, and general adult resting-HR and HRV data).
They are orientation, not diagnosis, and the percentiles are interpolated from
band edges rather than a real distribution — treat them as approximate.
"""
from __future__ import annotations

from . import rank as rank_scale

# Each band: (upper_bound, percentile_at_that_bound). Lower is better where
# `lower_is_better`, so the bands read in the direction of improvement.
NORMS = {
    "vo2max": {
        "label": "VO2 max",
        "unit": "ml/kg/min",
        "lower_is_better": False,
        "bands": [(32, 10), (37, 25), (42, 50), (47, 75), (52, 90), (60, 99)],
        "note": "Aerobic engine size. The single best predictor of endurance performance.",
    },
    "resting_hr": {
        "label": "Resting heart rate",
        "unit": "bpm",
        "lower_is_better": True,
        "bands": [(48, 95), (54, 80), (60, 60), (66, 40), (72, 20), (85, 5)],
        "note": "Falls as aerobic fitness rises. Trained endurance athletes often sit in the 40s.",
    },
    "body_fat_pct": {
        "label": "Body fat",
        "unit": "%",
        "lower_is_better": True,
        "bands": [(11, 95), (14, 85), (18, 70), (22, 50), (26, 30), (32, 10)],
        "note": "ACSM standards for adult men. Under 18% is fit, under 14% is athletic.",
    },
    "hrv": {
        "label": "Overnight HRV",
        "unit": "ms",
        "lower_is_better": False,
        "bands": [(30, 10), (40, 25), (55, 50), (70, 75), (90, 90), (120, 99)],
        "note": "Autonomic recovery capacity. Highly individual — your own trend beats any norm.",
    },
    "sleep_hours": {
        "label": "Sleep",
        "unit": "h",
        "lower_is_better": False,
        "bands": [(5.5, 5), (6.5, 25), (7.0, 45), (7.5, 65), (8.5, 90), (10, 99)],
        "note": "Adults training hard generally need 7.5-9h. Under 7 blunts adaptation.",
    },
}


def _percentile(value: float, spec: dict) -> int:
    bands = spec["bands"]
    if spec["lower_is_better"]:
        for upper, pct in bands:
            if value <= upper:
                return pct
        return 2
    for upper, pct in bands:
        if value <= upper:
            return pct
    return 99


def _verdict(pct: int) -> tuple[str, str]:
    if pct >= 80:
        return "good", "Well above average"
    if pct >= 55:
        return "good", "Above average"
    if pct >= 40:
        return "info", "About average"
    if pct >= 20:
        return "warn", "Below average"
    return "warn", "Well below average"


def build_benchmarks(payload: dict) -> dict | None:
    values: dict[str, float] = {}

    vo2 = payload.get("vo2max_trend") or []
    if vo2:
        values["vo2max"] = max(vo2, key=lambda v: v.get("date") or "")["vo2max"]

    rhr = [r for r in payload.get("rhr_trend") or [] if r.get("rhr")]
    if rhr:
        values["resting_hr"] = max(rhr, key=lambda r: r["date"])["rhr"]

    body = payload.get("body_view")
    if body and body["latest"].get("body_fat_pct") is not None:
        values["body_fat_pct"] = body["latest"]["body_fat_pct"]

    sleep = [s for s in payload.get("sleep_trend") or [] if s.get("date")]
    if sleep:
        recent = sorted(sleep, key=lambda s: s["date"], reverse=True)[:14]
        hrvs = [s["avg_overnight_hrv"] for s in recent if s.get("avg_overnight_hrv")]
        if hrvs:
            values["hrv"] = round(sum(hrvs) / len(hrvs))
        hours = [s["hours"] for s in recent if s.get("hours")]
        if hours:
            values["sleep_hours"] = round(sum(hours) / len(hours), 1)

    if not values:
        return None

    metrics = []
    for key, value in values.items():
        spec = NORMS[key]
        pct = _percentile(value, spec)
        status, label = _verdict(pct)
        metrics.append({
            "key": key,
            "label": spec["label"],
            "unit": spec["unit"],
            "value": value,
            "percentile": pct,
            "status": status,
            "rank": rank_scale.from_percentile(pct),
            "verdict": label,
            "note": spec["note"],
            "lower_is_better": spec["lower_is_better"],
        })
    metrics.sort(key=lambda m: m["percentile"])
    return {
        "metrics": metrics,
        "strongest": metrics[-1]["label"],
        "weakest": metrics[0]["label"],
        "average_percentile": round(sum(m["percentile"] for m in metrics) / len(metrics)),
    }
