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
