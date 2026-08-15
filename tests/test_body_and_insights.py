"""Body-composition grading and the cross-domain analyses."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_dashboard.domain.body import build_body_view, katch_mcardle_bmr
from garmin_dashboard.domain.insights import (
    Context,
    build_insights,
    confidence,
    pearson,
    strength,
)

ANCHOR = date(2026, 8, 15)

READING = {
    "date": "2026-08-15",
    "time": "09:42",
    "weight_kg": 98.9,
    "bmi": 27.1,
    "body_fat_pct": 20.3,
    "muscle_mass_kg": 74.9,
    "skeletal_muscle_kg": 38.2,
    "water_pct": 49.9,
    "protein_pct": 21.9,
    "bone_mass_kg": 4.0,
    "visceral_fat": 8,
    "subcutaneous_fat_pct": 15.3,
    "bmr": 2175,
    "body_score": 87,
}


# ------------------------------------------------------------------ body
def test_no_reading_means_no_view():
    assert build_body_view([], height_cm=192, today=ANCHOR) is None


def test_every_reported_metric_is_graded():
    v = build_body_view([READING], height_cm=192, today=ANCHOR)
    keys = {m["key"] for m in v["metrics"]}
    assert {"weight_kg", "bmi", "body_fat_pct", "muscle_mass_kg", "skeletal_muscle_kg",
            "water_pct", "protein_pct", "bone_mass_kg", "visceral_fat",
            "subcutaneous_fat_pct", "bmr", "body_score"} <= keys


def test_metrics_are_classified_against_reference_bands():
    v = build_body_view([READING], height_cm=192, today=ANCHOR)
    by_key = {m["key"]: m for m in v["metrics"]}
    assert by_key["water_pct"]["status"] == "low"
    assert by_key["visceral_fat"]["status"] == "normal"
    assert by_key["protein_pct"]["status"] == "optimal"
    assert by_key["body_fat_pct"]["status"] == "fair"
    assert by_key["bmi"]["status"] == "fair"


def test_only_out_of_range_metrics_need_attention():
    v = build_body_view([READING], height_cm=192, today=ANCHOR)
    assert {m["key"] for m in v["attention"]} == {"water_pct"}


def test_composition_splits_into_fat_and_lean_mass():
    v = build_body_view([READING], height_cm=192, today=ANCHOR)
    assert v["fat_mass_kg"] == pytest.approx(20.1, abs=0.1)
    assert v["lean_mass_kg"] == pytest.approx(78.8, abs=0.1)
    assert v["fat_mass_kg"] + v["lean_mass_kg"] == pytest.approx(98.9, abs=0.1)


def test_high_bmi_with_low_body_fat_is_called_out_as_a_bmi_artefact():
    v = build_body_view([READING], height_cm=192, today=ANCHOR)
    titles = " ".join(f["title"] for f in v["findings"])
    assert "BMI" in titles


def test_first_reading_says_it_is_a_baseline_not_a_trend():
    v = build_body_view([READING], height_cm=192, today=ANCHOR)
    assert any("baseline" in f["title"].lower() for f in v["findings"])


def test_second_reading_reports_the_change_and_drops_the_baseline_note():
    earlier = {**READING, "date": "2026-08-01", "weight_kg": 100.2, "body_fat_pct": 21.5, "muscle_mass_kg": 74.1}
    v = build_body_view([earlier, READING], height_cm=192, today=ANCHOR)
    assert not any("baseline" in f["title"].lower() for f in v["findings"])
    change = next(f for f in v["findings"] if f["title"].startswith("Since"))
    assert "-1.3kg" in change["detail"]
    # Fat down, muscle up: the good version, and it should say so.
    assert "want" in change["detail"] or "muscle" in change["detail"]


def test_deltas_are_attached_to_each_metric():
    earlier = {**READING, "date": "2026-08-01", "weight_kg": 100.2}
    v = build_body_view([earlier, READING], height_cm=192, today=ANCHOR)
    weight = next(m for m in v["metrics"] if m["key"] == "weight_kg")
    assert weight["delta"] == pytest.approx(-1.3, abs=0.01)


def test_katch_mcardle_uses_lean_mass():
    # 98.9kg at 20.3% fat -> 78.8kg lean -> 370 + 21.6*78.8
    assert katch_mcardle_bmr(98.9, 20.3) == pytest.approx(2072, abs=2)


def test_partial_reading_does_not_crash():
    v = build_body_view([{"date": "2026-08-15", "weight_kg": 98.9}], height_cm=192, today=ANCHOR)
    assert v["fat_mass_kg"] is None
    assert {m["key"] for m in v["metrics"]} == {"weight_kg"}


# -------------------------------------------------------------- statistics
def test_pearson_detects_a_perfect_relationship():
    assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)


def test_pearson_refuses_degenerate_input():
    assert pearson([1, 2], [3, 4]) is None       # too few points
    assert pearson([1, 1, 1], [1, 2, 3]) is None  # no variance


@pytest.mark.parametrize("n,expected", [(3, "early"), (7, "tentative"), (12, "solid"), (40, "solid")])
def test_confidence_grades_by_sample_size(n, expected):
    assert confidence(n) == expected


@pytest.mark.parametrize("r,expected", [(0.05, "none"), (0.25, "weak"), (0.4, "moderate"), (-0.8, "strong")])
def test_strength_grades_by_magnitude(r, expected):
    assert strength(r) == expected


# ---------------------------------------------------------------- insights
def _nights(count, score=80, hrv=60, hours=7.5, start=ANCHOR):
    return [
        {
            "date": (start - timedelta(days=i)).isoformat(),
            "score": score,
            "hours": hours,
            "avg_overnight_hrv": hrv,
            "bedtime_hour": 23.0,
            "sleep_need_min": 480,
        }
        for i in range(count)
    ]


def test_no_data_produces_no_findings():
    out = build_insights({}, ANCHOR)
    assert out["findings"] == []
    assert out["counts"]["total"] == 0


def test_sleep_debt_is_reported_when_short():
    payload = {"sleep_trend": _nights(7, hours=6.0)}
    out = build_insights(payload, ANCHOR)
    debt = next(f for f in out["findings"] if f["id"] == "sleep_debt")
    assert debt["severity"] == "warn"
    assert "sleep debt" in debt["headline"]


def test_meeting_sleep_need_is_reported_as_good():
    payload = {"sleep_trend": _nights(7, hours=8.2)}
    out = build_insights(payload, ANCHOR)
    debt = next(f for f in out["findings"] if f["id"] == "sleep_debt")
    assert debt["severity"] == "good"


def test_sleep_after_training_compares_against_rest_days():
    nights = _nights(10)
    # Nights following a training day score worse.
    sessions = []
    for i, night in enumerate(nights):
        if i % 2 == 0:
            prev = (date.fromisoformat(night["date"]) - timedelta(days=1)).isoformat()
            sessions.append({"date": prev, "type": "gym", "duration_min": 60})
            night["score"] = 68
        else:
            night["score"] = 84
    out = build_insights(
        {"sleep_trend": nights, "training": {"sessions": sessions}}, ANCHOR
    )
    f = next(x for x in out["findings"] if x["id"] == "sleep_vs_training")
    assert f["severity"] == "warn"
    assert "16" in f["headline"]


def test_findings_are_ordered_with_warnings_first():
    payload = {
        "sleep_trend": _nights(7, hours=5.5),
        "nutrition_view": {"week_balance_kcal": 0, "week_days_compared": 4},
    }
    out = build_insights(payload, ANCHOR)
    severities = [f["severity"] for f in out["findings"]]
    assert severities == sorted(severities, key=lambda s: {"warn": 0, "good": 1, "info": 2}[s])


def test_deficit_during_a_build_is_flagged():
    out = build_insights(
        {"nutrition_view": {"week_balance_kcal": -800, "week_days_compared": 5,
                            "week_avg_protein_g": 90, "protein_target_g": 178}},
        ANCHOR,
    )
    f = next(x for x in out["findings"] if x["id"] == "fuelling")
    assert f["severity"] == "warn"
    assert "800" in f["headline"]
    assert "short" in f["detail"]


def test_long_training_streak_is_flagged_as_recovery_risk():
    sessions = [
        {"date": (ANCHOR - timedelta(days=i)).isoformat(), "type": "gym", "duration_min": 60}
        for i in range(6)
    ]
    out = build_insights({"training": {"sessions": sessions}}, ANCHOR)
    f = next(x for x in out["findings"] if x["id"] == "recovery_debt")
    assert f["severity"] == "warn"
    assert "6 consecutive" in f["headline"]


def test_short_streak_is_not_flagged():
    sessions = [
        {"date": (ANCHOR - timedelta(days=i)).isoformat(), "type": "gym", "duration_min": 60}
        for i in range(3)
    ]
    out = build_insights({"training": {"sessions": sessions}}, ANCHOR)
    assert not any(f["id"] == "recovery_debt" for f in out["findings"])


def test_every_finding_carries_its_sample_size_and_confidence():
    payload = {
        "sleep_trend": _nights(9, hours=6.0),
        "nutrition_view": {"week_balance_kcal": -700, "week_days_compared": 5},
    }
    for f in build_insights(payload, ANCHOR)["findings"]:
        assert isinstance(f["n"], int) and f["n"] > 0
        assert f["confidence"] in ("early", "tentative", "solid")
        assert f["domains"]


def test_a_failing_analysis_cannot_take_down_the_page(monkeypatch):
    from garmin_dashboard.domain import insights

    def explode(ctx):
        raise ValueError("boom")

    monkeypatch.setattr(insights, "ANALYSES", [explode, insights.sleep_debt])
    out = insights.build_insights({"sleep_trend": _nights(7, hours=6.0)}, ANCHOR)
    assert len(out["findings"]) == 1


def test_context_indexes_nutrition_by_day():
    ctx = Context(
        {"nutrition": [
            {"date": "2026-08-14", "calories": 500, "protein_g": 40},
            {"date": "2026-08-14", "calories": 300, "protein_g": 20},
        ]},
        ANCHOR,
    )
    assert ctx.intake["2026-08-14"] == 800
    assert ctx.protein["2026-08-14"] == 60
