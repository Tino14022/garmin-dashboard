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


GARMIN_TYPE_MAP = {
    "strength_training": "gym",
    "indoor_cardio": "gym",
    "cycling": "bike", "indoor_cycling": "bike", "mountain_biking": "bike", "gravel_cycling": "bike",
    "hiking": "hike",
    "walking": "walk",
    "swimming": "swim", "lap_swimming": "swim", "open_water_swimming": "swim",
}
RUNNING_TYPE_KEYS = {"running", "trail_running", "treadmill_running", "track_running", "street_running"}

NAME_TYPE_KEYWORDS = {
    "padel": "padel",
    "football": "football", "soccer": "football",
    "hike": "hike", "hiking": "hike",
    "tennis": "tennis",
    "basketball": "basketball",
    "cycling": "bike", "bike": "bike", "cycle": "bike",
    "swim": "swim", "swimming": "swim",
    "walk": "walk", "walking": "walk",
    "yoga": "yoga",
}


def guess_type_from_name(name: str, fallback: str) -> str:
    lower = name.lower()
    for kw, t in NAME_TYPE_KEYWORDS.items():
        if kw in lower:
            return t
    return fallback


def fetch_other_activities(api, start: date, end: date) -> list[dict]:
    """Every non-running activity in range, generically classified (no per-sport API filtering)."""
    raw = safe_call(api.get_activities_by_date, iso(start), iso(end), None, default=[]) or []
    out = []
    for a in raw:
        type_key = (a.get("activityType") or {}).get("typeKey", "") or ""
        if type_key in RUNNING_TYPE_KEYS:
            continue  # covered by fetch_activities already
        dur_s = a.get("duration") or 0
        if dur_s <= 0:
            continue
        name = a.get("activityName") or type_key.replace("_", " ").title() or "Activity"
        start_local = a.get("startTimeLocal") or ""
        out.append({
            "date": start_local[:10],
            "hour": int(start_local[11:13]) if len(start_local) >= 13 else None,
            "type": guess_type_from_name(name, GARMIN_TYPE_MAP.get(type_key, "other")),
            "duration_min": round(dur_s / 60),
            "name": name,
        })
    return out


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
            "quality": v.get("sleepScoreQuality"),
            "deep_min": round((v.get("deepTime") or 0) / 60),
            "light_min": round((v.get("lightTime") or 0) / 60),
            "rem_min": round((v.get("remTime") or 0) / 60),
            "awake_min": round((v.get("awakeTime") or 0) / 60),
            "resting_hr": v.get("restingHeartRate"),
            "avg_hr": v.get("avgHeartRate"),
            "respiration": v.get("respiration"),
            "spo2": v.get("spO2"),
            "avg_overnight_hrv": v.get("avgOvernightHrv"),
            "hrv_7d_avg": v.get("hrv7dAverage"),
            "sleep_need_min": v.get("sleepNeed"),
            "body_battery_change": v.get("bodyBatteryChange"),
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
    """1.0 (max soreness) the moment a session is logged, fading out linearly by day 4."""
    if days_since < 0:
        return 0.0
    if days_since >= 4:
        return 0.0
    return 1 - days_since / 4


NAME_KEYWORD_MUSCLES = {
    "push": "push", "pull": "pull",
    "leg": "legs", "legs": "legs",
    "arm": "arms", "arms": "arms",
    "core": "core", "abs": "core",
    "upper": "upper", "lower": "lower",
    "chest": {"chest": 1.0, "triceps": 0.5, "front_delts": 0.5},
    "back": {"lats": 1.0, "upper_back": 0.8, "traps": 0.5, "lower_back": 0.4},
    "bicep": {"biceps": 1.0}, "biceps": {"biceps": 1.0},
    "tricep": {"triceps": 1.0}, "triceps": {"triceps": 1.0},
    "shoulder": {"front_delts": 0.7, "side_delts": 0.8, "rear_delts": 0.5},
    "shoulders": {"front_delts": 0.7, "side_delts": 0.8, "rear_delts": 0.5},
}


def guess_muscle_groups_from_name(name: str, gym_splits: dict) -> dict:
    """Best-effort split detection from an activity name like 'Push + Abs' or 'Back + biceps'."""
    words = name.lower().replace("+", " ").replace("/", " ").split()
    merged: dict[str, float] = {}
    for w in words:
        ref = NAME_KEYWORD_MUSCLES.get(w)
        if ref is None:
            continue
        group = gym_splits.get(ref, ref) if isinstance(ref, str) else ref
        for muscle, intensity in group.items():
            if intensity > merged.get(muscle, 0):
                merged[muscle] = intensity
    return merged


def build_training_view(runs: list[dict], other_activities: list[dict], today: date) -> dict:
    data_dir = Path(__file__).parent / "data"
    manual_sessions = load_json(data_dir / "trainings.json", [])
    presets = load_json(data_dir / "muscle_presets.json", {})
    run_preset = (presets.get("sports") or {}).get("run", {})
    gym_splits = presets.get("gym_splits") or {}
    default_presets_by_type = dict(presets.get("sports") or {})
    default_presets_by_type["gym"] = gym_splits.get("full_body", {})

    # Manual entries with no duration_min are annotations (subtype/muscle_groups) for a
    # Garmin-sourced activity on the same (date, type) — e.g. "Monday was push day".
    # Manual entries WITH duration_min are standalone records (e.g. no watch that day).
    annotations: dict[tuple, dict] = {}
    standalone = []
    for s in manual_sessions:
        if not s.get("duration_min"):
            annotations[(s.get("date"), s.get("type"))] = s
        else:
            standalone.append(s)

    sessions = []
    for s in standalone:
        sessions.append({
            "date": s.get("date"),
            "type": s.get("type", "other"),
            "subtype": s.get("subtype"),
            "duration_min": s.get("duration_min"),
            "muscle_groups": s.get("muscle_groups") or {},
            "notes": s.get("notes"),
        })
    for r in runs:
        hour = None
        if r.get("start_time_local") and len(r["start_time_local"]) >= 13:
            hour = int(r["start_time_local"][11:13])
        sessions.append({
            "date": r["date"],
            "type": "run",
            "subtype": None,
            "duration_min": round(r["duration_s"] / 60),
            "muscle_groups": run_preset,
            "notes": f'{r["distance_km"]} km @ {r["pace_label"]}',
            "hour": hour,
        })
    for o in other_activities:
        ann = annotations.get((o["date"], o["type"]))
        guessed = guess_muscle_groups_from_name(o["name"], gym_splits) if o["type"] == "gym" else {}
        muscle_groups = (
            (ann.get("muscle_groups") if ann else None)
            or guessed
            or default_presets_by_type.get(o["type"], {})
        )
        sessions.append({
            "date": o["date"],
            "type": o["type"],
            "subtype": ann.get("subtype") if ann else None,
            "duration_min": o["duration_min"],
            "muscle_groups": muscle_groups,
            "notes": (ann.get("notes") if ann else None) or o["name"],
            "hour": o.get("hour"),
        })
    sessions.sort(key=lambda s: s["date"] or "", reverse=True)

    scores: dict[str, float] = {}
    muscle_detail: dict[str, dict] = {}
    for s in sessions:
        try:
            d = date.fromisoformat(s["date"])
        except (ValueError, TypeError):
            continue
        days_since = (today - d).days
        decay = muscle_decay(days_since)
        for muscle, intensity in (s["muscle_groups"] or {}).items():
            existing = muscle_detail.get(muscle)
            if existing is None or days_since < existing["days_since"]:
                muscle_detail[muscle] = {
                    "days_since": days_since,
                    "last_date": s["date"],
                    "last_notes": s.get("notes"),
                    "last_type": s["type"],
                }
            if decay <= 0:
                continue
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

    gamification = compute_gamification(sessions, today)

    return {
        "sessions": sessions[:60],
        "muscle_scores": scores,
        "muscle_detail": muscle_detail,
        "streak_weeks": streak,
        "week_count": week_count,
        "gamification": gamification,
    }


def compute_gamification(sessions: list[dict], today: date) -> dict:
    session_dates = set()
    for s in sessions:
        try:
            session_dates.add(date.fromisoformat(s["date"]))
        except (ValueError, TypeError):
            continue

    # Daily streak: consecutive calendar days with >=1 session, alive if today or
    # yesterday has one (today isn't "missed" until the day is over).
    if today in session_dates:
        cursor = today
    elif (today - timedelta(days=1)) in session_dates:
        cursor = today - timedelta(days=1)
    else:
        cursor = None
    streak_days = 0
    d = cursor
    while d is not None and d in session_dates:
        streak_days += 1
        d -= timedelta(days=1)

    longest_streak_days = 0
    if session_dates:
        ordered = sorted(session_dates)
        run_len = 1
        longest_streak_days = 1
        for i in range(1, len(ordered)):
            if (ordered[i] - ordered[i - 1]).days == 1:
                run_len += 1
                longest_streak_days = max(longest_streak_days, run_len)
            else:
                run_len = 1

    # XP: 1 point per minute trained, total across all logged sessions.
    xp = sum(s.get("duration_min") or 0 for s in sessions)
    level = int((xp / 50) ** 0.5) + 1
    xp_for_level = lambda n: 50 * (n - 1) ** 2
    xp_into_level = xp - xp_for_level(level)
    xp_for_next = xp_for_level(level + 1) - xp_for_level(level)
    level_progress = round(xp_into_level / xp_for_next, 3) if xp_for_next else 0

    total_sessions = len(sessions)
    total_run_km = round(sum(
        float((s.get("notes") or "0 km").split(" km")[0])
        for s in sessions if s["type"] == "run" and "km" in (s.get("notes") or "")
    ), 1)
    gym_count = sum(1 for s in sessions if s["type"] == "gym")
    early_bird = sum(1 for s in sessions if s.get("hour") is not None and s["hour"] < 7)
    night_owl = sum(1 for s in sessions if s.get("hour") is not None and s["hour"] >= 21)
    longest_session = max((s.get("duration_min") or 0 for s in sessions), default=0)

    this_week_muscles: set[str] = set()
    week_cursor = week_start(today)
    for s in sessions:
        try:
            d2 = date.fromisoformat(s["date"])
        except (ValueError, TypeError):
            continue
        if d2 >= week_cursor:
            this_week_muscles.update((s.get("muscle_groups") or {}).keys())

    def badge(id_, icon, label, earned, desc):
        return {"id": id_, "icon": icon, "label": label, "earned": earned, "description": desc}

    badges = [
        badge("streak3", "🔥", "3-Day Streak", streak_days >= 3, "Train 3 days in a row"),
        badge("streak7", "🔥🔥", "Week Streak", streak_days >= 7, "Train 7 days in a row"),
        badge("streak14", "🔥🔥🔥", "Fortnight Streak", streak_days >= 14, "Train 14 days in a row"),
        badge("streak30", "🌋", "30-Day Streak", max(streak_days, longest_streak_days) >= 30, "Train 30 days in a row"),
        badge("sessions10", "🏅", "10 Sessions", total_sessions >= 10, "Log 10 total sessions"),
        badge("sessions50", "🎖️", "50 Sessions", total_sessions >= 50, "Log 50 total sessions"),
        badge("sessions100", "🏆", "Century", total_sessions >= 100, "Log 100 total sessions"),
        badge("run25", "🏃", "25K Runner", total_run_km >= 25, "25km total running (tracked window)"),
        badge("run50", "🏃‍♂️", "50K Runner", total_run_km >= 50, "50km total running (tracked window)"),
        badge("run100", "🚀", "100K Runner", total_run_km >= 100, "100km total running (tracked window)"),
        badge("balanced", "⚖️", "Balanced Week", len(this_week_muscles) >= 10, "Train 10+ muscle groups this week"),
        badge("earlybird", "🌅", "Early Bird", early_bird >= 5, "5 sessions started before 7am"),
        badge("nightowl", "🦉", "Night Owl", night_owl >= 5, "5 sessions started after 9pm"),
        badge("ironwill", "💪", "Iron Will", gym_count >= 20, "20 gym sessions logged"),
        badge("endurance", "🧗", "Endurance", longest_session >= 90, "A single session 90+ minutes"),
        badge("level5", "⭐", "Level 5", level >= 5, "Reach level 5"),
        badge("level10", "🌟", "Level 10", level >= 10, "Reach level 10"),
    ]

    return {
        "xp": xp,
        "level": level,
        "xp_into_level": xp_into_level,
        "xp_for_next_level": xp_for_next,
        "level_progress": level_progress,
        "streak_days": streak_days,
        "longest_streak_days": longest_streak_days,
        "badges": badges,
        "badges_earned": sum(1 for b in badges if b["earned"]),
        "badges_total": len(badges),
    }


# ---------------------------------------------------------------------------
# HTML build
# ---------------------------------------------------------------------------

def extract_running_tab(running_html: str) -> tuple[str, str, str]:
    """Split the standalone running template into (style_content, body_content, script_content)."""
    style_start = running_html.index("<style>") + len("<style>")
    style_end = running_html.index("</style>", style_start)
    style_content = running_html[style_start:style_end]

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
    return style_content, body_content, script_content


def build_html(data: dict) -> str:
    payload = json.dumps(data, default=str)
    running_path = Path(__file__).parent / "template.html"
    app_path = Path(__file__).parent / "app_template.html"

    running_html = running_path.read_text(encoding="utf-8")
    style_content, body_content, script_content = extract_running_tab(running_html)

    app_html = app_path.read_text(encoding="utf-8")
    # Injected before the shell's own <style> block so the shell's rules win
    # the cascade for any class name both files happen to define.
    app_html = app_html.replace("__RUNNING_TAB_STYLE__", style_content)
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

    print("Fetching sleep trend (12 weeks, for the Sleep tab)...")
    sleep_trend = fetch_sleep_trend(api, trend_start, today)

    print("Fetching personal records + race predictions...")
    personal_records = fetch_personal_records(api)
    race_predictions = fetch_race_predictions(api)

    recent_runs = [r for r in runs_12wk if date.fromisoformat(r["date"]) >= recent_runs_start]
    recent_runs.sort(key=lambda r: r["start_time_local"], reverse=True)

    weekly_mileage = build_weekly_mileage(runs_12wk, trend_start, today)
    pace_panel = split_easy_vs_workout(recent_runs)

    print("Fetching non-running activities (gym, etc.)...")
    other_activities = fetch_other_activities(api, trend_start, today)

    print("Loading training/nutrition/body-comp data files...")
    training_view = build_training_view(runs_12wk, other_activities, today)
    nutrition = load_json(Path(__file__).parent / "data" / "nutrition.json", [])
    body_comp = load_json(Path(__file__).parent / "data" / "body_comp.json", [])
    muscle_group_list = load_json(Path(__file__).parent / "data" / "muscle_presets.json", {}).get("muscle_groups", [])

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
        "muscle_group_list": muscle_group_list,
    }

    html = build_html(data)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"\nWrote {OUTPUT_PATH}")
    print(f"Open it directly in a browser, or file://{OUTPUT_PATH}")


if __name__ == "__main__":
    main()
