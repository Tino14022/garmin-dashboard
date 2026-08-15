"""Builds the dashboard payload from a metrics source and a data store.

Depends only on the protocols, never on garminconnect — so the entire build,
including HTML generation, runs offline against a fake source.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

from .config import Settings
from .domain.benchmarks import build_benchmarks
from .domain.body import build_body_view
from .domain.formatting import iso
from .domain.fuelling import (
    build_energy_flow,
    build_macro_plate,
    build_protein_distribution,
)
from .domain.goals import build_fat_loss_view
from .domain.health import FetchLog
from .domain.insights import build_insights
from .domain.matrix import build_digest, build_matrix, build_rings
from .domain.nutrition import build_nutrition_view
from .domain.overview import build_overview
from .domain.patterns import (
    build_body_battery,
    build_circadian,
    build_hypnogram,
    build_punch_card,
    build_streak_quality,
    build_volume_map,
)
from .domain.performance import build_pace_curve, build_pr_wall
from .domain.plan import build_race_plan
from .domain.readiness import (
    build_readiness,
    build_recovery_debt,
    build_todays_call,
)
from .domain.training import (
    build_training_view,
    build_weekly_mileage,
    split_easy_vs_workout,
)


def build_payload(
    source,
    store,
    settings: Settings,
    log: FetchLog,
    *,
    today: date | None = None,
    generated_at_time: str | None = None,
    generated_at_iso: str | None = None,
) -> dict:
    today = today or settings.today()
    weeks = settings.windows
    trend_start = today - timedelta(weeks=weeks.trend)
    recovery_start = today - timedelta(weeks=weeks.recovery)
    recent_runs_start = today - timedelta(weeks=weeks.recent_runs)

    runs = source.runs(trend_start, today)
    load_trend = source.load_trend(trend_start, today)
    vo2max_trend = source.vo2max_trend(trend_start, today)
    hrv_trend = source.hrv_trend(recovery_start, today)
    rhr_trend = source.rhr_trend(recovery_start, today)
    sleep_trend = source.sleep_trend(trend_start, today)
    personal_records = source.personal_records()
    race_predictions = source.race_predictions()
    other_activities = source.other_activities(trend_start, today)
    calorie_trend = source.calorie_trend(today - timedelta(weeks=weeks.calories), today)

    recent_runs = [
        r for r in runs if date.fromisoformat(r["date"]) >= recent_runs_start
    ]
    recent_runs.sort(key=lambda r: r["start_time_local"], reverse=True)

    presets = store.load("muscle_presets", {})
    training_view = build_training_view(
        runs,
        other_activities,
        today,
        manual_sessions=store.load("trainings", []),
        presets=presets,
        week_starts_on=settings.week_starts_on,
    )

    nutrition = store.load("nutrition", [])
    body_comp = store.load("body_comp", [])
    lifestyle = store.load("lifestyle", [])

    workout_plan = store.load("workout_plan", None)
    if workout_plan and workout_plan.get("date") != iso(today):
        workout_plan = None  # only show a plan for today; stale plans just disappear

    # Cutting raises the protein target rather than lowering it — protein is what
    # keeps the loss coming off as fat instead of muscle.
    protein_g_per_kg = (
        settings.goal.protein_g_per_kg
        if settings.goal
        else settings.athlete.protein_g_per_kg
    )
    nutrition_view = build_nutrition_view(
        nutrition,
        calorie_trend,
        body_comp,
        today,
        default_weight_kg=settings.athlete.weight_kg,
        protein_g_per_kg=protein_g_per_kg,
    )

    race_plan = build_race_plan(
        runs,
        today,
        race_date=settings.race.date,
        race_distance_km=settings.race.distance_km,
        week_starts_on=settings.week_starts_on,
    )

    days_remaining = (settings.race.date - today).days
    payload = {
        "generated_at": today.isoformat(),
        "generated_at_time": generated_at_time
        or time.strftime("%Y-%m-%d %H:%M %Z"),
        # Machine-readable build time so the page can work out for itself how
        # stale it is; the display string above is not reliably parseable.
        "generated_at_iso": generated_at_iso
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "athlete_name": source.athlete_name(),
        "race": {
            "name": settings.race.name,
            "date": settings.race.date.isoformat(),
            "distance_km": settings.race.distance_km,
            "days_remaining": days_remaining,
            "weeks_remaining": round(days_remaining / 7, 1),
        },
        "athlete": {
            "height_cm": settings.athlete.height_cm,
            "weight_kg": settings.athlete.weight_kg,
        },
        "personal_records": personal_records,
        "race_predictions": race_predictions,
        "load_trend": load_trend,
        "vo2max_trend": vo2max_trend,
        "hrv_trend": hrv_trend,
        "rhr_trend": rhr_trend,
        "sleep_trend": sleep_trend,
        "weekly_mileage": build_weekly_mileage(
            runs, trend_start, today, week_starts_on=settings.week_starts_on
        ),
        "recent_runs": recent_runs,
        "pace_panel": split_easy_vs_workout(recent_runs),
        "training": training_view,
        "nutrition": nutrition,
        "body_comp": body_comp,
        "muscle_group_list": presets.get("muscle_groups", []),
        "calorie_trend": calorie_trend,
        "nutrition_view": nutrition_view,
        "lifestyle": lifestyle,
        "workout_plan": workout_plan,
        "race_plan": race_plan,
        "build_health": log.to_payload(),
    }

    # These read the assembled payload rather than the raw sources, so they see
    # exactly what the page sees and cannot drift from it.
    payload["body_view"] = build_body_view(
        body_comp, height_cm=settings.athlete.height_cm, today=today
    )
    payload["fat_loss"] = build_fat_loss_view(
        body_comp, nutrition_view, settings.goal, today, race_date=settings.race.date
    )
    payload["insights"] = build_insights(payload, today)

    # Presentation modules. Each reads the assembled payload rather than the raw
    # sources, so none can drift from what the rest of the page shows, and each
    # returns None when its data isn't there — the tab simply omits that block.
    payload["readiness"] = build_readiness(payload, today)
    payload["todays_call"] = build_todays_call(payload, payload["readiness"], today)
    payload["recovery_debt"] = build_recovery_debt(payload, today)
    payload["circadian"] = build_circadian(payload, today)
    payload["hypnogram"] = build_hypnogram(payload)
    payload["body_battery"] = build_body_battery(payload)
    payload["punch_card"] = build_punch_card(payload, today)
    payload["streak_quality"] = build_streak_quality(payload, today)
    payload["volume_map"] = build_volume_map(payload, today)
    payload["pace_curve"] = build_pace_curve(payload)
    payload["pr_wall"] = build_pr_wall(payload)
    payload["macro_plate"] = build_macro_plate(payload, today)
    payload["energy_flow"] = build_energy_flow(payload, today)
    payload["protein_distribution"] = build_protein_distribution(payload, today)
    payload["benchmarks"] = build_benchmarks(payload)
    payload["correlation_matrix"] = build_matrix(payload)
    payload["rings"] = build_rings(payload, today)
    payload["digest"] = build_digest(payload, today)

    # Last: the overview summarises everything above it.
    payload["overview"] = build_overview(payload, today)
    return payload
