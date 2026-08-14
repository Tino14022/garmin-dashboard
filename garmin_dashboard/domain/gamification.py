"""XP, streaks and badges derived from logged sessions."""
from __future__ import annotations

from datetime import date, timedelta

from .formatting import parse_iso, week_start


def _badge(id_: str, icon: str, label: str, earned: bool, desc: str) -> dict:
    return {
        "id": id_,
        "icon": icon,
        "label": label,
        "earned": earned,
        "description": desc,
    }


def compute_gamification(
    sessions: list[dict], today: date, *, week_starts_on: int = 6
) -> dict:
    session_dates = set()
    for s in sessions:
        d = parse_iso(s["date"])
        if d is not None:
            session_dates.add(d)

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

    def xp_for_level(n: int) -> int:
        return 50 * (n - 1) ** 2

    xp_into_level = xp - xp_for_level(level)
    xp_for_next = xp_for_level(level + 1) - xp_for_level(level)
    level_progress = round(xp_into_level / xp_for_next, 3) if xp_for_next else 0

    total_sessions = len(sessions)
    total_run_km = round(
        sum(
            float((s.get("notes") or "0 km").split(" km")[0])
            for s in sessions
            if s["type"] == "run" and "km" in (s.get("notes") or "")
        ),
        1,
    )
    gym_count = sum(1 for s in sessions if s["type"] == "gym")
    early_bird = sum(
        1 for s in sessions if s.get("hour") is not None and s["hour"] < 7
    )
    night_owl = sum(
        1 for s in sessions if s.get("hour") is not None and s["hour"] >= 21
    )
    longest_session = max((s.get("duration_min") or 0 for s in sessions), default=0)

    this_week_muscles: set[str] = set()
    week_cursor = week_start(today, week_starts_on)
    for s in sessions:
        d2 = parse_iso(s["date"])
        if d2 is not None and d2 >= week_cursor:
            this_week_muscles.update((s.get("muscle_groups") or {}).keys())

    badges = [
        _badge("streak3", "🔥", "3-Day Streak", streak_days >= 3, "Train 3 days in a row"),
        _badge("streak7", "🔥🔥", "Week Streak", streak_days >= 7, "Train 7 days in a row"),
        _badge("streak14", "🔥🔥🔥", "Fortnight Streak", streak_days >= 14, "Train 14 days in a row"),
        _badge("streak30", "🌋", "30-Day Streak", max(streak_days, longest_streak_days) >= 30, "Train 30 days in a row"),
        _badge("sessions10", "🏅", "10 Sessions", total_sessions >= 10, "Log 10 total sessions"),
        _badge("sessions50", "🎖️", "50 Sessions", total_sessions >= 50, "Log 50 total sessions"),
        _badge("sessions100", "🏆", "Century", total_sessions >= 100, "Log 100 total sessions"),
        _badge("run25", "🏃", "25K Runner", total_run_km >= 25, "25km total running (tracked window)"),
        _badge("run50", "🏃‍♂️", "50K Runner", total_run_km >= 50, "50km total running (tracked window)"),
        _badge("run100", "🚀", "100K Runner", total_run_km >= 100, "100km total running (tracked window)"),
        _badge("balanced", "⚖️", "Balanced Week", len(this_week_muscles) >= 10, "Train 10+ muscle groups this week"),
        _badge("earlybird", "🌅", "Early Bird", early_bird >= 5, "5 sessions started before 7am"),
        _badge("nightowl", "🦉", "Night Owl", night_owl >= 5, "5 sessions started after 9pm"),
        _badge("ironwill", "💪", "Iron Will", gym_count >= 20, "20 gym sessions logged"),
        _badge("endurance", "🧗", "Endurance", longest_session >= 90, "A single session 90+ minutes"),
        _badge("level5", "⭐", "Level 5", level >= 5, "Reach level 5"),
        _badge("level10", "🌟", "Level 10", level >= 10, "Reach level 10"),
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
