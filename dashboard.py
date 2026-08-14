# /// script
# requires-python = ">=3.11"
# dependencies = ["garminconnect>=0.2.29"]
# ///
"""Standalone Garmin half-marathon training dashboard.

Run with:  uv run dashboard.py

Pulls live data from Garmin Connect using cached OAuth tokens (never
prompts for a password) and rewrites index.html next to this script.
Reads tokens from, in order: the GARMINTOKENS env var (a path or the
raw token JSON - used in CI), then ~/.garminconnect (local machine,
written by garmin-mcp-auth or garminconnect's own login flow).
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import garminconnect

# ---------------------------------------------------------------------------
# Race / athlete context - edit these for your own race
# ---------------------------------------------------------------------------
RACE_NAME = "Wizz Air Half Marathon"
RACE_DATE = date(2026, 10, 4)
RACE_DISTANCE_KM = 21.1
HEIGHT_CM = 192
WEIGHT_KG = 95

TREND_WEEKS = 12
RECOVERY_WEEKS = 4
RECENT_RUNS_WEEKS = 4

OUTPUT_PATH = Path(__file__).parent / "index.html"

PR_TYPE_LABELS = {
    1: "1K",
    2: "Mile",
    3: "5K",
    4: "10K",
    5: "15K",
    6: "Half Marathon",
    7: "Longest Run",
}
PR_TIME_TYPES = {1, 2, 3, 4, 5, 6}
EASY_LABELS = {"RECOVERY", "BASE", "AEROBIC_BASE", "MAINTAINING"}


def login() -> garminconnect.Garmin:
    tokenstore = os.environ.get("GARMINTOKENS") or os.path.expanduser("~/.garminconnect")
    api = garminconnect.Garmin()
    api.login(tokenstore)
    return api


def iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


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


def safe_call(fn, *args, default=None, retries=3, delay=0.5):
    label = getattr(fn, "__name__", str(fn))
    for attempt in range(retries):
        try:
            return fn(*args)
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ! {label}{args} failed after {retries} tries: {e}")
                return default
            time.sleep(delay * (attempt + 1))
    return default


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def fetch_activities(api, start: date, end: date) -> list[dict]:
    raw = safe_call(api.get_activities_by_date, iso(start), iso(end), "running", default=[]) or []
    runs = []
    for a in raw:
        dist_m = a.get("distance") or 0
        dur_s = a.get("duration") or 0
        if dist_m <= 0 or dur_s <= 0:
            continue
        pace = dur_s / (dist_m / 1000)
        runs.append({
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
        })
    runs.sort(key=lambda r: r["start_time_local"])
    return runs


def fetch_load_trend(api, start: date, end: date) -> list[dict]:
    trend = []
    d = start
    while d <= end:
        ts = safe_call(api.get_training_status, iso(d), retries=2, delay=0.6)
        if ts:
            latest = (ts.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
            for dev in latest.values():
                acute = dev.get("acuteTrainingLoadDTO") or {}
                atl = acute.get("dailyTrainingLoadAcute")
                ctl = acute.get("dailyTrainingLoadChronic")
                if atl is not None and ctl is not None:
                    trend.append({
                        "date": iso(d),
                        "atl": round(atl, 1),
                        "ctl": round(ctl, 1),
                        "tsb": round(ctl - atl, 1),
                        "acwr_status": acute.get("acwrStatus"),
                    })
                break  # primary device only
        time.sleep(0.15)
        d += timedelta(days=1)
    return trend


def fetch_vo2max_trend(api, start: date, end: date) -> list[dict]:
    raw = safe_call(api.get_max_metrics_range, iso(start), iso(end), default=[]) or []
    out = []
    for entry in raw:
        g = entry.get("generic") or {}
        v = g.get("vo2MaxValue")
        if v:
            out.append({"date": g.get("calendarDate"), "vo2max": v})
    out.sort(key=lambda x: x["date"])
    return out


def fetch_hrv_trend(api, start: date, end: date) -> list[dict]:
    raw = safe_call(api.get_hrv_data_range, iso(start), iso(end), default=None)
    out = []
    for entry in (raw or {}).get("hrvSummaries") or []:
        if entry.get("weeklyAvg") is None and entry.get("lastNightAvg") is None:
            continue
        out.append({
            "date": entry.get("calendarDate"),
            "weekly_avg": entry.get("weeklyAvg"),
            "last_night_avg": entry.get("lastNightAvg"),
            "status": entry.get("status"),
        })
    return out


def fetch_rhr_trend(api, start: date, end: date) -> list[dict]:
    raw = safe_call(api.get_rhr_daily, iso(start), iso(end), default=[]) or []
    return [{"date": e.get("calendarDate"), "rhr": e.get("value")} for e in raw if e.get("value")]


def fetch_sleep_trend(api, start: date, end: date) -> list[dict]:
    raw = safe_call(api.get_sleep_daily, iso(start), iso(end), default=[]) or []
    out = []
    for e in raw:
        v = e.get("values") or {}
        total_s = v.get("totalSleepTimeInSeconds")
        if not total_s:
            continue
        out.append({
            "date": e.get("calendarDate"),
            "hours": round(total_s / 3600, 2),
            "score": v.get("sleepScore"),
            "avg_overnight_hrv": v.get("avgOvernightHrv"),
        })
    out.sort(key=lambda x: x["date"])
    return out


def fetch_personal_records(api) -> list[dict]:
    raw = safe_call(api.get_personal_record, default=[]) or []
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


def fetch_race_predictions(api) -> dict:
    raw = safe_call(api.get_race_predictions, default={}) or {}
    return {
        "5K": fmt_duration(raw.get("time5K")),
        "10K": fmt_duration(raw.get("time10K")),
        "Half Marathon": fmt_duration(raw.get("timeHalfMarathon")),
        "Marathon": fmt_duration(raw.get("timeMarathon")),
    }


# ---------------------------------------------------------------------------
# Derived views
# ---------------------------------------------------------------------------

def week_start(d: date) -> date:
    # Account's first day of week is Sunday
    offset = (d.weekday() + 1) % 7  # Mon=0..Sun=6 -> days since most recent Sunday
    return d - timedelta(days=offset)


def build_weekly_mileage(runs: list[dict], start: date, end: date) -> list[dict]:
    buckets: dict[str, float] = {}
    w = week_start(start)
    last_w = week_start(end)
    while w <= last_w:
        buckets[iso(w)] = 0.0
        w += timedelta(days=7)
    for r in runs:
        try:
            rd = date.fromisoformat(r["date"])
        except ValueError:
            continue
        wk = iso(week_start(rd))
        if wk in buckets:
            buckets[wk] += r["distance_km"]
    return [{"week_start": k, "km": round(v, 1)} for k, v in sorted(buckets.items())]


def split_easy_vs_workout(runs: list[dict]) -> dict:
    easy = [r for r in runs if r["label"] in EASY_LABELS]
    workout = [r for r in runs if r["label"] not in EASY_LABELS]

    def avg_pace(rs):
        paces = [r["pace_sec_per_km"] for r in rs if r["pace_sec_per_km"]]
        return sum(paces) / len(paces) if paces else None

    def avg_hr(rs):
        hrs = [r["avg_hr"] for r in rs if r["avg_hr"]]
        return round(sum(hrs) / len(hrs)) if hrs else None

    return {
        "easy": {"count": len(easy), "avg_pace": fmt_pace(avg_pace(easy)), "avg_hr": avg_hr(easy)},
        "workout": {"count": len(workout), "avg_pace": fmt_pace(avg_pace(workout)), "avg_hr": avg_hr(workout)},
        "runs": [
            {**r, "bucket": "easy" if r["label"] in EASY_LABELS else "workout"}
            for r in runs
        ],
    }


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def muscle_decay(days_since: float) -> float:
    """0 on the day before training, peaks the day after, fades out by day 4."""
    if days_since < 0:
        return 0.0
    if days_since <= 1:
        return days_since
    if days_since <= 4:
        return max(0.0, 1 - (days_since - 1) / 3)
    return 0.0


def build_training_view(runs: list[dict], today: date) -> dict:
    data_dir = Path(__file__).parent / "data"
    manual_sessions = load_json(data_dir / "trainings.json", [])
    presets = load_json(data_dir / "muscle_presets.json", {})
    run_preset = (presets.get("sports") or {}).get("run", {})

    sessions = []
    for s in manual_sessions:
        sessions.append({
            "date": s.get("date"),
            "type": s.get("type", "other"),
            "subtype": s.get("subtype"),
            "duration_min": s.get("duration_min"),
            "muscle_groups": s.get("muscle_groups") or {},
            "notes": s.get("notes"),
        })
    for r in runs:
        sessions.append({
            "date": r["date"],
            "type": "run",
            "subtype": None,
            "duration_min": round(r["duration_s"] / 60),
            "muscle_groups": run_preset,
            "notes": f'{r["distance_km"]} km @ {r["pace_label"]}',
        })
    sessions.sort(key=lambda s: s["date"] or "", reverse=True)

    scores: dict[str, float] = {}
    for s in sessions:
        try:
            d = date.fromisoformat(s["date"])
        except (ValueError, TypeError):
            continue
        decay = muscle_decay((today - d).days)
        if decay <= 0:
            continue
        for muscle, intensity in (s["muscle_groups"] or {}).items():
            score = round(intensity * decay, 3)
            if score > scores.get(muscle, 0):
                scores[muscle] = score

    def week_key(d: date) -> str:
        return iso(week_start(d))

    weeks_with_activity = set()
    for s in sessions:
        try:
            d = date.fromisoformat(s["date"])
        except (ValueError, TypeError):
            continue
        weeks_with_activity.add(week_key(d))

    streak = 0
    cursor = week_start(today)
    while iso(cursor) in weeks_with_activity:
        streak += 1
        cursor -= timedelta(days=7)

    this_week_key = week_key(today)
    week_count = sum(
        1 for s in sessions
        if s["date"] and week_key(date.fromisoformat(s["date"])) == this_week_key
    )

    return {
        "sessions": sessions[:60],
        "muscle_scores": scores,
        "streak_weeks": streak,
        "week_count": week_count,
    }


# ---------------------------------------------------------------------------
# HTML build
# ---------------------------------------------------------------------------

def extract_running_tab(running_html: str) -> tuple[str, str]:
    """Split the standalone running template into (body_content, script_content)."""
    body_start = running_html.index("<body>") + len("<body>")
    body_end = running_html.index("<script>")
    script_start = body_end + len("<script>")
    script_end = running_html.index("</script>", script_start)

    body_content = running_html[body_start:body_end]
    script_content = running_html[script_start:script_end]

    # DATA is declared once by the app shell; strip the running template's own
    # declaration and its footer line (the shell owns the shared footer).
    script_content = script_content.replace("const DATA = __DASHBOARD_DATA__;", "")
    script_content = "\n".join(
        line for line in script_content.splitlines()
        if "el('footer')" not in line
    )
    body_content = body_content.replace('<footer id="footer"></footer>', "")
    return body_content, script_content


def build_html(data: dict) -> str:
    payload = json.dumps(data, default=str)
    running_path = Path(__file__).parent / "template.html"
    app_path = Path(__file__).parent / "app_template.html"

    running_html = running_path.read_text(encoding="utf-8")
    body_content, script_content = extract_running_tab(running_html)

    app_html = app_path.read_text(encoding="utf-8")
    app_html = app_html.replace("__RUNNING_TAB_CONTENT__", body_content)
    app_html = app_html.replace("__RUNNING_TAB_SCRIPT__", script_content)
    app_html = app_html.replace("__DASHBOARD_DATA__", payload)
    return app_html


def main() -> None:
    print("Logging in to Garmin Connect (cached tokens)...")
    api = login()
    print(f"Logged in as {api.get_full_name()}")

    today = date.today()
    trend_start = today - timedelta(weeks=TREND_WEEKS)
    recovery_start = today - timedelta(weeks=RECOVERY_WEEKS)
    recent_runs_start = today - timedelta(weeks=RECENT_RUNS_WEEKS)

    print(f"Fetching activities since {trend_start}...")
    runs_12wk = fetch_activities(api, trend_start, today)

    print("Fetching training load trend (this loops one call per day, be patient)...")
    load_trend = fetch_load_trend(api, trend_start, today)

    print("Fetching VO2 max trend...")
    vo2max_trend = fetch_vo2max_trend(api, trend_start, today)

    print("Fetching HRV trend...")
    hrv_trend = fetch_hrv_trend(api, recovery_start, today)

    print("Fetching resting HR trend...")
    rhr_trend = fetch_rhr_trend(api, recovery_start, today)

    print("Fetching sleep trend...")
    sleep_trend = fetch_sleep_trend(api, recovery_start, today)

    print("Fetching personal records + race predictions...")
    personal_records = fetch_personal_records(api)
    race_predictions = fetch_race_predictions(api)

    recent_runs = [r for r in runs_12wk if date.fromisoformat(r["date"]) >= recent_runs_start]
    recent_runs.sort(key=lambda r: r["start_time_local"], reverse=True)

    weekly_mileage = build_weekly_mileage(runs_12wk, trend_start, today)
    pace_panel = split_easy_vs_workout(recent_runs)

    print("Loading training/nutrition/body-comp data files...")
    training_view = build_training_view(runs_12wk, today)
    nutrition = load_json(Path(__file__).parent / "data" / "nutrition.json", [])
    body_comp = load_json(Path(__file__).parent / "data" / "body_comp.json", [])

    days_remaining = (RACE_DATE - today).days
    weeks_remaining = round(days_remaining / 7, 1)

    data = {
        "generated_at": today.isoformat(),
        "generated_at_time": time.strftime("%Y-%m-%d %H:%M %Z"),
        "athlete_name": api.get_full_name(),
        "race": {
            "name": RACE_NAME,
            "date": RACE_DATE.isoformat(),
            "distance_km": RACE_DISTANCE_KM,
            "days_remaining": days_remaining,
            "weeks_remaining": weeks_remaining,
        },
        "athlete": {
            "height_cm": HEIGHT_CM,
            "weight_kg": WEIGHT_KG,
        },
        "personal_records": personal_records,
        "race_predictions": race_predictions,
        "load_trend": load_trend,
        "vo2max_trend": vo2max_trend,
        "hrv_trend": hrv_trend,
        "rhr_trend": rhr_trend,
        "sleep_trend": sleep_trend,
        "weekly_mileage": weekly_mileage,
        "recent_runs": recent_runs,
        "pace_panel": pace_panel,
        "training": training_view,
        "nutrition": nutrition,
        "body_comp": body_comp,
    }

    html = build_html(data)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"\nWrote {OUTPUT_PATH}")
    print(f"Open it directly in a browser, or file://{OUTPUT_PATH}")


if __name__ == "__main__":
    main()
