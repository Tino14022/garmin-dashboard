"""The presentation modules: readiness, patterns, performance, fuelling,
benchmarks, matrix, rings and digest.

Each must degrade to None rather than raising when its data is absent — the
page omits the block instead of breaking.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_dashboard.config import FatLossGoal
from garmin_dashboard.domain.benchmarks import build_benchmarks
from garmin_dashboard.domain.fuelling import (
    build_eating_budget,
    build_macro_plate,
    build_protein_distribution,
)
from garmin_dashboard.domain.matrix import build_digest, build_matrix, build_rings
from garmin_dashboard.domain.patterns import (
    build_body_battery,
    build_circadian,
    build_hypnogram,
    build_punch_card,
    build_streak_quality,
    build_volume_map,
)
from garmin_dashboard.domain.performance import build_pace_curve, build_pr_wall
from garmin_dashboard.domain.readiness import (
    build_readiness,
    build_recovery_debt,
    build_todays_call,
)

TODAY = date(2026, 8, 15)


def iso(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def nights(count=14, **over):
    base = dict(score=80, hours=7.5, avg_overnight_hrv=60, hrv_7d_average=60,
                resting_hr=52, deep_min=80, light_min=250, rem_min=90, awake_min=20,
                bedtime_hour=23.0, sleep_need_min=480, body_battery_change=55)
    base.update(over)
    return [{"date": iso(i), **base} for i in range(count)]


def sessions(days, minutes=60, hour=18, muscles=None):
    return [
        {"date": iso(d), "type": "gym", "duration_min": minutes, "hour": hour,
         "muscle_groups": muscles or {"chest": 1.0, "triceps": 0.8}}
        for d in days
    ]


# ------------------------------------------------------------------ readiness
@pytest.mark.parametrize("builder", [build_readiness, build_recovery_debt])
def test_readiness_modules_return_none_without_data(builder):
    assert builder({}, TODAY) is None


def test_readiness_combines_its_inputs_and_shows_them():
    payload = {
        "sleep_trend": nights(),
        "training": {"muscle_scores": {"chest": 0.2}},
        "load_trend": [{"date": iso(0), "atl": 90, "ctl": 100, "tsb": 10}],
        "rhr_trend": [{"date": iso(i), "rhr": 52} for i in range(7)],
    }
    r = build_readiness(payload, TODAY)
    assert 0 <= r["score"] <= 100
    assert r["inputs_used"] == 5
    assert {c["key"] for c in r["components"]} == {"hrv", "sleep", "soreness", "form", "resting_hr"}


def test_readiness_falls_when_hrv_is_suppressed():
    good = build_readiness({"sleep_trend": nights()}, TODAY)
    bad = build_readiness(
        {"sleep_trend": nights(avg_overnight_hrv=40, hrv_7d_average=60)}, TODAY
    )
    assert bad["score"] < good["score"]


def test_readiness_names_the_limiting_input():
    payload = {"sleep_trend": nights(), "training": {"muscle_scores": {"quads": 0.95}}}
    r = build_readiness(payload, TODAY)
    assert r["limiter"] == "soreness"
    assert "quads" in r["limiter_detail"]


def test_readiness_works_from_partial_inputs():
    r = build_readiness({"sleep_trend": nights()}, TODAY)
    assert r is not None
    assert r["inputs_used"] < r["inputs_total"]


def test_sleep_debt_drags_readiness_below_the_raw_score():
    r = build_readiness({"sleep_trend": nights(hours=5.5, score=80)}, TODAY)
    sleep = next(c for c in r["components"] if c["key"] == "sleep")
    assert sleep["score"] < 80
    assert "debt" in sleep["detail"]


# ---------------------------------------------------------------- todays call
def test_todays_call_needs_readiness():
    assert build_todays_call({}, None, TODAY) is None


def test_long_streak_forces_a_rest_day():
    payload = {"sleep_trend": nights(), "training": {"sessions": sessions(range(7)), "muscle_scores": {}}}
    call = build_todays_call(payload, build_readiness(payload, TODAY), TODAY)
    assert call["verdict"] == "rest"
    assert "consecutive" in " ".join(call["reasons"])


def test_deep_soreness_downgrades_to_easy():
    payload = {"sleep_trend": nights(), "training": {"sessions": sessions([0]), "muscle_scores": {"chest": 0.85}}}
    call = build_todays_call(payload, build_readiness(payload, TODAY), TODAY)
    assert call["verdict"] == "easy"


def test_good_readiness_greenlights_a_hard_session():
    payload = {"sleep_trend": nights(), "training": {"sessions": sessions([0]), "muscle_scores": {"chest": 0.1}}}
    call = build_todays_call(payload, build_readiness(payload, TODAY), TODAY)
    assert call["verdict"] == "hard"
    assert call["reasons"]


def test_every_call_explains_itself():
    payload = {"sleep_trend": nights(), "training": {"sessions": sessions([0]), "muscle_scores": {}}}
    call = build_todays_call(payload, build_readiness(payload, TODAY), TODAY)
    assert call["reasons"] and call["detail"]


# -------------------------------------------------------------- recovery debt
def test_recovery_debt_accrues_on_short_nights():
    d = build_recovery_debt({"sleep_trend": nights(28, hours=5.5)}, TODAY)
    assert d["current_balance_h"] < 0
    assert d["status"] in ("warn", "bad")


def test_recovery_debt_stays_near_zero_when_sleeping_enough():
    d = build_recovery_debt({"sleep_trend": nights(28, hours=8.2)}, TODAY)
    assert d["current_balance_h"] >= -1
    assert d["status"] == "good"


def test_recovery_debt_is_bounded():
    d = build_recovery_debt({"sleep_trend": nights(28, hours=2.0)}, TODAY)
    assert d["current_balance_h"] >= -40


# ----------------------------------------------------------------- patterns
def test_pattern_modules_return_none_without_data():
    assert build_circadian({}, TODAY) is None
    assert build_punch_card({}, TODAY) is None
    assert build_streak_quality({}, TODAY) is None
    assert build_hypnogram({}) is None
    assert build_body_battery({}) is None
    assert build_volume_map({}, TODAY) is None


def test_circadian_measures_bedtime_spread():
    steady = build_circadian({"sleep_trend": nights(14, bedtime_hour=23.0)}, TODAY)
    assert steady["consistent"] is True
    assert steady["bedtime_spread_h"] == 0

    varied = [
        {**n, "bedtime_hour": 22.0 + (i % 5)} for i, n in enumerate(nights(14))
    ]
    assert build_circadian({"sleep_trend": varied}, TODAY)["consistent"] is False


def test_circadian_places_sessions_alongside_sleep():
    payload = {"sleep_trend": nights(3), "training": {"sessions": sessions([1], hour=19)}}
    rows = build_circadian(payload, TODAY, days=3)["rows"]
    row = next(r for r in rows if r["date"] == iso(1))
    assert row["sessions"][0]["hour"] == 19
    assert row["sleep"]["start"] == 23.0


def test_punch_card_finds_the_habitual_hour():
    payload = {"training": {"sessions": sessions(range(6), hour=18)}}
    card = build_punch_card(payload, TODAY)
    assert card["favourite_hour"] == 18
    assert card["sessions"] == 6


def test_streak_quality_grades_days_by_volume():
    payload = {"training": {"sessions": [
        {"date": iso(0), "type": "gym", "duration_min": 120},
        {"date": iso(1), "type": "gym", "duration_min": 20},
    ]}}
    cells = {c["date"]: c for c in build_streak_quality(payload, TODAY)["cells"]}
    assert cells[iso(0)]["level"] == 4     # long session
    assert cells[iso(1)]["level"] == 1     # short session
    assert cells[iso(2)]["level"] == 0     # rest day


def test_hypnogram_judges_sleep_architecture():
    h = build_hypnogram({"sleep_trend": nights(10)})
    assert h["avg_deep_pct"] > 0
    assert h["deep_verdict"] in ("low", "normal", "high")
    assert len(h["nights"]) == 10


def test_hypnogram_flags_low_deep_sleep():
    h = build_hypnogram({"sleep_trend": nights(10, deep_min=20, light_min=350, rem_min=60)})
    assert h["deep_verdict"] == "low"


def test_body_battery_flags_poor_recharge():
    good = build_body_battery({"sleep_trend": nights(10, body_battery_change=60)})
    assert good["verdict"] == "good"
    bad = build_body_battery({"sleep_trend": nights(10, body_battery_change=25)})
    assert bad["verdict"] == "bad"
    assert bad["poor_nights"] == 10


def test_volume_map_separates_well_trained_from_neglected():
    payload = {"training": {"sessions": [
        *sessions(range(0, 40, 2), muscles={"chest": 1.0}),
        {"date": iso(5), "type": "gym", "duration_min": 60, "muscle_groups": {"calves": 0.5}},
    ]}}
    v = build_volume_map(payload, TODAY)
    assert "chest" in v["well_trained"]
    assert "calves" in v["undertrained"]
    assert v["muscles"][0]["muscle"] == "chest"


# --------------------------------------------------------------- performance
def test_performance_modules_return_none_without_records():
    assert build_pace_curve({}) is None
    assert build_pr_wall({}) is None


def test_pace_curve_needs_at_least_two_records():
    assert build_pace_curve({"personal_records": [{"label": "5K", "value": "25:00"}]}) is None


def test_pace_curve_projects_the_race_distance():
    payload = {
        "personal_records": [
            {"label": "5K", "value": "25:00"},
            {"label": "10K", "value": "52:00"},
        ],
        "race": {"distance_km": 21.1},
    }
    c = build_pace_curve(payload)
    assert c["projection"]["km"] == 21.1
    # Riegel from a 25:00 5K puts a half around two hours.
    assert 6600 < c["projection"]["seconds"] < 8400
    assert c["curve"][0]["km"] == 1.0


def test_pace_curve_identifies_relative_strength():
    payload = {"personal_records": [
        {"label": "5K", "value": "25:00"},
        {"label": "10K", "value": "48:00"},   # much better than 5K predicts
    ]}
    c = build_pace_curve(payload)
    assert c["anchor"] == "10K"


def test_pr_wall_marks_records_the_prediction_says_are_beatable():
    payload = {
        "personal_records": [{"label": "10K", "value": "52:00"}],
        "race_predictions": {"10K": "49:00"},
    }
    wall = build_pr_wall(payload)
    assert wall["records"][0]["ripe"] is True
    assert wall["records"][0]["beatable_by_s"] == 180
    assert "10K" in wall["ripe"]


def test_pr_wall_tolerates_unparseable_values():
    wall = build_pr_wall({"personal_records": [{"label": "Longest Run", "value": "10.0 km"}]})
    assert wall["records"][0]["seconds"] is None


# ------------------------------------------------------------------ fuelling
def test_fuelling_modules_return_none_without_data():
    assert build_macro_plate({}, TODAY) is None
    assert build_protein_distribution({}, TODAY) is None
    assert build_eating_budget({}, TODAY, FatLossGoal()) is None
    assert build_eating_budget({"calorie_trend": [{"date": iso(1), "total_kcal": 2500}]}, TODAY, None) is None


def test_macro_plate_splits_by_calories_not_grams():
    payload = {
        "nutrition": [{"date": iso(0), "calories": 2000, "protein_g": 150, "carbs_g": 200, "fat_g": 50}],
        "nutrition_view": {"protein_target_g": 198, "week_avg_burn_kcal": 2800},
    }
    plate = build_macro_plate(payload, TODAY)
    by_macro = {s["macro"]: s for s in plate["slices"]}
    # 150*4=600, 200*4=800, 50*9=450 -> 1850 kcal from macros
    assert plate["kcal_from_macros"] == 1850
    assert by_macro["fat"]["pct"] == round(450 / 1850 * 100)
    assert by_macro["protein"]["delta_g"] == 150 - 198


def test_macro_plate_reports_calories_the_macros_do_not_explain():
    payload = {
        "nutrition": [{"date": iso(0), "calories": 2500, "protein_g": 100, "carbs_g": 100, "fat_g": 50}],
        "nutrition_view": {"protein_target_g": 198},
    }
    assert build_macro_plate(payload, TODAY)["unaccounted_kcal"] == 2500 - 1250


def test_protein_distribution_flags_a_single_dominant_meal():
    payload = {
        "nutrition": [
            {"date": iso(1), "meal": "dinner", "protein_g": 140},
            {"date": iso(1), "meal": "breakfast", "protein_g": 10},
        ],
        "nutrition_view": {"protein_target_g": 198},
    }
    dist = build_protein_distribution(payload, TODAY)
    assert dist["biggest_meal"] == "dinner"
    assert dist["concentrated"] is True
    assert next(m for m in dist["meals"] if m["meal"] == "dinner")["over_ceiling"] is True


def test_eating_budget_benchmarks_off_the_trailing_average_not_today():
    payload = {
        "calorie_trend": [
            {"date": iso(3), "total_kcal": 2800, "bmr_kcal": 2400, "active_kcal": 400},
            {"date": iso(2), "total_kcal": 2900, "bmr_kcal": 2400, "active_kcal": 500},
            {"date": iso(1), "total_kcal": 2900, "bmr_kcal": 2400, "active_kcal": 500},
            # Today is mid-day and heavily partial — must not pull the average down.
            {"date": iso(0), "total_kcal": 900, "bmr_kcal": 800, "active_kcal": 100},
        ],
        "nutrition_view": {"today_intake_kcal": 1500},
    }
    budget = build_eating_budget(payload, TODAY, FatLossGoal(weekly_rate_kg=0.4))
    assert budget["benchmark_days"] == 3
    assert budget["benchmark_kcal"] == round((2800 + 2900 + 2900) / 3)
    assert budget["daily_deficit_kcal"] == 440
    assert budget["daily_budget_kcal"] == budget["benchmark_kcal"] - 440
    assert budget["eaten_today_kcal"] == 1500
    assert budget["remaining_kcal"] == budget["daily_budget_kcal"] - 1500
    assert budget["over_budget"] is False


def test_eating_budget_flags_going_over():
    payload = {
        "calorie_trend": [{"date": iso(1), "total_kcal": 2400, "bmr_kcal": 2400, "active_kcal": 0}],
        "nutrition_view": {"today_intake_kcal": 3000},
    }
    budget = build_eating_budget(payload, TODAY, FatLossGoal(weekly_rate_kg=0.4))
    assert budget["daily_budget_kcal"] == 2400 - 440
    assert budget["remaining_kcal"] == (2400 - 440) - 3000
    assert budget["over_budget"] is True
    assert budget["rank"] == "bad"


# ---------------------------------------------------------------- benchmarks
def test_benchmarks_return_none_without_data():
    assert build_benchmarks({}) is None


def test_benchmarks_place_values_against_norms():
    payload = {
        "vo2max_trend": [{"date": iso(0), "vo2max": 45.0}],
        "rhr_trend": [{"date": iso(0), "rhr": 52}],
        "body_view": {"latest": {"body_fat_pct": 20.3}},
        "sleep_trend": nights(14),
    }
    b = build_benchmarks(payload)
    keys = {m["key"] for m in b["metrics"]}
    assert {"vo2max", "resting_hr", "body_fat_pct", "hrv", "sleep_hours"} == keys
    assert all(0 <= m["percentile"] <= 99 for m in b["metrics"])
    # Sorted worst-first so the weakest is actionable at the top.
    assert b["metrics"][0]["percentile"] <= b["metrics"][-1]["percentile"]


def test_lower_is_better_metrics_score_correctly():
    fast = build_benchmarks({"rhr_trend": [{"date": iso(0), "rhr": 45}]})
    slow = build_benchmarks({"rhr_trend": [{"date": iso(0), "rhr": 78}]})
    assert fast["metrics"][0]["percentile"] > slow["metrics"][0]["percentile"]


# -------------------------------------------------------- matrix, rings, digest
def test_matrix_needs_two_populated_metrics():
    assert build_matrix({}) is None


def test_matrix_correlates_every_pair_it_can():
    payload = {"sleep_trend": nights(14), "calorie_trend": [
        {"date": iso(i), "total_kcal": 2800 + i * 10} for i in range(14)
    ]}
    m = build_matrix(payload)
    assert m["metrics_compared"] >= 2
    assert all(c["n"] >= 0 for c in m["cells"])
    for cell in m["cells"]:
        if cell["r"] is not None:
            assert -1 <= cell["r"] <= 1


def test_matrix_leaves_thin_pairs_uncomputed():
    payload = {
        "sleep_trend": nights(14),
        "nutrition": [{"date": iso(0), "calories": 2000, "protein_g": 100}],
    }
    m = build_matrix(payload)
    assert m is not None
    for cell in m["cells"]:
        if cell["n"] < 5:
            assert cell["r"] is None


def test_rings_track_the_four_target_behaviours():
    payload = {
        "sleep_trend": nights(3),
        "nutrition_view": {"protein_target_g": 198, "today_protein_g": 150, "week_balance_kcal": -400},
        "training": {"sessions": sessions(range(4))},
        "fat_loss": {"required_daily_deficit_kcal": 440},
    }
    r = build_rings(payload, TODAY)
    assert {x["key"] for x in r["rings"]} == {"sleep", "protein", "training", "deficit"}
    assert all(0 <= x["pct"] <= 100 for x in r["rings"])


def test_rings_cap_at_a_hundred_percent():
    payload = {"nutrition_view": {"protein_target_g": 100, "today_protein_g": 400}}
    ring = build_rings(payload, TODAY)["rings"][0]
    assert ring["pct"] == 100


def test_digest_summarises_the_last_seven_days():
    payload = {
        "training": {"sessions": sessions(range(5))},
        "recent_runs": [{"date": iso(2), "distance_km": 7.05}],
        "sleep_trend": nights(7),
        "nutrition": [{"date": iso(1), "calories": 2400}],
    }
    d = build_digest(payload, TODAY)
    by_label = {s["label"]: s["value"] for s in d["stats"]}
    assert by_label["Sessions"] == 5
    assert by_label["Distance run"] == pytest.approx(7.05, abs=0.1)
    assert d["wins"]


def test_digest_flags_thin_food_logging():
    payload = {"nutrition": [{"date": iso(1), "calories": 2400}], "sleep_trend": nights(7)}
    d = build_digest(payload, TODAY)
    assert any("food logged" in w for w in d["watch"])


def test_digest_survives_an_empty_week():
    d = build_digest({}, TODAY)
    assert d["stats"]
    assert d["wins"] == []
