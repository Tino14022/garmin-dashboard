"""The contract between what the page logs and what the pipeline reads.

The Worker appends entries to data/*.json in the shape the browser sends. These
tests pin that shape, so a change to either side that breaks the round trip
fails here rather than silently producing a dashboard that ignores your logs.
"""
from __future__ import annotations

from datetime import date, timedelta

from garmin_dashboard.domain.nutrition import build_nutrition_view
from garmin_dashboard.domain.training import build_training_view

ANCHOR = date(2026, 8, 14)

PRESETS = {
    "gym_splits": {
        "push": {"chest": 1.0, "triceps": 0.9, "front_delts": 0.8},
        "pull": {"lats": 1.0, "biceps": 0.9},
    },
    "sports": {"run": {"quads": 0.75}},
}

# Exactly what the page POSTs for a finished workout: an annotation, so no
# duration_min. See the Finish Workout handler in app_template.html.
LOGGED_WORKOUT = {
    "date": ANCHOR.isoformat(),
    "type": "gym",
    "subtype": "push",
    "muscle_groups": {"chest": 1.0, "triceps": 0.9, "front_delts": 0.8},
    "notes": "Push Day — Incline DB Press 4/4x8-10",
}

LOGGED_FOOD = {
    "date": ANCHOR.isoformat(),
    "meal": "lunch",
    "description": "Chicken curry with rice, ~400g",
    "calories": 820,
    "protein_g": 55,
    "carbs_g": 94,
    "fat_g": 23,
}

LOGGED_BODY = {
    "date": ANCHOR.isoformat(),
    "weight_kg": 93.4,
    "body_fat_pct": 22.5,
    "bmr": 2050,
}


def test_logged_workout_shows_immediately_as_pending_sync():
    """Before the watch syncs there is no Garmin activity to merge with, so the
    session must still appear rather than vanishing until tomorrow."""
    view = build_training_view(
        [], [], ANCHOR, manual_sessions=[LOGGED_WORKOUT], presets=PRESETS
    )
    assert len(view["sessions"]) == 1
    session = view["sessions"][0]
    assert session["garmin_synced"] is False
    assert session["subtype"] == "push"
    assert view["muscle_scores"]["chest"] == 1.0


def test_logged_workout_merges_with_the_garmin_activity_rather_than_doubling():
    garmin_activity = {
        "date": ANCHOR.isoformat(),
        "type": "gym",
        "duration_min": 68,
        "name": "Strength",
        "hour": 18,
    }
    view = build_training_view(
        [], [garmin_activity], ANCHOR, manual_sessions=[LOGGED_WORKOUT], presets=PRESETS
    )
    assert len(view["sessions"]) == 1, "annotation and activity were double-counted"
    session = view["sessions"][0]
    assert session["garmin_synced"] is True
    assert session["duration_min"] == 68  # duration comes from the watch
    assert session["notes"] == LOGGED_WORKOUT["notes"]  # detail from the log
    assert session["muscle_groups"] == LOGGED_WORKOUT["muscle_groups"]


def test_logged_food_feeds_the_nutrition_view():
    yesterday = (ANCHOR - timedelta(days=1)).isoformat()
    entry = {**LOGGED_FOOD, "date": yesterday}
    view = build_nutrition_view(
        [entry],
        [{"date": yesterday, "total_kcal": 3000}],
        [],
        ANCHOR,
        default_weight_kg=95,
        protein_g_per_kg=1.8,
    )
    assert view["week_avg_intake_kcal"] == 820
    assert view["week_avg_protein_g"] == 55
    assert view["week_days_compared"] == 1


def test_food_logged_without_macros_is_still_accepted():
    """The form allows a description-only entry; it must not break the maths."""
    yesterday = (ANCHOR - timedelta(days=1)).isoformat()
    view = build_nutrition_view(
        [{"date": yesterday, "meal": "snack", "description": "handful of nuts"}],
        [{"date": yesterday, "total_kcal": 3000}],
        [],
        ANCHOR,
        default_weight_kg=95,
        protein_g_per_kg=1.8,
    )
    assert view["week_avg_intake_kcal"] == 0
    assert view["week_balance_kcal"] == -3000


def test_logged_weigh_in_replaces_the_hardcoded_default_weight():
    view = build_nutrition_view(
        [], [], [LOGGED_BODY], ANCHOR, default_weight_kg=95, protein_g_per_kg=1.8
    )
    assert view["latest_weight_kg"] == 93.4
    assert view["protein_target_g"] == 168  # 93.4 * 1.8, not 95 * 1.8
    assert view["latest_bmr"] == 2050


def test_most_recent_weigh_in_wins():
    older = {"date": (ANCHOR - timedelta(days=10)).isoformat(), "weight_kg": 96.0}
    view = build_nutrition_view(
        [], [], [LOGGED_BODY, older], ANCHOR, default_weight_kg=95, protein_g_per_kg=1.8
    )
    assert view["latest_weight_kg"] == 93.4
