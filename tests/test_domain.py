"""Unit tests for the pure transforms."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_dashboard.config import (
    AthleteConfig,
    RaceConfig,
    Settings,
    WindowConfig,
)
from garmin_dashboard.domain.formatting import (
    fmt_duration,
    fmt_pace,
    parse_iso,
    week_start,
)
from garmin_dashboard.domain.gamification import compute_gamification
from garmin_dashboard.domain.health import FetchLog
from garmin_dashboard.domain.nutrition import build_nutrition_view
from garmin_dashboard.domain.plan import build_race_plan, longest_run_km
from garmin_dashboard.domain.training import linear_decay

ANCHOR = date(2026, 8, 14)


# ---------------------------------------------------------------- formatting
@pytest.mark.parametrize(
    "seconds,expected",
    [(None, "-"), (0, "-"), (-5, "-"), (330, "5:30/km"), (359.6, "6:00/km")],
)
def test_fmt_pace(seconds, expected):
    assert fmt_pace(seconds) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [(None, "-"), (0, "-"), (59, "0:59"), (3600, "1:00:00"), (3661, "1:01:01")],
)
def test_fmt_duration(seconds, expected):
    assert fmt_duration(seconds) == expected


def test_parse_iso_rejects_junk():
    assert parse_iso("not-a-date") is None
    assert parse_iso(None) is None
    assert parse_iso("2026-08-14") == ANCHOR


def test_week_start_is_the_preceding_sunday():
    # 2026-08-14 is a Friday; the Sunday-start week began on the 9th.
    assert week_start(ANCHOR) == date(2026, 8, 9)
    assert week_start(date(2026, 8, 9)) == date(2026, 8, 9)


def test_week_start_honours_a_monday_week():
    assert week_start(ANCHOR, week_starts_on=0) == date(2026, 8, 10)


# ------------------------------------------------------------------- decay
@pytest.mark.parametrize(
    "days,expected", [(-1, 0.0), (0, 1.0), (1, 0.75), (2, 0.5), (4, 0.0), (9, 0.0)]
)
def test_linear_decay(days, expected):
    assert linear_decay(days) == pytest.approx(expected)


# --------------------------------------------------------------- nutrition
def _nutrition_args(nutrition, calories):
    return dict(
        nutrition=nutrition,
        calorie_trend=calories,
        body_comp=[],
        today=ANCHOR,
        default_weight_kg=95,
        protein_g_per_kg=1.8,
    )


def test_today_is_excluded_from_the_weekly_average():
    """Today is partial, so counting it would drag the daily average down."""
    days = [
        {"date": (ANCHOR - timedelta(days=n)).isoformat(), "calories": 3000, "protein_g": 180}
        for n in range(1, 4)
    ]
    days.append({"date": ANCHOR.isoformat(), "calories": 100, "protein_g": 5})
    burn = [
        {"date": (ANCHOR - timedelta(days=n)).isoformat(), "total_kcal": 3000}
        for n in range(1, 4)
    ]
    burn.append({"date": ANCHOR.isoformat(), "total_kcal": 400})
    view = build_nutrition_view(**_nutrition_args(days, burn))

    assert view["week_avg_intake_kcal"] == 3000
    assert view["week_days_compared"] == 3
    assert view["today_intake_kcal"] == 100


def test_days_without_both_sides_are_not_compared():
    intake = [{"date": (ANCHOR - timedelta(days=1)).isoformat(), "calories": 2000, "protein_g": 100}]
    burn = [{"date": (ANCHOR - timedelta(days=2)).isoformat(), "total_kcal": 2500}]
    view = build_nutrition_view(**_nutrition_args(intake, burn))
    assert view["week_days_compared"] == 0
    assert view["week_balance_kcal"] is None
    assert view["classification"] is None


@pytest.mark.parametrize(
    "intake,protein,expected",
    [
        (3400, 180, "surplus_adequate_protein"),
        (3400, 40, "surplus_low_protein"),
        (2000, 180, "deficit_adequate_protein"),
        (2000, 40, "deficit_low_protein"),
        (3000, 180, "maintenance"),
    ],
)
def test_energy_balance_classification(intake, protein, expected):
    days = [
        {"date": (ANCHOR - timedelta(days=n)).isoformat(), "calories": intake, "protein_g": protein}
        for n in range(1, 4)
    ]
    burn = [
        {"date": (ANCHOR - timedelta(days=n)).isoformat(), "total_kcal": 3000}
        for n in range(1, 4)
    ]
    assert build_nutrition_view(**_nutrition_args(days, burn))["classification"] == expected


def test_body_comp_weight_overrides_the_configured_default():
    view = build_nutrition_view(
        nutrition=[],
        calorie_trend=[],
        body_comp=[{"date": "2026-08-10", "weight_kg": 90.0, "bmr": 2000}],
        today=ANCHOR,
        default_weight_kg=95,
        protein_g_per_kg=1.8,
    )
    assert view["latest_weight_kg"] == 90.0
    assert view["protein_target_g"] == 162
    assert view["latest_bmr"] == 2000


# ------------------------------------------------------------ gamification
def test_streak_survives_a_day_that_is_not_over_yet():
    sessions = [
        {"date": (ANCHOR - timedelta(days=n)).isoformat(), "type": "gym", "duration_min": 60}
        for n in range(1, 4)
    ]
    assert compute_gamification(sessions, ANCHOR)["streak_days"] == 3


def test_streak_breaks_after_two_missed_days():
    sessions = [
        {"date": (ANCHOR - timedelta(days=n)).isoformat(), "type": "gym", "duration_min": 60}
        for n in (2, 3, 4)
    ]
    assert compute_gamification(sessions, ANCHOR)["streak_days"] == 0


def test_level_progress_stays_within_the_level():
    g = compute_gamification(
        [{"date": ANCHOR.isoformat(), "type": "gym", "duration_min": 725}], ANCHOR
    )
    assert g["xp"] == 725
    assert 0 <= g["level_progress"] <= 1
    assert 0 <= g["xp_into_level"] <= g["xp_for_next_level"]


def test_sessions_with_unparseable_dates_do_not_crash_gamification():
    g = compute_gamification(
        [{"date": "garbage", "type": "gym", "duration_min": 30}], ANCHOR
    )
    assert g["streak_days"] == 0


# -------------------------------------------------------------------- plan
def test_longest_run_ignores_runs_outside_the_window():
    runs = [
        {"date": (ANCHOR - timedelta(days=5)).isoformat(), "distance_km": 10.0},
        {"date": (ANCHOR - timedelta(days=400)).isoformat(), "distance_km": 18.0},
    ]
    assert longest_run_km(runs, since=ANCHOR - timedelta(days=56)) == 10.0


def test_plan_ends_on_race_day_at_race_distance():
    plan = build_race_plan(
        [{"date": ANCHOR.isoformat(), "distance_km": 10.0}],
        ANCHOR,
        race_date=date(2026, 10, 4),
        race_distance_km=21.1,
    )
    assert plan["weeks"][-1]["kind"] == "race"
    assert plan["weeks"][-1]["long_run_km"] == 21.1


def test_plan_never_jumps_more_than_ten_percent_between_builds():
    plan = build_race_plan(
        [{"date": ANCHOR.isoformat(), "distance_km": 10.0}],
        ANCHOR,
        race_date=date(2026, 10, 4),
        race_distance_km=21.1,
    )
    builds = [w["long_run_km"] for w in plan["weeks"] if w["kind"] == "build"]
    for previous, nxt in zip(builds, builds[1:]):
        assert nxt <= previous * 1.10 + 0.11  # +0.11 absorbs one-decimal rounding


def test_plan_tapers_rather_than_peaking_at_the_race():
    plan = build_race_plan(
        [{"date": ANCHOR.isoformat(), "distance_km": 10.0}],
        ANCHOR,
        race_date=date(2026, 10, 4),
        race_distance_km=21.1,
    )
    kinds = [w["kind"] for w in plan["weeks"]]
    assert kinds[-3:] == ["taper", "taper", "race"]
    tapers = [w["long_run_km"] for w in plan["weeks"] if w["kind"] == "taper"]
    assert tapers == sorted(tapers, reverse=True)


def test_plan_reports_when_there_is_not_enough_runway():
    plan = build_race_plan(
        [{"date": ANCHOR.isoformat(), "distance_km": 5.0}],
        ANCHOR,
        race_date=ANCHOR + timedelta(days=21),
        race_distance_km=21.1,
    )
    assert plan["on_track"] is False
    assert plan["weeks_needed_at_safe_growth"] > plan["build_weeks"]


def test_no_plan_once_the_race_has_passed():
    assert (
        build_race_plan([], ANCHOR, race_date=ANCHOR - timedelta(days=1), race_distance_km=21.1)
        is None
    )


def test_plan_copes_with_no_running_history():
    plan = build_race_plan([], ANCHOR, race_date=date(2026, 10, 4), race_distance_km=21.1)
    assert plan["current_longest_km"] == 5.0
    assert plan["weeks"]


# ------------------------------------------------------------------ health
def test_fetch_log_records_success():
    log = FetchLog()
    assert log.call("thing", lambda: 42) == 42
    assert log.healthy
    assert log.to_payload()["failed"] == 0


def test_fetch_log_retries_then_records_the_failure(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("nope")

    log = FetchLog()
    assert log.call("thing", boom, default="fallback", retries=3) == "fallback"
    assert len(calls) == 3
    assert not log.healthy
    payload = log.to_payload()
    assert payload["failed"] == 1
    assert "nope" in payload["failures"][0]["error"]


def test_fetch_log_recovers_if_a_retry_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("transient")
        return "ok"

    log = FetchLog()
    assert log.call("thing", flaky) == "ok"
    assert log.healthy


# ------------------------------------------------------------------ config
def test_settings_today_uses_the_configured_timezone():
    settings = Settings(
        race=RaceConfig(name="r", date=date(2026, 10, 4), distance_km=21.1),
        athlete=AthleteConfig(height_cm=192, weight_kg=95),
        windows=WindowConfig(),
    )
    assert settings.timezone_name == "Europe/Warsaw"
    assert isinstance(settings.today(), date)


def test_unknown_timezone_falls_back_instead_of_crashing():
    settings = Settings(
        race=RaceConfig(name="r", date=date(2026, 10, 4), distance_km=21.1),
        athlete=AthleteConfig(height_cm=192, weight_kg=95),
        timezone_name="Mars/Olympus_Mons",
    )
    assert isinstance(settings.today(), date)
