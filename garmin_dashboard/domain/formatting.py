"""Value formatting and calendar helpers shared across the transforms."""
from __future__ import annotations

from datetime import date, timedelta


def iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def parse_iso(value) -> date | None:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def fmt_pace(sec_per_km: float | None) -> str:
    if not sec_per_km or sec_per_km <= 0:
        return "-"
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}/km"


def fmt_duration(total_seconds: float | None) -> str:
    if not total_seconds:
        return "-"
    total_seconds = int(round(total_seconds))
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def week_start(d: date, week_starts_on: int = 6) -> date:
    """Start of the calendar week containing `d`.

    `week_starts_on` uses Python weekday numbers (Mon=0 .. Sun=6); the Garmin
    account's week begins on Sunday, hence the default of 6.
    """
    return d - timedelta(days=(d.weekday() - week_starts_on) % 7)
