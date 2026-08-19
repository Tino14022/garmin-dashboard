"""Gambling loss tracking: totals, calendar data, and the opportunity-cost jab."""
from __future__ import annotations

from datetime import date

from garmin_dashboard.domain.gambling import build_gambling_view, build_opportunity_cost

TODAY = date(2026, 8, 19)  # a Wednesday


def test_no_entries_means_no_panel():
    assert build_gambling_view([], TODAY) is None


def test_entries_missing_amount_or_date_are_ignored():
    assert build_gambling_view([{"date": "2026-08-19"}], TODAY) is None
    assert build_gambling_view([{"amount_den": 500}], TODAY) is None


def test_totals_sum_across_entries():
    v = build_gambling_view(
        [
            {"date": "2026-08-18", "amount_den": 300},
            {"date": "2026-08-19", "amount_den": 500},
        ],
        TODAY,
    )
    assert v["total_lost_den"] == 800
    assert v["entry_count"] == 2
    assert v["days_logged"] == 2


def test_same_day_entries_are_merged_by_date_for_the_calendar():
    v = build_gambling_view(
        [
            {"date": "2026-08-19", "amount_den": 200, "note": "poker"},
            {"date": "2026-08-19", "amount_den": 300, "note": "sports betting"},
        ],
        TODAY,
    )
    assert v["by_date"] == {"2026-08-19": 500}
    assert v["days_logged"] == 1


def test_week_total_only_counts_the_current_week():
    # Week starts Monday (2026-08-17); the previous Friday is out of range.
    v = build_gambling_view(
        [
            {"date": "2026-08-14", "amount_den": 1000},  # last week (Friday)
            {"date": "2026-08-17", "amount_den": 100},   # this Monday
            {"date": "2026-08-19", "amount_den": 200},   # today
        ],
        TODAY,
        week_starts_on=0,
    )
    assert v["week_total_den"] == 300
    assert v["total_lost_den"] == 1300


def test_month_total_only_counts_the_current_month():
    v = build_gambling_view(
        [
            {"date": "2026-07-30", "amount_den": 1000},
            {"date": "2026-08-01", "amount_den": 50},
            {"date": "2026-08-19", "amount_den": 200},
        ],
        TODAY,
    )
    assert v["month_total_den"] == 250


def test_worst_day_is_the_single_highest_loss_day():
    v = build_gambling_view(
        [
            {"date": "2026-08-17", "amount_den": 100},
            {"date": "2026-08-18", "amount_den": 900},
        ],
        TODAY,
    )
    assert v["worst_day"] == {"date": "2026-08-18", "amount_den": 900}


def test_opportunity_cost_is_absent_for_zero_or_negative():
    assert build_opportunity_cost(0) is None
    assert build_opportunity_cost(-50) is None


def test_opportunity_cost_picks_the_priciest_affordable_item():
    # 3000 den affords the 2840-den protein tub but not the 4500-den shoes.
    oc = build_opportunity_cost(3000)
    assert oc["item"] == "Whey Core protein tub"
    assert oc["price_den"] == 2840
    assert oc["count"] == 1.1


def test_opportunity_cost_carries_an_emoji_for_every_item():
    """The page shows a picture of the item, not just its name — every entry
    in the price list needs one, or that item would silently render blank."""
    from garmin_dashboard.domain.gambling import OPPORTUNITY_ITEMS

    for item in OPPORTUNITY_ITEMS:
        assert item.get("emoji"), f"{item['name']} has no emoji"

    oc = build_opportunity_cost(3000)
    assert oc["emoji"] == "🧴"  # Whey Core protein tub


def test_opportunity_cost_falls_back_to_the_cheapest_item_below_its_price():
    oc = build_opportunity_cost(40)
    assert oc["item"] == "coffee"
    assert oc["count"] == 0.5


def test_opportunity_cost_rounds_large_counts_to_whole_numbers():
    oc = build_opportunity_cost(2_000_000)
    assert oc["item"] == "used car"
    assert oc["count"] == 13
    assert isinstance(oc["count"], int)
