"""Running performance views: the personal pace–distance curve and PR wall."""
from __future__ import annotations

import re

from .formatting import fmt_pace

# Riegel's endurance exponent: time scales with distance^1.06 for trained
# runners. It is the standard way to project one race distance from another.
RIEGEL = 1.06

PR_DISTANCES_KM = {"1K": 1.0, "Mile": 1.609, "5K": 5.0, "10K": 10.0, "15K": 15.0, "Half Marathon": 21.0975}


def _seconds(display: str | None) -> float | None:
    """Parse the h:mm:ss / m:ss strings the PR list carries."""
    if not display or not isinstance(display, str):
        return None
    parts = display.strip().split(":")
    if not all(re.fullmatch(r"\d+", p) for p in parts):
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return None


def build_pace_curve(payload: dict) -> dict | None:
    """Your own pace-vs-distance curve, and which distances you over-perform at.

    Each PR predicts every other distance via Riegel. Where an actual PR beats
    what your other PRs predict, that is a genuine relative strength rather
    than a guess about your physiology.
    """
    prs = []
    for r in payload.get("personal_records") or []:
        km = PR_DISTANCES_KM.get(r.get("label"))
        secs = _seconds(r.get("value"))
        if km and secs:
            prs.append({"label": r["label"], "km": km, "seconds": secs,
                        "pace_sec_per_km": secs / km, "display": r["value"]})
    if len(prs) < 2:
        return None
    prs.sort(key=lambda p: p["km"])

    # Anchor on the PR with the best pace — usually the truest effort.
    anchor = min(prs, key=lambda p: p["pace_sec_per_km"])
    for p in prs:
        predicted = anchor["seconds"] * (p["km"] / anchor["km"]) ** RIEGEL
        p["predicted_seconds"] = round(predicted)
        p["delta_pct"] = round((p["seconds"] - predicted) / predicted * 100, 1)
        p["is_anchor"] = p is anchor

    # Modelled curve across the range, for drawing.
    curve = []
    km = 1.0
    while km <= 22.0:
        secs = anchor["seconds"] * (km / anchor["km"]) ** RIEGEL
        curve.append({"km": round(km, 1), "pace_sec_per_km": round(secs / km, 1),
                      "pace_label": fmt_pace(secs / km)})
        km += 0.5

    race_km = (payload.get("race") or {}).get("distance_km")
    projection = None
    if race_km:
        secs = anchor["seconds"] * (race_km / anchor["km"]) ** RIEGEL
        h, rem = divmod(int(secs), 3600)
        m, s = divmod(rem, 60)
        projection = {
            "km": race_km,
            "seconds": round(secs),
            "display": f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}",
            "pace_label": fmt_pace(secs / race_km),
        }

    strengths = [p for p in prs if not p["is_anchor"] and p["delta_pct"] < -2]
    weaknesses = [p for p in prs if not p["is_anchor"] and p["delta_pct"] > 5]
    return {
        "prs": prs,
        "curve": curve,
        "anchor": anchor["label"],
        "projection": projection,
        "strengths": [p["label"] for p in strengths],
        "weaknesses": [p["label"] for p in weaknesses],
    }


def build_pr_wall(payload: dict) -> dict | None:
    """Every record, with how far off the next round target you are."""
    records = payload.get("personal_records") or []
    if not records:
        return None
    predictions = payload.get("race_predictions") or {}
    out = []
    for r in records:
        secs = _seconds(r.get("value"))
        entry = {
            "label": r.get("label"),
            "display": r.get("value"),
            "seconds": secs,
            "km": PR_DISTANCES_KM.get(r.get("label")),
            "pace_label": fmt_pace(secs / PR_DISTANCES_KM[r["label"]])
            if secs and r.get("label") in PR_DISTANCES_KM
            else None,
            "predicted": predictions.get(r.get("label")),
        }
        # Garmin's current prediction against the standing record: if the
        # prediction is faster, the record is stale and there for the taking.
        pred_secs = _seconds(entry["predicted"])
        if secs and pred_secs:
            entry["beatable_by_s"] = round(secs - pred_secs)
            entry["ripe"] = pred_secs < secs
        out.append(entry)
    ripe = [r for r in out if r.get("ripe")]
    return {"records": out, "ripe": [r["label"] for r in ripe], "count": len(out)}
