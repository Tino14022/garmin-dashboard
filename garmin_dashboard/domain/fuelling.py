"""Nutrition composition views: macro plate, energy flow, protein distribution."""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from .formatting import parse_iso

KCAL = {"protein": 4, "carbs": 4, "fat": 9}
MEAL_ORDER = ["breakfast", "lunch", "dinner", "snack"]
# Beyond roughly this much in one sitting, extra protein contributes little to
# muscle protein synthesis — distribution matters, not just the daily total.
PER_MEAL_CEILING_G = 40


def _day_totals(nutrition: list[dict], on: str) -> dict:
    rows = [n for n in nutrition if n.get("date") == on]
    return {
        "calories": sum(n.get("calories") or 0 for n in rows),
        "protein": sum(n.get("protein_g") or 0 for n in rows),
        "carbs": sum(n.get("carbs_g") or 0 for n in rows),
        "fat": sum(n.get("fat_g") or 0 for n in rows),
        "entries": rows,
    }


def build_macro_plate(payload: dict, today: date) -> dict | None:
    """Actual macro split against the split your targets imply."""
    nutrition = [n for n in payload.get("nutrition") or [] if n.get("date")]
    if not nutrition:
        return None
    latest = max(n["date"] for n in nutrition)
    t = _day_totals(nutrition, latest)
    from_macros = sum(t[m] * KCAL[m] for m in KCAL)
    if from_macros <= 0:
        return None

    nv = payload.get("nutrition_view") or {}
    protein_target = nv.get("protein_target_g") or 0
    # Target plate: protein fixed by bodyweight, fat at 25% of intake, the rest
    # carbs — the usual construction for someone training hard in a deficit.
    target_kcal = nv.get("week_avg_burn_kcal") or t["calories"] or 2500
    target_fat_g = target_kcal * 0.25 / KCAL["fat"]
    target_carb_g = max(0, (target_kcal - protein_target * KCAL["protein"] - target_fat_g * KCAL["fat"]) / KCAL["carbs"])

    def slice_(name, grams, target_g):
        kcal = grams * KCAL[name]
        return {
            "macro": name,
            "grams": round(grams),
            "kcal": round(kcal),
            "pct": round(kcal / from_macros * 100),
            "target_g": round(target_g),
            "delta_g": round(grams - target_g),
        }

    slices = [
        slice_("protein", t["protein"], protein_target),
        slice_("carbs", t["carbs"], target_carb_g),
        slice_("fat", t["fat"], target_fat_g),
    ]
    return {
        "date": latest,
        "slices": slices,
        "total_kcal": round(t["calories"]),
        "kcal_from_macros": round(from_macros),
        # A gap here means the logged macros do not add up to the logged calories.
        "unaccounted_kcal": round(t["calories"] - from_macros),
    }


def build_energy_flow(payload: dict, today: date) -> dict | None:
    """Where the calories go: in from food, out via resting burn and activity."""
    nv = payload.get("nutrition_view") or {}
    intake = nv.get("week_avg_intake_kcal")
    bmr = nv.get("week_avg_bmr_kcal")
    active = nv.get("week_avg_active_kcal")
    if intake is None or bmr is None or active is None:
        return None
    burn = bmr + active
    balance = intake - burn
    return {
        "intake_kcal": intake,
        "bmr_kcal": bmr,
        "active_kcal": active,
        "burn_kcal": burn,
        "balance_kcal": balance,
        "days_compared": nv.get("week_days_compared"),
        # Shares of the larger side, so the two columns are drawn on one scale.
        "scale_max": max(intake, burn),
        "bmr_share": round(bmr / max(intake, burn) * 100, 1),
        "active_share": round(active / max(intake, burn) * 100, 1),
        "surplus": balance > 0,
    }


def build_protein_distribution(payload: dict, today: date, *, days: int = 7) -> dict | None:
    """Protein by meal — a daily total landing in one sitting is not the same
    as the same total spread across the day."""
    nutrition = [n for n in payload.get("nutrition") or [] if n.get("date") and n.get("protein_g")]
    if not nutrition:
        return None
    cutoff = (today - timedelta(days=days)).isoformat()
    recent = [n for n in nutrition if n["date"] >= cutoff]
    if not recent:
        recent = nutrition[-10:]

    by_meal: dict[str, list[float]] = {}
    for n in recent:
        meal = (n.get("meal") or "snack").lower()
        by_meal.setdefault(meal, []).append(n.get("protein_g") or 0)

    meals = []
    for meal in MEAL_ORDER:
        values = by_meal.get(meal)
        if not values:
            continue
        avg = statistics.fmean(values)
        meals.append({
            "meal": meal,
            "avg_protein_g": round(avg),
            "count": len(values),
            "over_ceiling": avg > PER_MEAL_CEILING_G,
        })
    for meal, values in by_meal.items():
        if meal not in MEAL_ORDER:
            meals.append({
                "meal": meal,
                "avg_protein_g": round(statistics.fmean(values)),
                "count": len(values),
                "over_ceiling": statistics.fmean(values) > PER_MEAL_CEILING_G,
            })
    if not meals:
        return None

    dates = {n["date"] for n in recent}
    daily = [sum(n.get("protein_g") or 0 for n in recent if n["date"] == d) for d in dates]
    target = (payload.get("nutrition_view") or {}).get("protein_target_g")
    biggest = max(meals, key=lambda m: m["avg_protein_g"])
    return {
        "meals": meals,
        "ceiling_g": PER_MEAL_CEILING_G,
        "avg_daily_g": round(statistics.fmean(daily)) if daily else 0,
        "target_g": target,
        "days": len(dates),
        "biggest_meal": biggest["meal"],
        # Front-loading everything into one meal wastes some of the total.
        "concentrated": biggest["avg_protein_g"] > PER_MEAL_CEILING_G * 1.5,
    }
