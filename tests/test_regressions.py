"""Regressions for bugs found while refactoring."""
from __future__ import annotations

from datetime import date

from garmin_dashboard.domain.training import (
    build_training_view,
    guess_muscle_groups_from_name,
)

ANCHOR = date(2026, 8, 14)


def test_unknown_split_infers_nothing_instead_of_crashing():
    """`gym_splits.get(ref, ref)` used to hand a bare string to .items(), so a
    missing or malformed muscle_presets.json took the entire build down."""
    assert guess_muscle_groups_from_name("Push", {}) == {}
    assert guess_muscle_groups_from_name("Push day", {"pull": {"lats": 1.0}}) == {}


def test_known_split_still_resolves():
    splits = {"push": {"chest": 1.0, "triceps": 0.9}}
    assert guess_muscle_groups_from_name("Push", splits) == {"chest": 1.0, "triceps": 0.9}


def test_inline_muscle_map_keywords_still_resolve_without_presets():
    """Keywords mapping straight to a muscle dict never needed the presets file."""
    assert guess_muscle_groups_from_name("chest", {}) == {
        "chest": 1.0,
        "triceps": 0.5,
        "front_delts": 0.5,
    }


def test_training_view_builds_with_no_presets_at_all():
    view = build_training_view(
        [],
        [{"date": ANCHOR.isoformat(), "type": "gym", "duration_min": 60, "name": "Push"}],
        ANCHOR,
        manual_sessions=[],
        presets={},
    )
    assert len(view["sessions"]) == 1
    assert view["sessions"][0]["muscle_groups"] == {}


def test_same_day_same_type_activities_merge_into_one_session():
    """A paddleboard outing split into GPS segments should read as one
    session with the combined duration, not three near-identical cards."""
    day = ANCHOR.isoformat()
    view = build_training_view(
        [],
        [
            {"date": day, "hour": 13, "type": "sup", "duration_min": 16, "name": "SUP"},
            {"date": day, "hour": 15, "type": "sup", "duration_min": 12, "name": "SUP"},
            {"date": day, "hour": 17, "type": "sup", "duration_min": 24, "name": "SUP"},
        ],
        ANCHOR,
        manual_sessions=[],
        presets={},
    )
    assert len(view["sessions"]) == 1
    session = view["sessions"][0]
    assert session["duration_min"] == 52
    assert session["hour"] == 13  # earliest of the three


def test_different_types_same_day_stay_separate():
    day = ANCHOR.isoformat()
    view = build_training_view(
        [],
        [
            {"date": day, "hour": 16, "type": "swim", "duration_min": 18, "name": "Swim"},
            {"date": day, "hour": 21, "type": "sup", "duration_min": 24, "name": "SUP"},
        ],
        ANCHOR,
        manual_sessions=[],
        presets={},
    )
    assert len(view["sessions"]) == 2
    assert {s["type"] for s in view["sessions"]} == {"swim", "sup"}
