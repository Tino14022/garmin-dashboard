"""Shared fixtures.

`legacy_reference.py` is a byte-identical snapshot of dashboard.py from before
the SOLID refactor. It is imported here only so the equivalence test can prove
the refactor did not change any computed value. It imports garminconnect at
module scope, which is not installed in the test environment, so a stub module
is registered before import — nothing in the transforms actually calls it.
"""
from __future__ import annotations

import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("garminconnect", types.ModuleType("garminconnect"))

ANCHOR = date(2026, 8, 14)


def _iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _run(day_offset: int, km: float, minutes: float, label="BASE", hr=150):
    d = ANCHOR - timedelta(days=day_offset)
    return {
        "activityId": 1000 + day_offset,
        "activityName": "Morning Run",
        "startTimeLocal": f"{_iso(d)} 07:15:00",
        "distance": km * 1000,
        "duration": minutes * 60,
        "averageHR": hr,
        "maxHR": hr + 20,
        "trainingEffectLabel": label,
        "activityTrainingLoad": 90.0,
        "activityType": {"typeKey": "running"},
    }


def _gym(day_offset: int, name: str, minutes: float = 65):
    d = ANCHOR - timedelta(days=day_offset)
    return {
        "activityId": 2000 + day_offset,
        "activityName": name,
        "startTimeLocal": f"{_iso(d)} 18:30:00",
        "distance": 0,
        "duration": minutes * 60,
        "activityType": {"typeKey": "strength_training"},
    }


def _other(day_offset: int, name: str, type_key: str, minutes: float = 80):
    d = ANCHOR - timedelta(days=day_offset)
    return {
        "activityId": 3000 + day_offset,
        "activityName": name,
        "startTimeLocal": f"{_iso(d)} 20:00:00",
        "distance": 0,
        "duration": minutes * 60,
        "activityType": {"typeKey": type_key},
    }


RAW_RUNS = [
    _run(1, 7.05, 45.3, "TEMPO", 162),
    _run(6, 10.0, 66.0, "BASE", 148),
    _run(14, 3.58, 21.5, "RECOVERY", 140),
    _run(23, 6.31, 39.1, "AEROBIC_BASE", 145),
    _run(40, 8.2, 52.0, "THRESHOLD", 168),
]

RAW_OTHER = [
    _gym(0, "Push"),
    _gym(2, "Pull day"),
    _gym(3, "Leg day"),
    _gym(9, "Back + biceps"),
    _other(9, "Skopje Padel", "other"),
    _other(18, "Skopje Soccer/Football", "other"),
    _other(30, "Thasos Open Water Swimming", "open_water_swimming"),
]


class FakeGarminApi:
    """Serves raw Garmin-shaped payloads. No network, no credentials."""

    def __init__(self, fail: set[str] | None = None):
        self.fail = fail or set()

    def _maybe_fail(self, name: str):
        if name in self.fail:
            raise RuntimeError(f"simulated {name} failure")

    def get_full_name(self):
        self._maybe_fail("get_full_name")
        return "Test Athlete"

    def get_activities_by_date(self, start, end, activity_type=None):
        self._maybe_fail("get_activities_by_date")
        rows = RAW_RUNS + RAW_OTHER if activity_type is None else RAW_RUNS
        return [r for r in rows if start <= r["startTimeLocal"][:10] <= end]

    def get_training_status(self, day):
        self._maybe_fail("get_training_status")
        n = int(day[-2:])
        return {
            "mostRecentTrainingStatus": {
                "latestTrainingStatusData": {
                    "dev1": {
                        "acuteTrainingLoadDTO": {
                            "dailyTrainingLoadAcute": 300 + n,
                            "dailyTrainingLoadChronic": 380 + n / 2,
                            "acwrStatus": "LOW",
                        }
                    }
                }
            }
        }

    def get_max_metrics_range(self, start, end):
        self._maybe_fail("get_max_metrics_range")
        return [
            {"generic": {"calendarDate": start, "vo2MaxValue": 44.0}},
            {"generic": {"calendarDate": end, "vo2MaxValue": 45.0}},
        ]

    def get_hrv_data_range(self, start, end):
        self._maybe_fail("get_hrv_data_range")
        return {
            "hrvSummaries": [
                {
                    "calendarDate": end,
                    "weeklyAvg": 62,
                    "lastNightAvg": 58,
                    "status": "BALANCED",
                },
                {"calendarDate": start, "weeklyAvg": None, "lastNightAvg": None},
            ]
        }

    def get_rhr_daily(self, start, end):
        self._maybe_fail("get_rhr_daily")
        return [
            {"calendarDate": start, "value": 54},
            {"calendarDate": end, "value": 52},
            {"calendarDate": end, "value": None},
        ]

    def get_sleep_daily(self, start, end):
        self._maybe_fail("get_sleep_daily")
        rows = []
        for offset in (1, 2, 3):
            d = _iso(ANCHOR - timedelta(days=offset))
            rows.append(
                {
                    "calendarDate": d,
                    "values": {
                        "totalSleepTimeInSeconds": 25200 + offset * 600,
                        "sleepScore": 78 + offset,
                        "sleepScoreQuality": "GOOD",
                        "deepTime": 4200,
                        "lightTime": 15000,
                        "remTime": 5400,
                        "awakeTime": 900,
                        "localSleepStartTimeInMillis": 1786500000000,
                        "restingHeartRate": 52,
                        "avgHeartRate": 58,
                        "respiration": 14.2,
                        "spO2": 95,
                        "avgOvernightHrv": 60,
                        "hrv7dAverage": 61,
                        "sleepNeed": 480,
                        "bodyBatteryChange": 41,
                    },
                }
            )
        rows.append({"calendarDate": _iso(ANCHOR), "values": {}})
        return rows

    def get_user_summary(self, day):
        self._maybe_fail("get_user_summary")
        n = int(day[-2:])
        return {
            "totalKilocalories": 2900 + n,
            "activeKilocalories": 700 + n,
            "bmrKilocalories": 2100,
        }

    def get_personal_record(self):
        self._maybe_fail("get_personal_record")
        return [
            {"typeId": 3, "value": 1500},
            {"typeId": 1, "value": 280},
            {"typeId": 7, "value": 10000},
            {"typeId": 99, "value": 1},
        ]

    def get_race_predictions(self):
        self._maybe_fail("get_race_predictions")
        return {
            "time5K": 1490,
            "time10K": 3100,
            "timeHalfMarathon": 6900,
            "timeMarathon": 14500,
        }


DATA_FILES = {
    "trainings": [
        {
            "date": _iso(ANCHOR),
            "type": "gym",
            "subtype": "push",
            "muscle_groups": {"chest": 0.9, "triceps": 0.9, "front_delts": 0.8},
            "notes": "Push day",
        },
        {
            "date": _iso(ANCHOR - timedelta(days=20)),
            "type": "gym",
            "subtype": "legs",
            "duration_min": 70,
            "muscle_groups": {"quads": 1.0, "hamstrings": 0.8},
            "notes": "Standalone leg day (no watch)",
        },
        {
            "date": _iso(ANCHOR - timedelta(days=5)),
            "type": "gym",
            "subtype": "pull",
            "muscle_groups": {"lats": 1.0},
            "notes": "Pending sync annotation",
        },
    ],
    "muscle_presets": {
        "muscle_groups": ["chest", "lats", "quads", "triceps", "biceps"],
        "gym_splits": {
            "push": {"chest": 1.0, "triceps": 0.9, "front_delts": 0.8},
            "pull": {"lats": 1.0, "biceps": 0.9},
            "legs": {"quads": 1.0, "hamstrings": 0.9},
            "full_body": {"chest": 0.6, "quads": 0.6},
            "back": {"lats": 1.0, "upper_back": 0.8},
        },
        "sports": {
            "run": {"quads": 0.75, "hamstrings": 0.7, "calves": 0.3},
            "padel": {"quads": 0.4, "forearms": 0.4},
            "football": {"quads": 0.6, "calves": 0.5},
        },
    },
    "nutrition": [
        {"date": _iso(ANCHOR), "calories": 820, "protein_g": 55},
        {"date": _iso(ANCHOR - timedelta(days=1)), "calories": 2600, "protein_g": 150},
        {"date": _iso(ANCHOR - timedelta(days=2)), "calories": 3100, "protein_g": 180},
        {"date": _iso(ANCHOR - timedelta(days=3)), "calories": 2400, "protein_g": 120},
        {"date": "not-a-date", "calories": 999, "protein_g": 99},
    ],
    "body_comp": [
        {"date": _iso(ANCHOR - timedelta(days=4)), "weight_kg": 93.4, "bmr": 2050},
    ],
    "lifestyle": [{"date": _iso(ANCHOR - timedelta(days=1)), "cigarettes": 2}],
    "workout_plan": {
        "date": _iso(ANCHOR),
        "name": "Push Day",
        "exercises": [{"name": "Incline DB Press", "target_sets": 4, "target_reps": "8-10"}],
    },
}


@pytest.fixture
def anchor() -> date:
    return ANCHOR


@pytest.fixture
def fake_api() -> FakeGarminApi:
    return FakeGarminApi()


@pytest.fixture
def data_files() -> dict:
    return {k: v for k, v in DATA_FILES.items()}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """The day-by-day endpoints pace themselves; tests should not wait for it."""
    monkeypatch.setattr("time.sleep", lambda *_: None)
