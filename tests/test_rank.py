"""The shared quality scale.

Before this each module invented its own vocabulary and coloured it by hand, so
the same idea could appear in three colours on three tabs. Everything that
grades anything must now emit a `rank` from this five-level scale.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_dashboard.config import DEFAULT_SETTINGS, FatLossGoal
from garmin_dashboard.domain import rank
from garmin_dashboard.domain.benchmarks import build_benchmarks
from garmin_dashboard.domain.body import build_body_view
from garmin_dashboard.domain.goals import build_fat_loss_view
from garmin_dashboard.domain.insights import build_insights
from garmin_dashboard.domain.overview import build_overview
from garmin_dashboard.domain.readiness import build_readiness, build_todays_call

TODAY = date(2026, 8, 16)


def iso(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def nights(count=14, **over):
    base = dict(score=80, hours=7.5, avg_overnight_hrv=60, hrv_7d_average=60,
                resting_hr=52, deep_min=80, light_min=250, rem_min=90, awake_min=20,
                bedtime_hour=23.0, sleep_need_min=480, body_battery_change=55)
    base.update(over)
    return [{"date": iso(i), **base} for i in range(count)]


READING = {
    "date": "2026-08-16", "weight_kg": 98.35, "bmi": 26.9, "body_fat_pct": 20.3,
    "muscle_mass_kg": 74.4, "water_pct": 50.0, "protein_pct": 21.7,
    "visceral_fat": 8, "bmr": 2165,
}


# ------------------------------------------------------------------- scale
def test_the_scale_runs_best_to_worst():
    assert rank.RANKS == ["excellent", "good", "fair", "bad", "terrible"]
    assert rank.RANK_ORDER["excellent"] < rank.RANK_ORDER["terrible"]


@pytest.mark.parametrize("score,expected", [
    (100, "excellent"), (85, "excellent"), (84, "good"), (70, "good"),
    (69, "fair"), (50, "fair"), (49, "bad"), (30, "bad"), (29, "terrible"), (0, "terrible"),
])
def test_scores_band_consistently(score, expected):
    assert rank.from_score(score) == expected


def test_a_missing_score_has_no_rank():
    assert rank.from_score(None) is None


@pytest.mark.parametrize("pct,expected", [
    (99, "excellent"), (90, "excellent"), (80, "good"), (50, "fair"), (20, "bad"), (5, "terrible"),
])
def test_percentiles_band_consistently(pct, expected):
    assert rank.from_percentile(pct) == expected


@pytest.mark.parametrize("severity,expected", [
    ("good", "good"), ("info", "fair"), ("warn", "bad"), ("bad", "terrible"),
])
def test_severities_map_onto_the_scale(severity, expected):
    assert rank.from_severity(severity) == expected


def test_an_unknown_severity_lands_mid_scale_rather_than_crashing():
    assert rank.from_severity("nonsense") == "fair"
    assert rank.from_severity(None) == "fair"


@pytest.mark.parametrize("quality,expected", [
    ("EXCELLENT", "excellent"), ("GOOD", "good"), ("FAIR", "fair"), ("POOR", "bad"),
])
def test_garmins_own_sleep_words_map_onto_the_scale(quality, expected):
    assert rank.from_quality(quality) == expected


def test_unknown_quality_is_not_guessed():
    assert rank.from_quality("SPLENDID") is None
    assert rank.from_quality(None) is None


def test_worst_picks_the_lowest_rank():
    assert rank.worst(["good", "terrible", "excellent"]) == "terrible"
    assert rank.worst(["excellent", "good"]) == "good"
    assert rank.worst([]) is None


# ------------------------------------------ every grading module emits a rank
def test_body_metrics_and_findings_are_ranked():
    v = build_body_view([READING], height_cm=192, today=TODAY)
    assert all(m["rank"] in rank.RANKS for m in v["metrics"])
    assert all(f["rank"] in rank.RANKS for f in v["findings"])
    assert v["worst_rank"] in rank.RANKS


def test_body_attention_uses_the_shared_scale_not_ad_hoc_statuses():
    v = build_body_view([READING], height_cm=192, today=TODAY)
    assert all(m["rank"] in ("bad", "terrible") for m in v["attention"])


def test_benchmarks_are_ranked():
    payload = {"rhr_trend": [{"date": iso(0), "rhr": 52}], "sleep_trend": nights()}
    for m in build_benchmarks(payload)["metrics"]:
        assert m["rank"] in rank.RANKS


def test_readiness_and_its_components_are_ranked():
    payload = {"sleep_trend": nights(), "training": {"muscle_scores": {"chest": 0.2}}}
    r = build_readiness(payload, TODAY)
    assert r["rank"] in rank.RANKS
    for c in r["components"]:
        assert c["rank"] in rank.RANKS or c["score"] is None


def test_todays_call_is_ranked():
    payload = {"sleep_trend": nights(), "training": {"sessions": [], "muscle_scores": {}}}
    call = build_todays_call(payload, build_readiness(payload, TODAY), TODAY)
    assert call["rank"] in rank.RANKS


def test_insight_findings_are_ranked():
    out = build_insights({"sleep_trend": nights(hours=5.5)}, TODAY)
    assert out["findings"]
    for f in out["findings"]:
        assert f["rank"] in rank.RANKS


def test_fat_loss_findings_are_ranked():
    v = build_fat_loss_view([READING], {}, FatLossGoal(), TODAY, race_date=date(2026, 10, 4))
    for f in v["findings"]:
        assert f["rank"] in rank.RANKS


def test_overview_cards_and_priorities_are_ranked():
    payload = {
        "sleep_trend": nights(),
        "training": {"sessions": [], "muscle_scores": {"chest": 0.9}},
        "insights": {"findings": [
            {"severity": "warn", "headline": "x", "detail": "y", "confidence": "solid"},
        ]},
    }
    ov = build_overview(payload, TODAY)
    for c in ov["cards"]:
        assert c["rank"] in rank.RANKS
    for p in ov["priorities"]:
        assert p["rank"] in rank.RANKS


def test_a_warning_never_ranks_better_than_a_good_result():
    """The bug this caught: findings rendered without their rank defaulted to
    fair, so warnings and neutral notes looked identical."""
    assert rank.RANK_ORDER[rank.from_severity("warn")] > rank.RANK_ORDER[rank.from_severity("good")]
    assert rank.RANK_ORDER[rank.from_severity("warn")] > rank.RANK_ORDER[rank.from_severity("info")]
