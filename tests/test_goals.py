"""Fat-loss goal tracking."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_dashboard.config import FatLossGoal
from garmin_dashboard.domain.goals import build_fat_loss_view

TODAY = date(2026, 8, 15)
RACE = date(2026, 10, 4)
GOAL = FatLossGoal()

BASELINE = {"date": "2026-08-15", "weight_kg": 98.9, "body_fat_pct": 20.3}


def view(entries, nutrition_view=None, goal=GOAL, today=TODAY):
    return build_fat_loss_view(
        entries, nutrition_view or {}, goal, today, race_date=RACE
    )


def test_no_goal_means_no_panel():
    assert build_fat_loss_view([BASELINE], {}, None, TODAY) is None


def test_no_readings_means_no_panel():
    assert view([]) is None


def test_entry_without_body_fat_is_unusable():
    assert view([{"date": "2026-08-15", "weight_kg": 98.9}]) is None


def test_target_holds_lean_mass_and_only_removes_fat():
    v = view([BASELINE])
    assert v["lean_mass_kg"] == pytest.approx(78.8, abs=0.1)
    # 78.8kg lean at 18% body fat implies 96.1kg total, so 17.3kg of fat.
    assert v["target_weight_kg"] == pytest.approx(96.1, abs=0.1)
    assert v["target_fat_mass_kg"] == pytest.approx(17.3, abs=0.1)
    assert v["fat_to_lose_kg"] == pytest.approx(2.8, abs=0.1)


def test_required_deficit_follows_from_the_target_rate():
    v = view([BASELINE])
    # 0.4kg of fat a week is 3080 kcal, i.e. 440 a day.
    assert v["required_daily_deficit_kcal"] == 440
    assert v["weeks_needed"] == pytest.approx(7.0, abs=0.1)


def test_protein_target_is_raised_for_the_cut():
    v = view([BASELINE])
    assert v["protein_target_g"] == round(98.9 * 2.0)


def test_goal_reachable_before_race_day_is_reported_as_such():
    v = view([BASELINE])
    assert v["achievable_by_race"] is True
    assert any(f["severity"] == "good" for f in v["findings"])


def test_goal_that_overruns_the_race_says_so_rather_than_rushing():
    v = view([BASELINE], goal=FatLossGoal(target_body_fat_pct=12.0))
    assert v["achievable_by_race"] is False
    text = " ".join(f["detail"] for f in v["findings"])
    assert "after the race" in text


def test_single_reading_gives_no_rate():
    v = view([BASELINE])
    assert v["actual"] is None
    assert any("no rate to judge" in f["title"] for f in v["findings"])


def test_fat_down_with_lean_held_is_the_good_split():
    later = {"date": "2026-08-29", "weight_kg": 97.6, "body_fat_pct": 18.9}
    v = view([BASELINE, later])
    assert v["actual"]["fat_change_kg"] < 0
    assert v["actual"]["lean_change_kg"] >= -0.3
    good = [f for f in v["findings"] if f["severity"] == "good"]
    assert any("lean mass held" in f["title"] for f in good)


def test_losing_lean_mass_raises_a_warning():
    # Same weight drop, but taken out of muscle rather than fat.
    later = {"date": "2026-08-29", "weight_kg": 96.4, "body_fat_pct": 20.6}
    v = view([BASELINE, later])
    assert v["actual"]["lean_change_kg"] < -0.7
    warn = [f for f in v["findings"] if f["severity"] == "warn"]
    assert any("Lean mass down" in f["title"] for f in warn)


def test_losing_weight_too_fast_is_flagged():
    later = {"date": "2026-08-22", "weight_kg": 96.5, "body_fat_pct": 19.0}
    v = view([BASELINE, later])
    assert v["actual"]["weight_rate_pct_per_week"] > 1.0
    assert any("too fast" in f["title"] for f in v["findings"])


def test_gaining_fat_is_flagged():
    later = {"date": "2026-08-29", "weight_kg": 100.5, "body_fat_pct": 21.5}
    v = view([BASELINE, later])
    assert v["actual"]["fat_change_kg"] > 0
    assert any("Fat mass up" in f["title"] for f in v["findings"])


def test_logged_intake_not_in_deficit_is_called_out():
    v = view(
        [BASELINE],
        nutrition_view={"week_balance_kcal": 300, "week_days_compared": 5},
    )
    assert any("isn't in a deficit" in f["title"] for f in v["findings"])


def test_deficit_check_needs_enough_logged_days():
    v = view(
        [BASELINE],
        nutrition_view={"week_balance_kcal": 300, "week_days_compared": 1},
    )
    assert not any("isn't in a deficit" in f["title"] for f in v["findings"])


def test_already_at_target_stops_prescribing_a_deficit():
    lean = {"date": "2026-08-15", "weight_kg": 90.0, "body_fat_pct": 15.0}
    v = view([lean])
    assert v["fat_to_lose_kg"] <= 0
    assert v["findings"][0]["severity"] == "good"
    assert "already at target" in v["findings"][0]["title"].lower()


# ---------------------------------------------- rate needs a real time span
NEXT_DAY = {"date": "2026-08-16", "weight_kg": 98.35, "body_fat_pct": 20.3}


def test_readings_a_day_apart_do_not_produce_a_rate():
    """-0.55kg overnight extrapolates to -3.9%/week, which would fire a
    too-fast warning off what is really just water."""
    v = view([BASELINE, NEXT_DAY], today=date(2026, 8, 16))
    assert v["actual"] is None
    assert v["too_soon"]["days"] == 1
    assert not any("too fast" in f["title"] for f in v["findings"])


def test_a_short_gap_still_reports_the_raw_change_and_says_why_it_is_not_a_rate():
    v = view([BASELINE, NEXT_DAY], today=date(2026, 8, 16))
    assert v["too_soon"]["weight_change_kg"] == pytest.approx(-0.55, abs=0.01)
    finding = next(f for f in v["findings"] if "too soon" in f["title"])
    assert "water" in finding["detail"]


def test_a_long_enough_gap_does_produce_a_rate():
    later = {"date": "2026-08-29", "weight_kg": 97.6, "body_fat_pct": 18.9}
    v = view([BASELINE, later], today=date(2026, 8, 29))
    assert v["actual"] is not None
    assert v["too_soon"] is None
    assert v["actual"]["days"] == 14
