"""The refactor must not change a single computed value.

Both implementations are driven by the same fake Garmin API and the same data
files, and every key the legacy build produced is compared. Keys the refactor
adds (race_plan, build_health) are asserted separately in their own tests.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

import legacy_reference as legacy
from garmin_dashboard.config import DEFAULT_SETTINGS
from garmin_dashboard.domain.health import FetchLog
from garmin_dashboard.pipeline import build_payload
from garmin_dashboard.sources.garmin import GarminSource
from garmin_dashboard.storage import DictDataStore

NEW_KEYS = {"race_plan", "build_health", "generated_at_iso", "body_view", "insights"}


def legacy_payload(api, data_files, today):
    """Reproduces legacy main()'s assembly, minus login and file IO."""
    legacy_load = lambda path, default: data_files.get(  # noqa: E731
        path.name.replace(".json", ""), default
    )
    original = legacy.load_json
    legacy.load_json = legacy_load
    try:
        trend_start = today - timedelta(weeks=legacy.TREND_WEEKS)
        recovery_start = today - timedelta(weeks=legacy.RECOVERY_WEEKS)
        recent_start = today - timedelta(weeks=legacy.RECENT_RUNS_WEEKS)

        runs = legacy.fetch_activities(api, trend_start, today)
        recent = [
            r for r in runs if legacy.date.fromisoformat(r["date"]) >= recent_start
        ]
        recent.sort(key=lambda r: r["start_time_local"], reverse=True)
        other = legacy.fetch_other_activities(api, trend_start, today)
        calorie_trend = legacy.fetch_calorie_trend(
            api, today - timedelta(weeks=legacy.CALORIE_WEEKS), today
        )
        nutrition = data_files.get("nutrition", [])
        body_comp = data_files.get("body_comp", [])
        workout_plan = data_files.get("workout_plan")
        if workout_plan and workout_plan.get("date") != legacy.iso(today):
            workout_plan = None
        days_remaining = (legacy.RACE_DATE - today).days

        return {
            "generated_at": today.isoformat(),
            "athlete_name": api.get_full_name(),
            "race": {
                "name": legacy.RACE_NAME,
                "date": legacy.RACE_DATE.isoformat(),
                "distance_km": legacy.RACE_DISTANCE_KM,
                "days_remaining": days_remaining,
                "weeks_remaining": round(days_remaining / 7, 1),
            },
            "athlete": {
                "height_cm": legacy.HEIGHT_CM,
                "weight_kg": legacy.WEIGHT_KG,
            },
            "personal_records": legacy.fetch_personal_records(api),
            "race_predictions": legacy.fetch_race_predictions(api),
            "load_trend": legacy.fetch_load_trend(api, trend_start, today),
            "vo2max_trend": legacy.fetch_vo2max_trend(api, trend_start, today),
            "hrv_trend": legacy.fetch_hrv_trend(api, recovery_start, today),
            "rhr_trend": legacy.fetch_rhr_trend(api, recovery_start, today),
            "sleep_trend": legacy.fetch_sleep_trend(api, trend_start, today),
            "weekly_mileage": legacy.build_weekly_mileage(runs, trend_start, today),
            "recent_runs": recent,
            "pace_panel": legacy.split_easy_vs_workout(recent),
            "training": legacy.build_training_view(runs, other, today),
            "nutrition": nutrition,
            "body_comp": body_comp,
            "muscle_group_list": data_files.get("muscle_presets", {}).get(
                "muscle_groups", []
            ),
            "calorie_trend": calorie_trend,
            "nutrition_view": legacy.build_nutrition_view(
                nutrition, calorie_trend, body_comp, today
            ),
            "lifestyle": data_files.get("lifestyle", []),
            "workout_plan": workout_plan,
        }
    finally:
        legacy.load_json = original


@pytest.fixture
def payloads(fake_api, data_files, anchor):
    old = legacy_payload(fake_api, data_files, anchor)
    new = build_payload(
        GarminSource(fake_api, FetchLog(), pause=0),
        DictDataStore(data_files),
        DEFAULT_SETTINGS,
        FetchLog(),
        today=anchor,
        generated_at_time="fixed",
    )
    return old, new


def test_no_legacy_key_is_missing(payloads):
    old, new = payloads
    assert set(old) - set(new) == set()


def test_only_expected_keys_were_added(payloads):
    old, new = payloads
    assert set(new) - set(old) == NEW_KEYS | {"generated_at_time"}


@pytest.mark.parametrize(
    "key",
    [
        "generated_at",
        "athlete_name",
        "race",
        "athlete",
        "personal_records",
        "race_predictions",
        "load_trend",
        "vo2max_trend",
        "hrv_trend",
        "rhr_trend",
        "sleep_trend",
        "weekly_mileage",
        "recent_runs",
        "pace_panel",
        "nutrition",
        "body_comp",
        "muscle_group_list",
        "calorie_trend",
        "lifestyle",
        "workout_plan",
    ],
)
def test_value_is_identical(payloads, key):
    old, new = payloads
    assert new[key] == old[key], f"{key} changed in the refactor"


@pytest.mark.parametrize(
    "key",
    ["sessions", "muscle_scores", "muscle_detail", "streak_weeks", "week_count", "gamification"],
)
def test_training_view_is_identical(payloads, key):
    old, new = payloads
    assert new["training"][key] == old["training"][key]


def test_nutrition_view_keeps_every_legacy_field(payloads):
    """nutrition_view deliberately gained fields (the active/basal split, and
    partial-day exclusion). Every value the legacy build produced must still
    agree; the additions are pinned in test_nutrition_completeness.py."""
    old, new = payloads
    for key, value in old["nutrition_view"].items():
        assert new["nutrition_view"][key] == value, f"nutrition_view.{key} changed"


def test_training_view_produced_real_data(payloads):
    """Guards against the comparison passing because both sides are empty."""
    _, new = payloads
    assert len(new["training"]["sessions"]) > 5
    assert new["training"]["muscle_scores"]
    assert new["recent_runs"]
    assert new["calorie_trend"]
