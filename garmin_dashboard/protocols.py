"""Abstractions the pipeline depends on.

The build depends on these protocols rather than on `garminconnect` directly,
so the whole pipeline can run against a recorded or synthetic source with no
network and no credentials. Each protocol is deliberately narrow: a caller that
only needs sleep data should not have to satisfy the whole Garmin surface.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable


@runtime_checkable
class ActivitySource(Protocol):
    def runs(self, start: date, end: date) -> list[dict]: ...

    def other_activities(self, start: date, end: date) -> list[dict]: ...


@runtime_checkable
class LoadSource(Protocol):
    def load_trend(self, start: date, end: date) -> list[dict]: ...

    def vo2max_trend(self, start: date, end: date) -> list[dict]: ...


@runtime_checkable
class RecoverySource(Protocol):
    def hrv_trend(self, start: date, end: date) -> list[dict]: ...

    def rhr_trend(self, start: date, end: date) -> list[dict]: ...

    def sleep_trend(self, start: date, end: date) -> list[dict]: ...


@runtime_checkable
class EnergySource(Protocol):
    def calorie_trend(self, start: date, end: date) -> list[dict]: ...


@runtime_checkable
class AchievementSource(Protocol):
    def personal_records(self) -> list[dict]: ...

    def race_predictions(self) -> dict: ...


@runtime_checkable
class MetricsSource(
    ActivitySource, LoadSource, RecoverySource, EnergySource, AchievementSource, Protocol
):
    """The full surface the build consumes. Composed of the narrow protocols
    above so individual transforms can depend on only the slice they use."""

    def athlete_name(self) -> str: ...


@runtime_checkable
class DataStore(Protocol):
    """Manually-logged data (nutrition, gym annotations, body comp, plans)."""

    def load(self, name: str, default): ...
