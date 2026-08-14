"""Adapter translating Garmin Connect's raw payloads into domain shapes.

This is the only module that knows what Garmin's JSON looks like. Everything
downstream consumes the normalised dicts produced here, which is what lets the
rest of the pipeline run against a fake source with no network.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone

from ..domain.activities import (
    GARMIN_TYPE_MAP,
    PR_TIME_TYPES,
    PR_TYPE_LABELS,
    RUNNING_TYPE_KEYS,
    guess_type_from_name,
)
from ..domain.formatting import fmt_duration, fmt_pace, iso
from ..domain.health import FetchLog


def login():
    import garminconnect

    tokenstore = os.environ.get("GARMINTOKENS") or os.path.expanduser("~/.garminconnect")
    api = garminconnect.Garmin()
    api.login(tokenstore)
    return api


class GarminSource:
    """Implements MetricsSource against a live garminconnect client."""

    def __init__(self, api, log: FetchLog, *, pause: float = 0.15):
        self._api = api
        self._log = log
        self._pause = pause

    # -- identity ---------------------------------------------------------
    def athlete_name(self) -> str:
        return self._log.call("athlete_name", self._api.get_full_name, default="Athlete")

    # -- activities -------------------------------------------------------
    def runs(self, start: date, end: date) -> list[dict]:
        raw = (
            self._log.call(
                "runs",
                self._api.get_activities_by_date,
                iso(start),
                iso(end),
                "running",
                default=[],
            )
            or []
        )
        out = []
        for a in raw:
            dist_m = a.get("distance") or 0
            dur_s = a.get("duration") or 0
            if dist_m <= 0 or dur_s <= 0:
                continue
            pace = dur_s / (dist_m / 1000)
            out.append(
                {
                    "id": a.get("activityId"),
                    "name": a.get("activityName") or "Run",
                    "date": (a.get("startTimeLocal") or "")[:10],
                    "start_time_local": a.get("startTimeLocal") or "",
                    "distance_km": round(dist_m / 1000, 2),
                    "duration_s": dur_s,
                    "pace_sec_per_km": pace,
                    "pace_label": fmt_pace(pace),
                    "avg_hr": a.get("averageHR"),
                    "max_hr": a.get("maxHR"),
                    "label": a.get("trainingEffectLabel") or "UNKNOWN",
                    "training_load": a.get("activityTrainingLoad"),
                }
            )
        out.sort(key=lambda r: r["start_time_local"])
        return out

    def other_activities(self, start: date, end: date) -> list[dict]:
        raw = (
            self._log.call(
                "other_activities",
                self._api.get_activities_by_date,
                iso(start),
                iso(end),
                None,
                default=[],
            )
            or []
        )
        out = []
        for a in raw:
            type_key = (a.get("activityType") or {}).get("typeKey", "") or ""
            if type_key in RUNNING_TYPE_KEYS:
                continue  # covered by runs() already
            dur_s = a.get("duration") or 0
            if dur_s <= 0:
                continue
            name = (
                a.get("activityName")
                or type_key.replace("_", " ").title()
                or "Activity"
            )
            start_local = a.get("startTimeLocal") or ""
            out.append(
                {
                    "date": start_local[:10],
                    "hour": int(start_local[11:13]) if len(start_local) >= 13 else None,
                    "type": guess_type_from_name(
                        name, GARMIN_TYPE_MAP.get(type_key, "other")
                    ),
                    "duration_min": round(dur_s / 60),
                    "name": name,
                }
            )
        return out

    # -- load / fitness ---------------------------------------------------
    def load_trend(self, start: date, end: date) -> list[dict]:
        trend = []
        failures = 0
        days = 0
        d = start
        while d <= end:
            days += 1
            try:
                ts = self._api.get_training_status(iso(d))
            except Exception:  # noqa: BLE001
                failures += 1
                ts = None
            if ts:
                latest = (ts.get("mostRecentTrainingStatus") or {}).get(
                    "latestTrainingStatusData"
                ) or {}
                for dev in latest.values():
                    acute = dev.get("acuteTrainingLoadDTO") or {}
                    atl = acute.get("dailyTrainingLoadAcute")
                    ctl = acute.get("dailyTrainingLoadChronic")
                    if atl is not None and ctl is not None:
                        trend.append(
                            {
                                "date": iso(d),
                                "atl": round(atl, 1),
                                "ctl": round(ctl, 1),
                                "tsb": round(ctl - atl, 1),
                                "acwr_status": acute.get("acwrStatus"),
                            }
                        )
                    break  # primary device only
            time.sleep(self._pause)
            d += timedelta(days=1)
        self._record_loop("load_trend", days, failures)
        return trend

    def vo2max_trend(self, start: date, end: date) -> list[dict]:
        raw = (
            self._log.call(
                "vo2max_trend",
                self._api.get_max_metrics_range,
                iso(start),
                iso(end),
                default=[],
            )
            or []
        )
        out = []
        for entry in raw:
            g = entry.get("generic") or {}
            v = g.get("vo2MaxValue")
            if v:
                out.append({"date": g.get("calendarDate"), "vo2max": v})
        out.sort(key=lambda x: x["date"])
        return out

    # -- recovery ---------------------------------------------------------
    def hrv_trend(self, start: date, end: date) -> list[dict]:
        raw = self._log.call(
            "hrv_trend", self._api.get_hrv_data_range, iso(start), iso(end), default=None
        )
        out = []
        for entry in (raw or {}).get("hrvSummaries") or []:
            if entry.get("weeklyAvg") is None and entry.get("lastNightAvg") is None:
                continue
            out.append(
                {
                    "date": entry.get("calendarDate"),
                    "weekly_avg": entry.get("weeklyAvg"),
                    "last_night_avg": entry.get("lastNightAvg"),
                    "status": entry.get("status"),
                }
            )
        return out

    def rhr_trend(self, start: date, end: date) -> list[dict]:
        raw = (
            self._log.call(
                "rhr_trend", self._api.get_rhr_daily, iso(start), iso(end), default=[]
            )
            or []
        )
        return [
            {"date": e.get("calendarDate"), "rhr": e.get("value")}
            for e in raw
            if e.get("value")
        ]

    def sleep_trend(self, start: date, end: date) -> list[dict]:
        raw = (
            self._log.call(
                "sleep_trend", self._api.get_sleep_daily, iso(start), iso(end), default=[]
            )
            or []
        )
        out = []
        for e in raw:
            v = e.get("values") or {}
            total_s = v.get("totalSleepTimeInSeconds")
            if not total_s:
                continue
            awake_min = round((v.get("awakeTime") or 0) / 60)
            sleep_min = round(total_s / 60)
            bedtime_ms = v.get("localSleepStartTimeInMillis")
            bedtime_hour = None
            if bedtime_ms:
                # Garmin's "local" sleep timestamps are UTC-encoded local wall-clock time.
                t = datetime.fromtimestamp(bedtime_ms / 1000, tz=timezone.utc)
                bedtime_hour = t.hour + t.minute / 60
                if bedtime_hour < 12:
                    # After-midnight bedtime — keep evening bedtimes contiguous
                    # (e.g. 24.5 = 12:30am) so the chart doesn't wrap.
                    bedtime_hour += 24
            out.append(
                {
                    "date": e.get("calendarDate"),
                    "hours": round(total_s / 3600, 2),
                    "score": v.get("sleepScore"),
                    "quality": v.get("sleepScoreQuality"),
                    "deep_min": round((v.get("deepTime") or 0) / 60),
                    "light_min": round((v.get("lightTime") or 0) / 60),
                    "rem_min": round((v.get("remTime") or 0) / 60),
                    "awake_min": awake_min,
                    "efficiency": round(sleep_min / (sleep_min + awake_min) * 100, 1)
                    if (sleep_min + awake_min)
                    else None,
                    "bedtime_hour": round(bedtime_hour, 2)
                    if bedtime_hour is not None
                    else None,
                    "resting_hr": v.get("restingHeartRate"),
                    "avg_hr": v.get("avgHeartRate"),
                    "respiration": v.get("respiration"),
                    "spo2": v.get("spO2"),
                    "avg_overnight_hrv": v.get("avgOvernightHrv"),
                    "hrv_7d_avg": v.get("hrv7dAverage"),
                    "sleep_need_min": v.get("sleepNeed"),
                    "body_battery_change": v.get("bodyBatteryChange"),
                }
            )
        out.sort(key=lambda x: x["date"])
        return out

    # -- energy -----------------------------------------------------------
    def calorie_trend(self, start: date, end: date) -> list[dict]:
        """Garmin's device-measured daily expenditure, not a BMR formula."""
        out = []
        failures = 0
        days = 0
        d = start
        while d <= end:
            days += 1
            try:
                s = self._api.get_user_summary(iso(d))
            except Exception:  # noqa: BLE001
                failures += 1
                s = None
            if s and s.get("totalKilocalories"):
                out.append(
                    {
                        "date": iso(d),
                        "total_kcal": s.get("totalKilocalories"),
                        "active_kcal": s.get("activeKilocalories"),
                        "bmr_kcal": s.get("bmrKilocalories"),
                    }
                )
            time.sleep(self._pause)
            d += timedelta(days=1)
        self._record_loop("calorie_trend", days, failures)
        return out

    # -- achievements -----------------------------------------------------
    def personal_records(self) -> list[dict]:
        raw = self._log.call(
            "personal_records", self._api.get_personal_record, default=[]
        ) or []
        out = []
        for r in raw:
            type_id = r.get("typeId")
            label = PR_TYPE_LABELS.get(type_id)
            if not label:
                continue
            value = r.get("value")
            if type_id in PR_TIME_TYPES:
                display = fmt_duration(value)
            elif type_id == 7:
                display = f"{round((value or 0) / 1000, 2)} km"
            else:
                display = str(value)
            out.append({"label": label, "value": display, "type_id": type_id})
        out.sort(key=lambda x: x["type_id"])
        return out

    def race_predictions(self) -> dict:
        raw = (
            self._log.call(
                "race_predictions", self._api.get_race_predictions, default={}
            )
            or {}
        )
        return {
            "5K": fmt_duration(raw.get("time5K")),
            "10K": fmt_duration(raw.get("time10K")),
            "Half Marathon": fmt_duration(raw.get("timeHalfMarathon")),
            "Marathon": fmt_duration(raw.get("timeMarathon")),
        }

    # -- internals --------------------------------------------------------
    def _record_loop(self, name: str, days: int, failures: int) -> None:
        """Day-by-day endpoints record one outcome for the metric, not per day."""
        if failures and failures >= days:
            self._log.record(
                name, ok=False, error=f"all {days} daily requests failed"
            )
        elif failures:
            self._log.record(
                name, ok=False, error=f"{failures} of {days} daily requests failed"
            )
        else:
            self._log.record(name, ok=True)
