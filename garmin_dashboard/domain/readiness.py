"""Readiness, the daily training call, and the recovery debt ledger.

Readiness is a composite, and composites are usually black boxes — a number
appears and you either believe it or you don't. This one always ships its
components, so when it says 54 you can see which input dragged it there and
decide whether you agree.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from .formatting import parse_iso

# Weights sum to 1.0. HRV and sleep dominate because they are the two signals
# that move first when you are accumulating fatigue.
WEIGHTS = {"hrv": 0.3, "sleep": 0.3, "soreness": 0.2, "form": 0.1, "resting_hr": 0.1}


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def _latest(rows, key="date"):
    dated = [r for r in rows if r.get(key)]
    return max(dated, key=lambda r: r[key]) if dated else None


def _component(label, score, detail, available=True):
    return {
        "key": label,
        "score": round(score) if score is not None else None,
        "detail": detail,
        "available": available,
    }


def build_readiness(payload: dict, today: date) -> dict | None:
    sleep = [s for s in payload.get("sleep_trend") or [] if s.get("date")]
    last_night = _latest(sleep)
    components = []

    # --- HRV against your own recent baseline, not a population number -------
    hrv_score, hrv_detail = None, "no overnight HRV recorded"
    if last_night and last_night.get("avg_overnight_hrv") is not None:
        hrv = last_night["avg_overnight_hrv"]
        baseline = last_night.get("hrv_7d_average") or last_night.get("hrv_7d_avg")
        if not baseline:
            history = [s["avg_overnight_hrv"] for s in sleep if s.get("avg_overnight_hrv")]
            baseline = statistics.fmean(history) if history else hrv
        if baseline:
            ratio = hrv / baseline
            # 1.0 of baseline is a 75; each 10% either side moves it 25 points.
            hrv_score = _clamp(75 + (ratio - 1) * 250)
            pct = round((ratio - 1) * 100)
            hrv_detail = f"{hrv}ms against a {round(baseline)}ms baseline ({pct:+}%)"
    components.append(_component("hrv", hrv_score, hrv_detail, hrv_score is not None))

    # --- Sleep: last night, tempered by the week's debt ----------------------
    sleep_score, sleep_detail = None, "no sleep recorded"
    if last_night:
        score = last_night.get("score")
        recent = sorted(sleep, key=lambda s: s["date"], reverse=True)[:7]
        hours = [s["hours"] for s in recent if s.get("hours")]
        needs = [s["sleep_need_min"] for s in recent if s.get("sleep_need_min")]
        need_h = (statistics.fmean(needs) / 60) if needs else 8.0
        debt = max(0.0, (need_h - statistics.fmean(hours)) * len(hours)) if hours else 0.0
        if score is not None:
            # Each hour of accumulated debt costs 4 points off last night's score.
            sleep_score = _clamp(score - debt * 4)
            sleep_detail = f"last night {score}"
            if debt > 0.5:
                sleep_detail += f", carrying {debt:.1f}h of debt"
    components.append(_component("sleep", sleep_score, sleep_detail, sleep_score is not None))

    # --- Soreness: the worst muscle group decides ---------------------------
    # Absent training data is not the same as being fresh: with nothing logged
    # there is no soreness signal, and scoring it 100 would invent readiness
    # out of an empty payload.
    scores = (payload.get("training") or {}).get("muscle_scores")
    if scores is None:
        components.append(_component("soreness", None, "no training logged", False))
    else:
        worst = max(scores.values(), default=0)
        sore_score = _clamp(100 - worst * 100)
        worst_name = max(scores, key=scores.get, default=None) if scores else None
        sore_detail = (
            f"{worst_name.replace('_', ' ')} at {round(worst * 100)}% soreness"
            if worst_name and worst > 0.1
            else "nothing meaningfully sore"
        )
        components.append(_component("soreness", sore_score, sore_detail))

    # --- Form (TSB): fresh is good, but very high means detrained ------------
    load = _latest(payload.get("load_trend") or [])
    form_score, form_detail = None, "no training load data"
    if load and load.get("tsb") is not None:
        tsb = load["tsb"]
        # Peak readiness sits around +10; deeply negative is fatigue, very
        # positive is freshness bought with lost fitness.
        form_score = _clamp(100 - abs(tsb - 10) * 1.6)
        form_detail = f"TSB {tsb:+}"
        if tsb < -20:
            form_detail += " — deep fatigue"
        elif tsb > 30:
            form_detail += " — very fresh, verging on detrained"
    components.append(_component("form", form_score, form_detail, form_score is not None))

    # --- Resting HR drift against baseline ----------------------------------
    rhr_rows = [r for r in payload.get("rhr_trend") or [] if r.get("rhr")]
    rhr_score, rhr_detail = None, "no resting HR data"
    if rhr_rows:
        latest_rhr = max(rhr_rows, key=lambda r: r["date"])["rhr"]
        baseline = statistics.fmean([r["rhr"] for r in rhr_rows])
        drift = latest_rhr - baseline
        # Every beat above baseline costs 8 points; below baseline is a bonus.
        rhr_score = _clamp(80 - drift * 8)
        rhr_detail = f"{latest_rhr}bpm against a {round(baseline)}bpm baseline ({drift:+.0f})"
    components.append(_component("resting_hr", rhr_score, rhr_detail, rhr_score is not None))

    usable = [c for c in components if c["score"] is not None]
    if not usable:
        return None
    total_weight = sum(WEIGHTS[c["key"]] for c in usable)
    score = round(sum(c["score"] * WEIGHTS[c["key"]] for c in usable) / total_weight)

    if score >= 75:
        band, label = "high", "Ready"
    elif score >= 55:
        band, label = "moderate", "Moderate"
    else:
        band, label = "low", "Compromised"

    # Which single input is holding the score back — the actionable part.
    limiter = min(usable, key=lambda c: c["score"])
    return {
        "score": score,
        "band": band,
        "label": label,
        "components": components,
        "limiter": limiter["key"] if limiter["score"] < score else None,
        "limiter_detail": limiter["detail"],
        "inputs_used": len(usable),
        "inputs_total": len(components),
    }


def build_todays_call(payload: dict, readiness: dict | None, today: date) -> dict | None:
    """Train hard, train easy, or rest — with the reasoning exposed."""
    if not readiness:
        return None

    scores = (payload.get("training") or {}).get("muscle_scores") or {}
    worst = max(scores.values(), default=0)
    sessions = (payload.get("training") or {}).get("sessions") or []
    session_days = sorted({parse_iso(s["date"]) for s in sessions if parse_iso(s["date"])}, reverse=True)
    streak = 0
    if session_days and (today - session_days[0]).days <= 1:
        streak = 1
        for a, b in zip(session_days, session_days[1:]):
            if (a - b).days == 1:
                streak += 1
            else:
                break

    plan = payload.get("workout_plan")
    race_plan = payload.get("race_plan") or {}
    reasons: list[str] = []
    verdict, detail = "moderate", ""

    if streak >= 6:
        verdict = "rest"
        reasons.append(f"{streak} consecutive training days — adaptation happens on the days off")
    elif readiness["score"] < 50:
        verdict = "rest"
        reasons.append(f"readiness at {readiness['score']}, held down by {readiness['limiter_detail']}")
    elif readiness["score"] < 65 or worst > 0.7:
        verdict = "easy"
        if worst > 0.7:
            reasons.append("a muscle group is still deeply sore")
        if readiness["score"] < 65:
            reasons.append(f"readiness at {readiness['score']}")
    else:
        verdict = "hard"
        reasons.append(f"readiness at {readiness['score']} with nothing badly sore")

    if plan and verdict != "rest":
        reasons.append(f"today's plan is {plan.get('name')}")
    if race_plan.get("next_long_run_km") and verdict == "hard":
        reasons.append(f"the ladder wants a {race_plan['next_long_run_km']}km long run this week")

    detail = {
        "hard": "Green light for a hard session — the long run or a heavy lift. This is the day to spend.",
        "easy": "Train, but keep it genuinely easy. Conversational pace, or lift something that isn't sore.",
        "rest": "Take the day. Not a walk-it-off day, an actual rest day — that is what turns training into fitness.",
    }[verdict]

    return {
        "verdict": verdict,
        "headline": {"hard": "Train hard", "easy": "Train easy", "rest": "Rest"}[verdict],
        "detail": detail,
        "reasons": reasons,
        "streak_days": streak,
        "readiness_score": readiness["score"],
    }


def build_recovery_debt(payload: dict, today: date, *, days: int = 28) -> dict | None:
    """Sleep debt as a running balance you can overdraw."""
    sleep = [s for s in payload.get("sleep_trend") or [] if s.get("date") and s.get("hours")]
    if len(sleep) < 3:
        return None
    by_date = {s["date"]: s for s in sleep}
    series = []
    balance = 0.0
    for i in range(days, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        night = by_date.get(d)
        if night:
            need = (night.get("sleep_need_min") or 480) / 60
            nightly = night["hours"] - need
            # Debt accrues fully; surplus repays at half rate, because you
            # cannot bank sleep as efficiently as you lose it.
            balance += nightly if nightly < 0 else nightly * 0.5
        # Debt fades slowly even on unlogged days rather than compounding forever.
        balance = max(-40.0, min(8.0, balance * 0.97))
        series.append({"date": d, "balance": round(balance, 2), "logged": night is not None})
    current = series[-1]["balance"] if series else 0
    status = "good" if current > -3 else "warn" if current > -10 else "bad"
    return {
        "series": series,
        "current_balance_h": round(current, 1),
        "status": status,
        "worst_h": round(min(s["balance"] for s in series), 1),
        "nights_logged": sum(1 for s in series if s["logged"]),
    }
