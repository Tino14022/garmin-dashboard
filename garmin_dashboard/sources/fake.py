"""A metrics source backed by literal data, for tests and offline builds."""
from __future__ import annotations

from datetime import date


def _in_range(rows, start: date, end: date, key: str = "date"):
    out = []
    for r in rows:
        value = r.get(key)
        try:
            d = date.fromisoformat(value)
        except (ValueError, TypeError):
            continue
        if start <= d <= end:
            out.append(r)
    return out


class FakeSource:
    """Implements MetricsSource from in-memory rows already in domain shape."""

    def __init__(
        self,
        *,
        name: str = "Test Athlete",
        runs: list[dict] | None = None,
        other_activities: list[dict] | None = None,
        load_trend: list[dict] | None = None,
        vo2max_trend: list[dict] | None = None,
        hrv_trend: list[dict] | None = None,
        rhr_trend: list[dict] | None = None,
        sleep_trend: list[dict] | None = None,
        calorie_trend: list[dict] | None = None,
        personal_records: list[dict] | None = None,
        race_predictions: dict | None = None,
    ):
        self._name = name
        self._runs = runs or []
        self._other = other_activities or []
        self._load = load_trend or []
        self._vo2 = vo2max_trend or []
        self._hrv = hrv_trend or []
        self._rhr = rhr_trend or []
        self._sleep = sleep_trend or []
        self._calories = calorie_trend or []
        self._prs = personal_records or []
        self._predictions = race_predictions or {}

    def athlete_name(self) -> str:
        return self._name

    def runs(self, start, end):
        return _in_range(self._runs, start, end)

    def other_activities(self, start, end):
        return _in_range(self._other, start, end)

    def load_trend(self, start, end):
        return _in_range(self._load, start, end)

    def vo2max_trend(self, start, end):
        return _in_range(self._vo2, start, end)

    def hrv_trend(self, start, end):
        return _in_range(self._hrv, start, end)

    def rhr_trend(self, start, end):
        return _in_range(self._rhr, start, end)

    def sleep_trend(self, start, end):
        return _in_range(self._sleep, start, end)

    def calorie_trend(self, start, end):
        return _in_range(self._calories, start, end)

    def personal_records(self):
        return list(self._prs)

    def race_predictions(self):
        return dict(self._predictions)
