"""The append helper the morning agents call.

It exists so agents never load a growing data file into context just to add a
row, so the behaviour that matters is: correct merge, strict validation, and
never destroying existing data on bad input.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import log_entry  # noqa: E402

WEIGH_IN = {"date": "2026-08-16", "weight_kg": 98.35, "body_fat_pct": 20.3, "bmr": 2165}


def run(name, entry, path):
    return log_entry.apply(name, entry, path)


def test_creates_the_file_when_absent(tmp_path):
    p = tmp_path / "body_comp.json"
    run("body_comp", WEIGH_IN, p)
    assert json.loads(p.read_text()) == [WEIGH_IN]


def test_appends_alongside_existing_entries(tmp_path):
    p = tmp_path / "body_comp.json"
    p.write_text(json.dumps([{"date": "2026-08-15", "weight_kg": 98.9}]))
    run("body_comp", WEIGH_IN, p)
    rows = json.loads(p.read_text())
    assert [r["date"] for r in rows] == ["2026-08-15", "2026-08-16"]


def test_same_day_weigh_in_updates_rather_than_duplicating(tmp_path):
    """Re-running after a correction must not leave two readings for one day."""
    p = tmp_path / "body_comp.json"
    run("body_comp", WEIGH_IN, p)
    run("body_comp", {**WEIGH_IN, "weight_kg": 98.4}, p)
    rows = json.loads(p.read_text())
    assert len(rows) == 1
    assert rows[0]["weight_kg"] == 98.4


def test_correcting_one_field_keeps_the_rest_of_the_reading(tmp_path):
    """A partial resend must merge, not replace — otherwise fixing one number
    silently deletes the other fourteen fields the scale reported."""
    p = tmp_path / "body_comp.json"
    full = {**WEIGH_IN, "bmi": 26.9, "water_pct": 50.0, "body_score": 87}
    run("body_comp", full, p)
    run("body_comp", {"date": WEIGH_IN["date"], "weight_kg": 98.4}, p)
    row = json.loads(p.read_text())[0]
    assert row["weight_kg"] == 98.4        # corrected
    assert row["bmi"] == 26.9              # preserved
    assert row["water_pct"] == 50.0
    assert row["body_score"] == 87


def test_entries_are_kept_in_date_order(tmp_path):
    p = tmp_path / "body_comp.json"
    for d in ("2026-08-18", "2026-08-16", "2026-08-17"):
        run("body_comp", {"date": d, "weight_kg": 98.0}, p)
    assert [r["date"] for r in json.loads(p.read_text())] == [
        "2026-08-16", "2026-08-17", "2026-08-18",
    ]


def test_nulls_are_dropped_not_stored(tmp_path):
    p = tmp_path / "body_comp.json"
    run("body_comp", {"date": "2026-08-16", "weight_kg": 98.35, "bmi": None}, p)
    assert "bmi" not in json.loads(p.read_text())[0]


def test_unknown_fields_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown field"):
        run("body_comp", {"date": "2026-08-16", "vibes": "good"}, tmp_path / "body_comp.json")


def test_missing_required_fields_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="missing required"):
        run("body_comp", {"weight_kg": 98.35}, tmp_path / "body_comp.json")


@pytest.mark.parametrize("bad", ["16-08-2026", "2026/08/16", "tomorrow", ""])
def test_malformed_dates_are_rejected(tmp_path, bad):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run("body_comp", {"date": bad, "weight_kg": 98.0}, tmp_path / "body_comp.json")


def test_a_corrupt_file_is_not_overwritten(tmp_path):
    """Better to fail loudly than to silently replace a file we can't parse."""
    p = tmp_path / "body_comp.json"
    p.write_text("{ this is not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        run("body_comp", WEIGH_IN, p)
    assert p.read_text() == "{ this is not json"


def test_workout_plan_replaces_the_whole_file(tmp_path):
    """Only one plan is ever current, so it overwrites rather than accumulates."""
    p = tmp_path / "workout_plan.json"
    run("workout_plan", {"date": "2026-08-16", "name": "Pull Day", "exercises": []}, p)
    run("workout_plan", {"date": "2026-08-17", "name": "Push Day", "exercises": []}, p)
    assert json.loads(p.read_text())["name"] == "Push Day"


def test_nutrition_allows_several_entries_per_day(tmp_path):
    p = tmp_path / "nutrition.json"
    run("nutrition", {"date": "2026-08-16", "description": "eggs", "calories": 300}, p)
    run("nutrition", {"date": "2026-08-16", "description": "rice", "calories": 400}, p)
    assert len(json.loads(p.read_text())) == 2


def test_every_real_data_file_field_is_accepted(tmp_path):
    """Guards against the helper rejecting a field the dashboard already uses."""
    full = {
        "date": "2026-08-16", "time": "10:37", "weight_kg": 98.35, "bmi": 26.9,
        "body_fat_pct": 20.3, "muscle_mass_kg": 74.4, "skeletal_muscle_kg": 38.1,
        "water_pct": 50.0, "protein_pct": 21.7, "bone_mass_kg": 4.0,
        "visceral_fat": 8, "subcutaneous_fat_pct": 15.3, "bmr": 2165,
        "scale_heart_rate": 83, "body_score": 87,
    }
    p = tmp_path / "body_comp.json"
    run("body_comp", full, p)
    assert json.loads(p.read_text())[0] == full


def test_cli_rejects_an_unknown_target(capsys):
    assert log_entry.main(["log_entry.py", "not_a_file"]) == 2


def test_training_annotations_can_be_logged(tmp_path):
    """Sessions are logged often enough that agents need this target too."""
    p = tmp_path / "trainings.json"
    run("trainings", {
        "date": "2026-08-16", "type": "gym", "subtype": "full_body",
        "notes": "Bodyweight Circuit", "muscle_groups": {"chest": 0.65},
    }, p)
    assert json.loads(p.read_text())[0]["subtype"] == "full_body"


def test_several_sessions_on_one_day_are_all_kept(tmp_path):
    """A gym session and a run on the same day are two entries, not a merge."""
    p = tmp_path / "trainings.json"
    run("trainings", {"date": "2026-08-16", "type": "gym"}, p)
    run("trainings", {"date": "2026-08-16", "type": "run"}, p)
    assert [r["type"] for r in json.loads(p.read_text())] == ["gym", "run"]


def test_a_training_entry_without_a_type_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="missing required"):
        run("trainings", {"date": "2026-08-16"}, tmp_path / "trainings.json")


def test_non_ascii_notes_are_stored_readably(tmp_path):
    """Notes routinely contain em-dashes. Escaping them is valid JSON but makes
    every diff on these data files unreadable."""
    dash = "—"
    p = tmp_path / "trainings.json"
    run("trainings", {"date": "2026-08-16", "type": "gym", "notes": f"Circuit {dash} cut short"}, p)
    raw = p.read_text(encoding="utf-8")
    assert dash in raw
    assert "u2014" not in raw
