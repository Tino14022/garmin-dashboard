"""The Garmin workout pusher.

The pace conversion is the part worth pinning: Garmin stores a pace target as a
*speed* range in m/s, so the faster pace is the larger number. Inverting them
produces a target the watch reads backwards, and nothing about that fails
loudly — it just makes every session wrong.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

# No garminconnect import needed: the pusher keeps payload building free of the
# client library precisely so it stays testable without it.
from push_workouts_to_garmin import (  # noqa: E402
    PLAN_PATH,
    build_steps,
    build_workout,
    estimate_seconds,
    speed_bounds,
)

PLAN = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
PACES = PLAN["paces"]


def test_faster_pace_becomes_the_higher_speed():
    # 6:25/km is faster than 6:40/km, so it must be the larger m/s value.
    slower, faster = speed_bounds([385, 400])
    assert slower == pytest.approx(2.5)
    assert faster == pytest.approx(2.5974, abs=0.001)
    assert faster > slower


def test_distance_steps_carry_a_distance_end_condition():
    steps = build_steps([{"kind": "run", "distance_m": 5000, "pace": "easy"}], PACES)
    assert steps[0]["endCondition"]["conditionTypeKey"] == "distance"
    assert steps[0]["endConditionValue"] == 5000.0


def test_time_steps_carry_a_time_end_condition():
    steps = build_steps([{"kind": "recover", "seconds": 90}], PACES)
    assert steps[0]["endCondition"]["conditionTypeKey"] == "time"
    assert steps[0]["endConditionValue"] == 90.0


def test_steps_without_a_pace_get_no_target():
    steps = build_steps([{"kind": "recover", "seconds": 90}], PACES)
    assert steps[0]["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert "targetValueOne" not in steps[0]


def test_repeat_group_wraps_its_children_and_counts_iterations():
    steps = build_steps(
        [{"kind": "repeat", "times": 6, "steps": [
            {"kind": "run", "distance_m": 400, "pace": "rep_400"},
            {"kind": "recover", "seconds": 90},
        ]}],
        PACES,
    )
    group = steps[0]
    assert group["type"] == "RepeatGroupDTO"
    assert group["numberOfIterations"] == 6
    assert len(group["workoutSteps"]) == 2
    assert group["endCondition"]["conditionTypeKey"] == "iterations"


def test_step_order_is_strictly_increasing_across_a_repeat():
    steps = build_steps(
        [
            {"kind": "warmup", "distance_m": 1500, "pace": "easy"},
            {"kind": "repeat", "times": 3, "steps": [
                {"kind": "run", "distance_m": 400, "pace": "rep_400"},
                {"kind": "recover", "seconds": 60},
            ]},
            {"kind": "cooldown", "distance_m": 1000, "pace": "easy"},
        ],
        PACES,
    )
    orders = []
    for step in steps:
        orders.append(step["stepOrder"])
        orders.extend(child["stepOrder"] for child in step.get("workoutSteps", []))
    assert orders == sorted(orders), orders
    assert len(orders) == len(set(orders)), "duplicate stepOrder"


def test_repeat_duration_counts_every_iteration():
    specs = [{"kind": "repeat", "times": 4, "steps": [{"kind": "recover", "seconds": 60}]}]
    assert estimate_seconds(specs, PACES) == 240


def test_every_planned_session_builds_a_valid_workout():
    """Guards the plan file itself: a typo'd pace key or step kind would
    otherwise only surface mid-upload, halfway through writing to the account."""
    for session in PLAN["sessions"]:
        workout = build_workout(session, PACES, PLAN["name_prefix"])
        assert workout["workoutName"]
        assert workout["estimatedDurationInSecs"] > 0
        steps = workout["workoutSegments"][0]["workoutSteps"]
        assert steps, session["date"]


def test_every_pace_key_in_the_plan_actually_exists():
    def check(specs):
        for spec in specs:
            if spec["kind"] == "repeat":
                check(spec["steps"])
            elif spec.get("pace"):
                assert spec["pace"] in PACES, f"unknown pace '{spec['pace']}'"

    for session in PLAN["sessions"]:
        check(session["steps"])


def test_race_day_is_the_full_distance():
    race = [s for s in PLAN["sessions"] if s["date"] == "2026-10-04"][0]
    assert race["steps"][0]["distance_m"] == 21100
