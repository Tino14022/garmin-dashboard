"""Fat-loss goal tracking.

Weight is the wrong thing to chase and the wrong thing to measure. What matters
is fat mass falling while lean mass holds — the same 2kg lost can be a good
week or a bad one depending on which it came from. This tracks both, checks the
rate is slow enough to actually be fat, and says plainly when the deficit is
fighting the race build rather than fitting alongside it.
"""
from __future__ import annotations

from datetime import date, timedelta

from .formatting import parse_iso

KCAL_PER_KG_FAT = 7700

# Day-to-day scale readings are dominated by water, glycogen and gut contents,
# not tissue. Two readings a day apart showing -0.55kg extrapolate to "-3.9% of
# bodyweight per week", which would fire a too-fast warning off pure noise —
# real tissue loss that fast is not physiologically possible at these deficits.
# Below this span the change is reported but no rate is computed from it.
MIN_DAYS_FOR_RATE = 5


def _split(entry: dict) -> tuple[float, float] | None:
    w, bf = entry.get("weight_kg"), entry.get("body_fat_pct")
    if w is None or bf is None:
        return None
    fat = w * bf / 100
    return fat, w - fat


def build_fat_loss_view(
    body_comp: list[dict],
    nutrition_view: dict,
    goal,
    today: date,
    *,
    race_date: date | None = None,
) -> dict | None:
    if goal is None:
        return None
    entries = sorted(
        [b for b in body_comp if parse_iso(b.get("date")) and _split(b)],
        key=lambda b: b["date"],
    )
    if not entries:
        return None

    first, latest = entries[0], entries[-1]
    fat_now, lean_now = _split(latest)
    weight_now = latest["weight_kg"]

    # Target holds lean mass constant — the whole point is to lose only the fat.
    target_weight = lean_now / (1 - goal.target_body_fat_pct / 100)
    target_fat = target_weight - lean_now
    fat_to_lose = round(fat_now - target_fat, 1)

    daily_deficit = round(goal.weekly_rate_kg * KCAL_PER_KG_FAT / 7)
    weeks_needed = round(fat_to_lose / goal.weekly_rate_kg, 1) if goal.weekly_rate_kg else None
    eta = today + timedelta(weeks=weeks_needed) if weeks_needed and weeks_needed > 0 else None

    # Measured progress, only once the readings span enough time to mean anything.
    actual = None
    too_soon = None
    if len(entries) > 1:
        d0, d1 = parse_iso(first["date"]), parse_iso(latest["date"])
        days = (d1 - d0).days
        if 0 < days < MIN_DAYS_FOR_RATE:
            fat_first, lean_first = _split(first)
            too_soon = {
                "days": days,
                "needed": MIN_DAYS_FOR_RATE,
                "weight_change_kg": round(weight_now - first["weight_kg"], 2),
                "fat_change_kg": round(fat_now - fat_first, 2),
                "lean_change_kg": round(lean_now - lean_first, 2),
            }
        if days >= MIN_DAYS_FOR_RATE:
            fat_first, lean_first = _split(first)
            weeks = days / 7
            actual = {
                "days": days,
                "fat_change_kg": round(fat_now - fat_first, 2),
                "lean_change_kg": round(lean_now - lean_first, 2),
                "weight_change_kg": round(weight_now - first["weight_kg"], 2),
                "fat_rate_kg_per_week": round((fat_now - fat_first) / weeks, 2),
                "weight_rate_pct_per_week": round(
                    (first["weight_kg"] - weight_now) / first["weight_kg"] / weeks * 100, 2
                ),
            }

    findings = _assess(
        goal, actual, nutrition_view, fat_to_lose, eta, race_date, today,
        daily_deficit, too_soon,
    )

    return {
        "target_body_fat_pct": goal.target_body_fat_pct,
        "current_body_fat_pct": latest["body_fat_pct"],
        "start_body_fat_pct": first["body_fat_pct"],
        "fat_mass_kg": round(fat_now, 1),
        "lean_mass_kg": round(lean_now, 1),
        "target_fat_mass_kg": round(target_fat, 1),
        "target_weight_kg": round(target_weight, 1),
        "fat_to_lose_kg": fat_to_lose,
        "target_weekly_rate_kg": goal.weekly_rate_kg,
        "required_daily_deficit_kcal": daily_deficit,
        "protein_target_g": round(weight_now * goal.protein_g_per_kg),
        "weeks_needed": weeks_needed,
        "projected_date": eta.isoformat() if eta else None,
        "achievable_by_race": bool(eta and race_date and eta <= race_date),
        "readings": len(entries),
        "actual": actual,
        "too_soon": too_soon,
        "min_days_for_rate": MIN_DAYS_FOR_RATE,
        "findings": findings,
    }


def _assess(goal, actual, nutrition_view, fat_to_lose, eta, race_date, today,
            daily_deficit, too_soon=None) -> list[dict]:
    out: list[dict] = []

    if fat_to_lose <= 0:
        out.append({
            "severity": "good",
            "title": "You're already at target",
            "detail": f"Body fat is at or below the {goal.target_body_fat_pct}% goal. Hold here and train.",
        })
        return out

    # How the plan sits against race day — the constraint that actually binds.
    if race_date and eta:
        days_to_race = (race_date - today).days
        if eta <= race_date:
            out.append({
                "severity": "good",
                "title": f"{fat_to_lose}kg of fat to lose, and time to do it",
                "detail": (
                    f"At {goal.weekly_rate_kg}kg a week you reach {goal.target_body_fat_pct}% around "
                    f"{eta.strftime('%d %b')}, which is inside the {days_to_race} days to race day. That rate needs "
                    f"about a {daily_deficit} kcal daily deficit — modest enough to run on, which is the point. "
                    "Going faster costs long-run quality and lean mass, not just fat."
                ),
            })
        else:
            out.append({
                "severity": "info",
                "title": f"{fat_to_lose}kg to lose — this runs past race day",
                "detail": (
                    f"At a safe {goal.weekly_rate_kg}kg a week you hit {goal.target_body_fat_pct}% around "
                    f"{eta.strftime('%d %b')}, after the race on {race_date.strftime('%d %b')}. That is fine and it is "
                    "the right order: hold the modest deficit through the build, race, then cut harder afterwards. "
                    "Chasing the whole thing before race day would come out of your long runs."
                ),
            })

    # Whether the intended deficit is actually happening does not depend on
    # having a second weigh-in, so this is checked before that early return.
    balance = nutrition_view.get("week_balance_kcal")
    days_compared = nutrition_view.get("week_days_compared") or 0
    if balance is not None and days_compared >= 3 and balance > -100:
        out.append({
            "severity": "warn",
            "title": "Logged intake isn't in a deficit",
            "detail": (
                f"Your logged days average {balance:+} kcal against measured burn, where the goal needs about "
                f"-{daily_deficit}. Either the food log is missing days or the deficit is not actually happening."
            ),
        })

    if actual is None:
        if too_soon:
            out.append({
                "severity": "info",
                "title": f"{too_soon['days']} day(s) between readings — too soon for a rate",
                "detail": (
                    f"Weight moved {too_soon['weight_change_kg']:+}kg, of which the scale attributes "
                    f"{too_soon['fat_change_kg']:+}kg to fat and {too_soon['lean_change_kg']:+}kg to lean mass. "
                    "Do not read any of that as tissue: over a day or two the scale is mostly measuring water, "
                    "glycogen and gut contents. Losing half a kilo of actual fat takes roughly a 3,800 kcal "
                    f"deficit, which is not what happened. A real rate needs about {too_soon['needed']} days "
                    "between readings, and a trustworthy one needs two to three weeks."
                ),
            })
        else:
            out.append({
                "severity": "info",
                "title": "One reading so far — no rate to judge yet",
                "detail": (
                    "Fat loss is only visible as a trend. Weigh in two or three times a week on the same routine "
                    "(waking, before food or drink) and this panel starts showing whether the weight coming off is "
                    "fat or muscle, which is the only question that matters."
                ),
            })
        return out

    # Is the weight coming off as fat, or as muscle?
    fat_d, lean_d = actual["fat_change_kg"], actual["lean_change_kg"]
    if lean_d <= -0.7:
        out.append({
            "severity": "warn",
            "title": f"Lean mass down {abs(lean_d)}kg — the deficit is too aggressive",
            "detail": (
                f"Over {actual['days']} days fat moved {fat_d:+}kg but lean mass moved {lean_d:+}kg. Losing lean "
                f"mass during a race build costs you both the run and the physique. Add roughly 250 kcal a day, "
                f"push protein to the {goal.protein_g_per_kg}g/kg target, and keep the strength work in."
            ),
        })
    elif fat_d < -0.2 and lean_d >= -0.3:
        out.append({
            "severity": "good",
            "title": f"Fat down {abs(fat_d)}kg with lean mass held",
            "detail": (
                f"Exactly the split you want across {actual['days']} days: {fat_d:+}kg fat, {lean_d:+}kg lean. "
                "Whatever you are doing on food and lifting, keep doing it."
            ),
        })
    elif fat_d > 0.2:
        out.append({
            "severity": "warn",
            "title": f"Fat mass up {fat_d}kg",
            "detail": (
                f"Over {actual['days']} days fat mass rose rather than fell, so intake is above burn on average "
                "regardless of what any single day showed. The weekly energy balance on the Nutrition tab is where "
                "to look — it needs several logged days to be worth anything."
            ),
        })

    # Rate safety, independent of composition.
    rate_pct = actual["weight_rate_pct_per_week"]
    if rate_pct > goal.max_safe_weekly_pct:
        out.append({
            "severity": "warn",
            "title": f"Losing {rate_pct}% of bodyweight a week — too fast",
            "detail": (
                f"Above about {goal.max_safe_weekly_pct}% a week the loss stops being mostly fat, and during a "
                "build it eats into the training you are trying to absorb. Ease the deficit."
            ),
        })
    elif actual["fat_rate_kg_per_week"] < 0:
        pace = abs(actual["fat_rate_kg_per_week"])
        if pace < goal.weekly_rate_kg * 0.5:
            out.append({
                "severity": "info",
                "title": f"Fat loss running at {pace}kg/week against a {goal.weekly_rate_kg}kg target",
                "detail": (
                    "Slower than planned. That is not a failure — slow loss protects muscle — but if you want the "
                    f"target date to hold, the deficit needs to be nearer {daily_deficit} kcal a day."
                ),
            })

    return out
