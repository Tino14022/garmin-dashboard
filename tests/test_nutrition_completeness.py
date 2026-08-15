"""Partial Garmin days must not be averaged in as if they were whole.

Garmin accrues a day's basal burn as it goes, so a day the watch did not cover
end to end arrives with a short BMR and a correspondingly short total. Averaging
such a day in understates burn — and on a day where food *was* logged, it can
flip a maintenance week into a large fake surplus. This is the case that shipped:

    2026-08-13   3418 total = 952 active + 2466 BMR   complete
    2026-08-14   2171 total = 272 active + 1899 BMR   partial (~18h covered)

Aug 14 was the only day with food logged, so the whole weekly verdict came from
a truncated day and read "+2414 kcal/day, likely building muscle".
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from garmin_dashboard.domain.nutrition import (
    build_nutrition_view,
    is_complete_day,
    typical_daily_bmr,
)

TODAY = date(2026, 8, 15)


def day(offset: int, *, active: float, bmr: float) -> dict:
    """Garmin's total is exactly basal + active, so the fixture mirrors that."""
    return {
        "date": (TODAY - timedelta(days=offset)).isoformat(),
        "total_kcal": active + bmr,
        "active_kcal": active,
        "bmr_kcal": bmr,
    }


FULL_BMR = 2466.0


@pytest.fixture
def week():
    """Six complete days plus the partial Aug 14 that caused the bug."""
    rows = [day(n, active=140 + n * 40, bmr=FULL_BMR) for n in range(2, 8)]
    rows.append(day(1, active=272, bmr=1899))
    return rows


def test_typical_bmr_is_the_median_not_the_mean(week):
    assert typical_daily_bmr(week) == FULL_BMR


def test_a_short_bmr_day_is_recognised_as_partial(week):
    assert is_complete_day(week[-1], FULL_BMR) is False
    assert is_complete_day(week[0], FULL_BMR) is True


def test_day_with_no_bmr_reported_is_assumed_usable():
    assert is_complete_day({"total_kcal": 2600}, FULL_BMR) is True


def test_partial_day_is_excluded_from_the_average(week):
    intake = [
        {"date": (TODAY - timedelta(days=n)).isoformat(), "calories": 2500, "protein_g": 150}
        for n in range(1, 8)
    ]
    view = build_nutrition_view(
        intake, week, [], TODAY, default_weight_kg=98.9, protein_g_per_kg=1.8
    )
    assert view["partial_days_excluded"] == [(TODAY - timedelta(days=1)).isoformat()]
    assert view["week_days_compared"] == 6
    # The partial day's 2171 would have dragged this down had it counted.
    assert view["week_avg_burn_kcal"] > 2600


def test_the_shipped_case_no_longer_invents_a_surplus():
    """Only the partial day has food logged — the exact situation on the site."""
    complete = [day(n, active=434, bmr=FULL_BMR) for n in range(2, 8)]
    partial = day(1, active=272, bmr=1899)
    intake = [{"date": partial["date"], "calories": 4585, "protein_g": 234}]

    view = build_nutrition_view(
        intake, complete + [partial], [], TODAY, default_weight_kg=98.9, protein_g_per_kg=1.8
    )
    # With the only logged day excluded there is nothing honest to compare, and
    # saying so beats reporting a +2414 surplus off a truncated day.
    assert view["week_days_compared"] == 0
    assert view["week_balance_kcal"] is None
    assert view["classification"] is None
    assert partial["date"] in view["partial_days_excluded"]


def test_one_logged_day_reports_numbers_but_refuses_a_verdict():
    """A single day was enough to print 'likely building muscle'. It isn't."""
    rows = [day(n, active=354, bmr=FULL_BMR) for n in range(1, 8)]
    intake = [{"date": rows[0]["date"], "calories": 4585, "protein_g": 234}]
    view = build_nutrition_view(
        intake, rows, [], TODAY, default_weight_kg=98.9, protein_g_per_kg=1.8
    )
    assert view["week_days_compared"] == 1
    assert view["week_balance_kcal"] == 1765     # the number is still shown
    assert view["classification"] is None         # but no conclusion is drawn
    assert view["too_few_days_for_verdict"] is True


def test_verdict_appears_once_enough_days_are_logged():
    rows = [day(n, active=354, bmr=FULL_BMR) for n in range(1, 8)]
    intake = [
        {"date": r["date"], "calories": 4585, "protein_g": 234} for r in rows[:3]
    ]
    view = build_nutrition_view(
        intake, rows, [], TODAY, default_weight_kg=98.9, protein_g_per_kg=1.8
    )
    assert view["week_days_compared"] == 3
    assert view["classification"] == "surplus_adequate_protein"
    assert view["too_few_days_for_verdict"] is False


def test_burn_is_reported_split_into_basal_and_active(week):
    intake = [
        {"date": (TODAY - timedelta(days=n)).isoformat(), "calories": 2500, "protein_g": 150}
        for n in range(2, 8)
    ]
    view = build_nutrition_view(
        intake, week, [], TODAY, default_weight_kg=98.9, protein_g_per_kg=1.8
    )
    assert view["week_avg_bmr_kcal"] == FULL_BMR
    assert view["week_avg_active_kcal"] > 0
    # The headline burn is the sum of the two halves, not the basal figure alone.
    assert view["week_avg_burn_kcal"] == pytest.approx(
        view["week_avg_bmr_kcal"] + view["week_avg_active_kcal"], abs=1
    )


def test_today_reports_its_own_split(week):
    today_row = {"date": TODAY.isoformat(), "total_kcal": 962, "active_kcal": 2, "bmr_kcal": 960}
    view = build_nutrition_view(
        [], week + [today_row], [], TODAY, default_weight_kg=98.9, protein_g_per_kg=1.8
    )
    assert view["today_burn_so_far_kcal"] == 962
    assert view["today_active_kcal"] == 2
    assert view["today_bmr_kcal"] == 960


def test_all_complete_days_means_nothing_excluded():
    rows = [day(n, active=434, bmr=FULL_BMR) for n in range(1, 8)]
    intake = [
        {"date": r["date"], "calories": 2900, "protein_g": 178} for r in rows
    ]
    view = build_nutrition_view(
        intake, rows, [], TODAY, default_weight_kg=98.9, protein_g_per_kg=1.8
    )
    assert view["partial_days_excluded"] == []
    assert view["week_days_compared"] == 7
    assert view["classification"] == "maintenance"
