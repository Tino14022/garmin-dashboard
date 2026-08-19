"""Gambling losses: totals, and what the money could have bought instead."""
from __future__ import annotations

from datetime import date

from .formatting import parse_iso, week_start

# Priced in MKD denars so the comparison lands in numbers the athlete actually
# recognises, not an abstract currency. Ordered cheapest to priciest so the
# opportunity-cost pick can just take the last one the total affords.
# Images live in icons/opportunity/ (re-hosted from Wikimedia Commons rather
# than hotlinked — see icons/opportunity/CREDITS.md for source and licence).
OPPORTUNITY_ITEMS: list[dict] = [
    {"name": "coffee", "plural": "coffees", "price_den": 80, "image": "coffee.jpg"},
    {"name": "work canteen lunch", "plural": "work canteen lunches", "price_den": 210, "image": "lunch.png"},
    {"name": "movie ticket", "plural": "movie tickets", "price_den": 250, "image": "movie_ticket.jpg"},
    {"name": "half marathon race entry", "plural": "half marathon race entries", "price_den": 2000, "image": "race_medal.jpg"},
    {"name": "Whey Core protein tub", "plural": "tubs of Whey Core protein", "price_den": 2840, "image": "protein_tub.jpg"},
    {"name": "pair of running shoes", "plural": "pairs of running shoes", "price_den": 4500, "image": "running_shoes.jpg"},
    {"name": "weekend trip", "plural": "weekend trips", "price_den": 15000, "image": "suitcase.jpg"},
    {"name": "month's rent", "plural": "months' rent", "price_den": 18000, "image": "apartment.jpg"},
    {"name": "flagship smartphone", "plural": "flagship smartphones", "price_den": 70000, "image": "smartphone.jpg"},
    {"name": "used car", "plural": "used cars", "price_den": 150000, "image": "used_car.jpg"},
]


def build_opportunity_cost(total_den: float) -> dict | None:
    """Picks the priciest item the total loss could have fully bought.

    The point is to sting, so this reaches for the biggest thing that would
    have cost no more than what actually got lost — a handful of coffees
    says nothing, a pair of running shoes does.
    """
    if total_den <= 0:
        return None
    affordable = [i for i in OPPORTUNITY_ITEMS if i["price_den"] <= total_den]
    item = affordable[-1] if affordable else OPPORTUNITY_ITEMS[0]
    count = total_den / item["price_den"]
    return {
        "item": item["name"],
        "item_plural": item["plural"],
        "count": round(count, 1) if count < 10 else round(count),
        "price_den": item["price_den"],
        "image": item["image"],
    }


def build_gambling_view(
    entries: list[dict],
    today: date,
    *,
    week_starts_on: int = 0,
) -> dict | None:
    rows = [e for e in entries if e.get("date") and e.get("amount_den") is not None]
    if not rows:
        return None

    by_date: dict[str, float] = {}
    for e in rows:
        by_date[e["date"]] = by_date.get(e["date"], 0) + e["amount_den"]

    total_lost = sum(by_date.values())
    wk_start = week_start(today, week_starts_on)
    week_total = sum(
        amount for d, amount in by_date.items()
        if (dd := parse_iso(d)) and wk_start <= dd <= today
    )
    month_total = sum(
        amount for d, amount in by_date.items()
        if (dd := parse_iso(d)) and dd.year == today.year and dd.month == today.month
    )
    worst_date, worst_amount = max(by_date.items(), key=lambda kv: kv[1])

    return {
        "entry_count": len(rows),
        "days_logged": len(by_date),
        "tracking_since": min(by_date),
        "total_lost_den": round(total_lost),
        "week_total_den": round(week_total),
        "month_total_den": round(month_total),
        "by_date": {d: round(v) for d, v in by_date.items()},
        "worst_day": {"date": worst_date, "amount_den": round(worst_amount)},
        "opportunity_cost": build_opportunity_cost(total_lost),
    }
