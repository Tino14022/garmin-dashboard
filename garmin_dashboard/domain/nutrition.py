"""Nutrition aggregation: intake vs Garmin's measured burn."""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from .formatting import iso, parse_iso

# Garmin reports a day's basal burn as it accrues, so a day the watch did not
# cover end to end arrives with a short BMR. Counting such a day as complete
# understates burn and can invert the whole surplus/deficit verdict, so days
# below this share of the athlete's typical full-day BMR are treated as partial.
COMPLETE_DAY_BMR_RATIO = 0.9

# A single day is a meal, not a trend. Calling one logged day a surplus and
# concluding "likely building muscle" from it is how this panel embarrassed
# itself; below this many compared days the numbers are shown without a verdict.
MIN_DAYS_FOR_VERDICT = 3


def typical_daily_bmr(calorie_trend: list[dict]) -> float | None:
    """Median full-day basal burn, used as the yardstick for completeness.

    Median rather than mean so the partial days this exists to detect cannot
    drag the threshold down far enough to admit themselves.
    """
    values = [c["bmr_kcal"] for c in calorie_trend if c.get("bmr_kcal")]
    return statistics.median(values) if values else None


def is_complete_day(entry: dict, typical_bmr: float | None) -> bool:
    bmr = entry.get("bmr_kcal")
    if not typical_bmr or not bmr:
        return True  # nothing to judge against; assume usable
    return bmr >= typical_bmr * COMPLETE_DAY_BMR_RATIO


def build_nutrition_view(
    nutrition: list[dict],
    calorie_trend: list[dict],
    body_comp: list[dict],
    today: date,
    *,
    default_weight_kg: float,
    protein_g_per_kg: float,
) -> dict:
    latest_weight = default_weight_kg
    latest_bmr = None
    if body_comp:
        sorted_bc = sorted(body_comp, key=lambda b: b.get("date") or "")
        last_bc = sorted_bc[-1] if sorted_bc else None
        if last_bc:
            if last_bc.get("weight_kg"):
                latest_weight = last_bc["weight_kg"]
            if last_bc.get("bmr"):
                latest_bmr = last_bc["bmr"]
    protein_target_g = round(latest_weight * protein_g_per_kg)

    # Only complete days count toward the average — today isn't over, so its
    # numbers are partial and would skew a "daily average" downward.
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    intake_by_date: dict[str, float] = {}
    protein_by_date: dict[str, float] = {}
    for n in nutrition:
        d = n.get("date")
        if not d:
            continue
        dd = parse_iso(d)
        if dd is None or dd < week_ago or dd > yesterday:
            continue
        intake_by_date[d] = intake_by_date.get(d, 0) + (n.get("calories") or 0)
        protein_by_date[d] = protein_by_date.get(d, 0) + (n.get("protein_g") or 0)

    typical_bmr = typical_daily_bmr(calorie_trend)
    in_window = [
        c
        for c in calorie_trend
        if c.get("date") and week_ago <= date.fromisoformat(c["date"]) <= yesterday
    ]
    burn_by_date = {
        c["date"]: c["total_kcal"] for c in in_window if is_complete_day(c, typical_bmr)
    }
    active_by_date = {
        c["date"]: (c.get("active_kcal") or 0)
        for c in in_window
        if is_complete_day(c, typical_bmr)
    }
    bmr_by_date = {
        c["date"]: (c.get("bmr_kcal") or 0)
        for c in in_window
        if is_complete_day(c, typical_bmr)
    }
    partial_days = [c["date"] for c in in_window if not is_complete_day(c, typical_bmr)]

    # Only compare days where we actually know both sides of the equation.
    common_dates = sorted(set(intake_by_date) & set(burn_by_date))
    avg_intake = (
        round(sum(intake_by_date[d] for d in common_dates) / len(common_dates))
        if common_dates
        else None
    )
    avg_burn = (
        round(sum(burn_by_date[d] for d in common_dates) / len(common_dates))
        if common_dates
        else None
    )
    avg_protein = (
        round(sum(protein_by_date.get(d, 0) for d in common_dates) / len(common_dates))
        if common_dates
        else None
    )
    balance = (
        (avg_intake - avg_burn)
        if (avg_intake is not None and avg_burn is not None)
        else None
    )

    classification = None
    if balance is not None and len(common_dates) >= MIN_DAYS_FOR_VERDICT:
        protein_adequate = (
            avg_protein is not None and avg_protein >= protein_target_g * 0.85
        )
        if balance >= 200:
            classification = (
                "surplus_adequate_protein" if protein_adequate else "surplus_low_protein"
            )
        elif balance <= -200:
            classification = (
                "deficit_adequate_protein" if protein_adequate else "deficit_low_protein"
            )
        else:
            classification = "maintenance"

    today_iso = iso(today)
    today_intake = sum(
        n.get("calories") or 0 for n in nutrition if n.get("date") == today_iso
    )
    today_protein = sum(
        n.get("protein_g") or 0 for n in nutrition if n.get("date") == today_iso
    )
    today_entry = next((c for c in calorie_trend if c.get("date") == today_iso), None)
    today_burn_so_far = today_entry.get("total_kcal") if today_entry else None

    def _avg(source):
        return (
            round(sum(source.get(d, 0) for d in common_dates) / len(common_dates))
            if common_dates
            else None
        )

    return {
        # Burn is Garmin's total = basal + active. Both halves are reported so
        # the page can show that active work is in there rather than leaving it
        # looking like a bare BMR figure.
        "week_avg_active_kcal": _avg(active_by_date),
        "week_avg_bmr_kcal": _avg(bmr_by_date),
        "today_active_kcal": today_entry.get("active_kcal") if today_entry else None,
        "today_bmr_kcal": today_entry.get("bmr_kcal") if today_entry else None,
        "partial_days_excluded": partial_days,
        "typical_bmr_kcal": round(typical_bmr) if typical_bmr else None,
        # True when there are numbers but too few days to draw a conclusion from.
        "too_few_days_for_verdict": bool(
            balance is not None and len(common_dates) < MIN_DAYS_FOR_VERDICT
        ),
        "min_days_for_verdict": MIN_DAYS_FOR_VERDICT,
        "protein_target_g": protein_target_g,
        "protein_g_per_kg": protein_g_per_kg,
        "latest_weight_kg": latest_weight,
        "latest_bmr": latest_bmr,
        "week_avg_intake_kcal": avg_intake,
        "week_avg_burn_kcal": avg_burn,
        "week_avg_protein_g": avg_protein,
        "week_balance_kcal": round(balance) if balance is not None else None,
        "week_days_compared": len(common_dates),
        "classification": classification,
        "today_intake_kcal": round(today_intake) if today_intake else None,
        "today_protein_g": round(today_protein) if today_protein else None,
        "today_burn_so_far_kcal": today_burn_so_far,
    }
