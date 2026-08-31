"""Training sessions, muscle recovery scoring, and mileage aggregation."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from .activities import EASY_LABELS
from .formatting import fmt_pace, iso, parse_iso, week_start
from .gamification import compute_gamification

NAME_KEYWORD_MUSCLES = {
    "push": "push",
    "pull": "pull",
    "leg": "legs",
    "legs": "legs",
    "arm": "arms",
    "arms": "arms",
    "core": "core",
    "abs": "core",
    "upper": "upper",
    "lower": "lower",
    "chest": {"chest": 1.0, "triceps": 0.5, "front_delts": 0.5},
    "back": {"lats": 1.0, "upper_back": 0.8, "traps": 0.5, "lower_back": 0.4},
    "bicep": {"biceps": 1.0},
    "biceps": {"biceps": 1.0},
    "tricep": {"triceps": 1.0},
    "triceps": {"triceps": 1.0},
    "shoulder": {"front_delts": 0.7, "side_delts": 0.8, "rear_delts": 0.5},
    "shoulders": {"front_delts": 0.7, "side_delts": 0.8, "rear_delts": 0.5},
}

RECOVERY_DAYS = 4


def linear_decay(days_since: float) -> float:
    """1.0 (max soreness) the moment a session is logged, fading out by day 4."""
    if days_since < 0:
        return 0.0
    if days_since >= RECOVERY_DAYS:
        return 0.0
    return 1 - days_since / RECOVERY_DAYS


DecayModel = Callable[[float], float]


def guess_muscle_groups_from_name(name: str, gym_splits: dict) -> dict:
    """Best-effort split detection from a name like 'Push + Abs' or 'Back + biceps'."""
    words = name.lower().replace("+", " ").replace("/", " ").split()
    merged: dict[str, float] = {}
    for w in words:
        ref = NAME_KEYWORD_MUSCLES.get(w)
        if ref is None:
            continue
        # A str ref names a split to look up; an unknown split infers nothing.
        # (Defaulting to `ref` itself, as this once did, handed a plain string
        # to .items() and crashed the whole build whenever muscle_presets.json
        # was missing or did not define that split.)
        group = gym_splits.get(ref, {}) if isinstance(ref, str) else ref
        for muscle, intensity in group.items():
            if intensity > merged.get(muscle, 0):
                merged[muscle] = intensity
    return merged


def build_weekly_mileage(
    runs: list[dict], start: date, end: date, *, week_starts_on: int = 6
) -> list[dict]:
    buckets: dict[str, float] = {}
    w = week_start(start, week_starts_on)
    last_w = week_start(end, week_starts_on)
    while w <= last_w:
        buckets[iso(w)] = 0.0
        w += timedelta(days=7)
    for r in runs:
        rd = parse_iso(r["date"])
        if rd is None:
            continue
        wk = iso(week_start(rd, week_starts_on))
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
        "easy": {
            "count": len(easy),
            "avg_pace": fmt_pace(avg_pace(easy)),
            "avg_hr": avg_hr(easy),
        },
        "workout": {
            "count": len(workout),
            "avg_pace": fmt_pace(avg_pace(workout)),
            "avg_hr": avg_hr(workout),
        },
        "runs": [
            {**r, "bucket": "easy" if r["label"] in EASY_LABELS else "workout"}
            for r in runs
        ],
    }


def _merge_same_day_same_type(activities: list[dict]) -> list[dict]:
    """Fold same-day, same-type activities into one entry.

    A single paddleboard outing sometimes syncs as several GPS segments
    (a pause splits it into separate activities) — without this, that shows
    up as three near-identical cards on the same day instead of one with the
    combined duration. Different types on the same day (a run then a swim)
    are untouched; only exact (date, type) repeats get folded together.
    """
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for a in activities:
        key = (a["date"], a["type"])
        if key not in merged:
            merged[key] = dict(a)
            order.append(key)
        else:
            merged[key]["duration_min"] += a["duration_min"]
            earlier = a.get("hour")
            if earlier is not None and (merged[key].get("hour") is None or earlier < merged[key]["hour"]):
                merged[key]["hour"] = earlier
    return [merged[k] for k in order]


def build_training_view(
    runs: list[dict],
    other_activities: list[dict],
    today: date,
    *,
    manual_sessions: list[dict],
    presets: dict,
    week_starts_on: int = 6,
    decay: DecayModel = linear_decay,
) -> dict:
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
        sessions.append(
            {
                "date": s.get("date"),
                "type": s.get("type", "other"),
                "subtype": s.get("subtype"),
                "duration_min": s.get("duration_min"),
                "muscle_groups": s.get("muscle_groups") or {},
                "notes": s.get("notes"),
                "exercises": s.get("exercises"),
                "garmin_synced": True,
            }
        )
    for r in runs:
        hour = None
        if r.get("start_time_local") and len(r["start_time_local"]) >= 13:
            hour = int(r["start_time_local"][11:13])
        sessions.append(
            {
                "date": r["date"],
                "type": "run",
                "subtype": None,
                "duration_min": round(r["duration_s"] / 60),
                "muscle_groups": run_preset,
                "notes": f'{r["distance_km"]} km @ {r["pace_label"]}',
                "hour": hour,
                "garmin_synced": True,
            }
        )
    matched_keys = set()
    for o in _merge_same_day_same_type(other_activities):
        key = (o["date"], o["type"])
        matched_keys.add(key)
        ann = annotations.get(key)
        guessed = (
            guess_muscle_groups_from_name(o["name"], gym_splits)
            if o["type"] == "gym"
            else {}
        )
        muscle_groups = (
            (ann.get("muscle_groups") if ann else None)
            or guessed
            or default_presets_by_type.get(o["type"], {})
        )
        sessions.append(
            {
                "date": o["date"],
                "type": o["type"],
                "subtype": ann.get("subtype") if ann else None,
                "duration_min": o["duration_min"],
                "muscle_groups": muscle_groups,
                "notes": (ann.get("notes") if ann else None) or o["name"],
                "exercises": ann.get("exercises") if ann else None,
                "hour": o.get("hour"),
                "garmin_synced": True,
            }
        )
    # Annotations logged before Garmin's own activity has synced yet — show them now
    # so nothing feels lost, flagged as pending; a later rebuild upgrades them
    # automatically once the matching Garmin activity appears in other_activities.
    for key, ann in annotations.items():
        if key in matched_keys:
            continue
        ann_date, ann_type = key
        sessions.append(
            {
                "date": ann_date,
                "type": ann_type,
                "subtype": ann.get("subtype"),
                "duration_min": None,
                "muscle_groups": ann.get("muscle_groups") or {},
                "notes": ann.get("notes"),
                "exercises": ann.get("exercises"),
                "hour": None,
                "garmin_synced": False,
            }
        )
    sessions.sort(key=lambda s: s["date"] or "", reverse=True)

    scores: dict[str, float] = {}
    muscle_detail: dict[str, dict] = {}
    for s in sessions:
        d = parse_iso(s["date"])
        if d is None:
            continue
        days_since = (today - d).days
        decayed = decay(days_since)
        for muscle, intensity in (s["muscle_groups"] or {}).items():
            existing = muscle_detail.get(muscle)
            if existing is None or days_since < existing["days_since"]:
                muscle_detail[muscle] = {
                    "days_since": days_since,
                    "last_date": s["date"],
                    "last_notes": s.get("notes"),
                    "last_type": s["type"],
                }
            if decayed <= 0:
                continue
            score = round(intensity * decayed, 3)
            if score > scores.get(muscle, 0):
                scores[muscle] = score

    weeks_with_activity = set()
    for s in sessions:
        d = parse_iso(s["date"])
        if d is not None:
            weeks_with_activity.add(iso(week_start(d, week_starts_on)))

    streak = 0
    cursor = week_start(today, week_starts_on)
    while iso(cursor) in weeks_with_activity:
        streak += 1
        cursor -= timedelta(days=7)

    this_week_key = iso(week_start(today, week_starts_on))
    week_count = sum(
        1
        for s in sessions
        if s["date"]
        and iso(week_start(date.fromisoformat(s["date"]), week_starts_on))
        == this_week_key
    )

    return {
        "sessions": sessions[:60],
        "muscle_scores": scores,
        "muscle_detail": muscle_detail,
        "streak_weeks": streak,
        "week_count": week_count,
        "gamification": compute_gamification(
            sessions, today, week_starts_on=week_starts_on
        ),
    }
