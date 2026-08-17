"""resolve_todays_workout: the standing split resolves to a session for every
weekday, a chat-logged workout_plan.json entry for today overrides it, and
the abs finisher gets appended to gym days only."""
from __future__ import annotations

from datetime import date

from garmin_dashboard.domain.workout import resolve_todays_workout

SPLIT = {
    "schedule": {
        "0": "long_run", "1": "push", "2": "pull", "3": "legs",
        "4": "rest", "5": "light_run", "6": "bodyweight_circuit",
    },
    "append_finisher_to": ["push", "pull", "legs"],
    "templates": {
        "push": {"name": "Push Day", "exercises": [{"name": "Bench", "target_sets": 3, "target_reps": "10"}]},
        "pull": {"name": "Pull Day", "exercises": [{"name": "Row", "target_sets": 3, "target_reps": "10"}]},
        "legs": {"name": "Leg Day", "exercises": [{"name": "Squat", "target_sets": 3, "target_reps": "10"}]},
        "abs_finisher": {"name": "Abs Finisher", "exercises": [{"name": "Plank", "target_sets": 5, "target_reps": "90 sec"}]},
        "bodyweight_circuit": {"name": "Bodyweight Circuit", "note": "Abs, push-ups, pull-ups."},
    },
}

MONDAY = date(2026, 8, 17)  # weekday() == 0


def test_gym_day_appends_the_abs_finisher():
    result = resolve_todays_workout({}, date(2026, 8, 18), SPLIT)  # Tuesday -> push
    assert result["kind"] == "checklist"
    assert result["name"] == "Push Day"
    names = [ex["name"] for ex in result["exercises"]]
    assert names == ["Bench", "Plank"]


def test_run_day_pulls_the_long_run_target_from_race_plan():
    payload = {"race_plan": {"next_long_run_km": 7.8}}
    result = resolve_todays_workout(payload, MONDAY, SPLIT)
    assert result["kind"] == "run"
    assert result["name"] == "Long Run"
    assert result["target_km"] == 7.8


def test_light_run_day_has_no_prescribed_distance():
    result = resolve_todays_workout({}, date(2026, 8, 22), SPLIT)  # Saturday
    assert result["kind"] == "run"
    assert result["name"] == "Light Run"
    assert result["target_km"] is None


def test_rest_day():
    result = resolve_todays_workout({}, date(2026, 8, 21), SPLIT)  # Friday
    assert result["kind"] == "rest"


def test_note_day_for_a_template_with_no_fixed_reps():
    result = resolve_todays_workout({}, date(2026, 8, 23), SPLIT)  # Sunday
    assert result["kind"] == "note"
    assert "push-ups" in result["note"]


def test_chat_logged_plan_for_today_overrides_the_standing_split():
    payload = {
        "workout_plan": {
            "date": "2026-08-18",
            "name": "Actually Legs Today",
            "exercises": [{"name": "Deadlift", "target_sets": 5, "target_reps": "5"}],
        }
    }
    result = resolve_todays_workout(payload, date(2026, 8, 18), SPLIT)  # Tuesday, normally push
    assert result["source"] == "override"
    assert result["name"] == "Actually Legs Today"
    assert [ex["name"] for ex in result["exercises"]] == ["Deadlift"]


def test_stale_workout_plan_for_a_different_date_does_not_override():
    payload = {
        "workout_plan": {"date": "2026-08-10", "name": "Old Plan", "exercises": [{"name": "X", "target_sets": 1, "target_reps": "1"}]},
        "race_plan": {},
    }
    result = resolve_todays_workout(payload, date(2026, 8, 18), SPLIT)
    assert result["source"] == "standing_split"
    assert result["name"] == "Push Day"


def test_missing_schedule_entry_returns_none_kind_not_a_crash():
    result = resolve_todays_workout({}, MONDAY, {"schedule": {}, "templates": {}})
    assert result["kind"] == "none"
