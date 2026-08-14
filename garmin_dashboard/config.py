"""Configuration for the dashboard build.

Everything the athlete might want to change lives here as data, so no other
module needs editing to point the build at a different race, body, or timezone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class RaceConfig:
    name: str
    date: date
    distance_km: float


@dataclass(frozen=True)
class AthleteConfig:
    height_cm: int
    weight_kg: float
    protein_g_per_kg: float = 1.8


@dataclass(frozen=True)
class WindowConfig:
    """How far back each family of metrics is fetched, in weeks."""

    trend: int = 12
    recovery: int = 4
    recent_runs: int = 4
    # Garmin's daily-summary endpoint is one call per day, so this stays modest.
    calories: int = 5


@dataclass(frozen=True)
class Settings:
    race: RaceConfig
    athlete: AthleteConfig
    windows: WindowConfig = field(default_factory=WindowConfig)
    # The build runs on a UTC CI runner; without this, "today" flips over at
    # 02:00 local in summer and the dashboard shows yesterday for two hours.
    # Held as a name and resolved lazily: Windows ships no system tz database,
    # so constructing ZoneInfo at import time makes the module unimportable
    # there even for code paths that never ask what day it is.
    timezone_name: str = "Europe/Warsaw"
    # Account's first day of week, as Python weekday numbers (Mon=0 .. Sun=6).
    week_starts_on: int = 6

    def tzinfo(self):
        try:
            return ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, KeyError):
            print(
                f"  ! no tz database entry for {self.timezone_name}; "
                "falling back to UTC (install the 'tzdata' package)"
            )
            return timezone.utc

    def today(self) -> date:
        return datetime.now(self.tzinfo()).date()


DEFAULT_SETTINGS = Settings(
    race=RaceConfig(
        name="Wizz Air Half Marathon",
        date=date(2026, 10, 4),
        distance_km=21.1,
    ),
    athlete=AthleteConfig(height_cm=192, weight_kg=95),
)
