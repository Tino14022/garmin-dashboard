"""The overview: latest state per domain, staleness, and what needs attention."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_dashboard.domain.overview import build_overview

TODAY = date(2026, 8, 15)


def iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def cards_by_domain(payload):
    return {c["domain"]: c for c in build_overview(payload, TODAY)["cards"]}


def test_empty_payload_still_produces_a_page():
    ov = build_overview({}, TODAY)
    assert ov["cards"]
    assert ov["priorities"] == []
    assert all(c["value"] in ("—", "All clear") for c in ov["cards"])


def test_each_domain_reports_its_most_recent_entry():
    payload = {
        "sleep_trend": [
            {"date": iso(3), "score": 60, "hours": 6.0},
            {"date": iso(1), "score": 84, "hours": 7.4, "quality": "GOOD"},
        ],
        "training": {"sessions": [
            {"date": iso(1), "type": "gym", "subtype": "push", "duration_min": 65},
            {"date": iso(4), "type": "gym", "subtype": "legs", "duration_min": 70},
        ], "gamification": {"streak_days": 3}},
        "recent_runs": [{"date": iso(2), "distance_km": 7.05, "pace_label": "6:25/km"}],
        "nutrition": [{"date": iso(1), "calories": 2400, "protein_g": 180}],
        "nutrition_view": {"protein_target_g": 198},
        "body_view": {"latest": {"weight_kg": 98.9, "body_fat_pct": 20.3}, "measured_on": iso(0), "fat_mass_kg": 20.1},
    }
    c = cards_by_domain(payload)
    assert c["sleep"]["value"] == 84            # newest night, not the older one
    assert c["training"]["value"] == "Push"     # newest session
    assert c["running"]["value"] == 7.05
    assert c["nutrition"]["value"] == 2400
    assert c["body"]["value"] == 98.9


def test_age_is_reported_in_plain_language():
    payload = {"sleep_trend": [{"date": iso(0), "score": 80}]}
    assert cards_by_domain(payload)["sleep"]["age_label"] == "today"
    payload = {"sleep_trend": [{"date": iso(1), "score": 80}]}
    assert cards_by_domain(payload)["sleep"]["age_label"] == "yesterday"
    payload = {"sleep_trend": [{"date": iso(5), "score": 80}]}
    assert cards_by_domain(payload)["sleep"]["age_label"] == "5 days ago"


def test_a_domain_that_has_stopped_being_updated_is_flagged():
    """The thing an overview can say that no single tab can."""
    payload = {"nutrition": [{"date": iso(6), "calories": 2400, "protein_g": 180}]}
    ov = build_overview(payload, TODAY)
    card = next(c for c in ov["cards"] if c["domain"] == "nutrition")
    assert card["stale"] is True
    assert card["status"] == "warn"
    assert "nutrition" in ov["stale_domains"]


def test_a_freshly_updated_domain_is_not_flagged():
    payload = {"nutrition": [{"date": iso(1), "calories": 2400, "protein_g": 180}]}
    ov = build_overview(payload, TODAY)
    assert ov["stale_domains"] == []


def test_domains_have_their_own_staleness_thresholds():
    """A weigh-in 6 days old is fine; a food log 6 days old is not."""
    body = {"body_view": {"latest": {"weight_kg": 98.9, "body_fat_pct": 20.3}, "measured_on": iso(6), "fat_mass_kg": 20.1}}
    assert build_overview(body, TODAY)["stale_domains"] == []
    food = {"nutrition": [{"date": iso(6), "calories": 2400}]}
    assert build_overview(food, TODAY)["stale_domains"] == ["nutrition"]


def test_sleep_status_reflects_the_score():
    assert cards_by_domain({"sleep_trend": [{"date": iso(0), "score": 85}]})["sleep"]["status"] == "good"
    assert cards_by_domain({"sleep_trend": [{"date": iso(0), "score": 55}]})["sleep"]["status"] == "warn"
    assert cards_by_domain({"sleep_trend": [{"date": iso(0), "score": 72}]})["sleep"]["status"] == "info"


def test_recovery_card_names_the_least_recovered_group():
    payload = {"training": {"muscle_scores": {"chest": 0.92, "quads": 0.5, "lats": 0.1}}}
    card = cards_by_domain(payload)["recovery"]
    assert card["value"] == "Chest"
    assert card["status"] == "warn"
    assert "2 groups still recovering" in card["sub"]


def test_recovery_card_when_nothing_is_sore():
    card = cards_by_domain({"training": {"muscle_scores": {}}})["recovery"]
    assert card["value"] == "All clear"
    assert card["status"] == "good"


def test_race_card_reflects_whether_the_plan_is_on_track():
    behind = {
        "race": {"days_remaining": 50, "name": "Half"},
        "race_plan": {"on_track": False, "current_longest_km": 7.05, "race_distance_km": 21.1},
    }
    assert cards_by_domain(behind)["race"]["status"] == "warn"
    ahead = {**behind, "race_plan": {**behind["race_plan"], "on_track": True}}
    assert cards_by_domain(ahead)["race"]["status"] == "good"


def test_goal_card_disappears_without_a_goal():
    assert "goal" not in cards_by_domain({})
    with_goal = {"fat_loss": {"fat_to_lose_kg": 2.8, "current_body_fat_pct": 20.3,
                              "target_body_fat_pct": 18.0, "required_daily_deficit_kcal": 440}}
    assert cards_by_domain(with_goal)["goal"]["value"] == 2.8


def test_goal_card_reports_a_reached_target():
    reached = {"fat_loss": {"fat_to_lose_kg": -0.4, "target_body_fat_pct": 18.0}}
    card = cards_by_domain(reached)["goal"]
    assert card["value"] == "Reached"
    assert card["status"] == "good"


def test_priorities_gather_warnings_from_every_source():
    payload = {
        "build_health": {"healthy": False, "failures": [{"name": "sleep_trend", "error": "401"}]},
        "insights": {"findings": [
            {"severity": "warn", "headline": "Bedtime swings", "detail": "...", "confidence": "solid"},
            {"severity": "good", "headline": "Fine", "detail": "..."},
        ]},
        "fat_loss": {"findings": [{"severity": "warn", "title": "Lean mass down", "detail": "..."}]},
        "body_view": {"findings": [{"severity": "warn", "title": "Water low", "detail": "..."}]},
    }
    ov = build_overview(payload, TODAY)
    titles = [p["title"] for p in ov["priorities"]]
    assert "Some Garmin data is missing" in titles
    assert "Bedtime swings" in titles
    assert "Lean mass down" in titles
    assert "Water low" in titles
    assert "Fine" not in titles       # good news is not a priority
    assert ov["priority_count"] == 4


def test_priorities_are_capped_but_the_true_count_is_kept():
    payload = {"insights": {"findings": [
        {"severity": "warn", "headline": f"Issue {i}", "detail": "..."} for i in range(9)
    ]}}
    ov = build_overview(payload, TODAY)
    assert len(ov["priorities"]) == 5
    assert ov["priority_count"] == 9


def test_today_block_carries_the_in_progress_numbers():
    payload = {"nutrition_view": {
        "today_intake_kcal": 820, "today_protein_g": 55,
        "today_burn_so_far_kcal": 1035, "protein_target_g": 198,
    }}
    assert build_overview(payload, TODAY)["today"] == {
        "intake_kcal": 820, "protein_g": 55, "burn_kcal": 1035, "protein_target_g": 198,
    }


def test_every_card_links_to_a_real_tab():
    payload = {"training": {"muscle_scores": {"chest": 0.9}}, "fat_loss": {"fat_to_lose_kg": 2.0}}
    tabs = {"overview", "analysis", "workout", "training", "running", "sleep", "nutrition", "body"}
    for card in build_overview(payload, TODAY)["cards"]:
        assert card["tab"] in tabs, f"{card['domain']} links to unknown tab {card['tab']}"


def test_a_failing_card_cannot_take_down_the_page(monkeypatch):
    from garmin_dashboard.domain import overview

    def explode(payload, today):
        raise ValueError("boom")

    monkeypatch.setattr(overview, "CARD_BUILDERS", [explode, overview._sleep_card])
    ov = overview.build_overview({"sleep_trend": [{"date": iso(0), "score": 80}]}, TODAY)
    assert len(ov["cards"]) == 1
