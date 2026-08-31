"""Activity classification rules.

These are open for extension: adding a sport means adding an entry to a mapping,
never editing a branch in the fetch layer.
"""
from __future__ import annotations

GARMIN_TYPE_MAP = {
    "strength_training": "gym",
    "indoor_cardio": "gym",
    "cycling": "bike",
    "indoor_cycling": "bike",
    "mountain_biking": "bike",
    "gravel_cycling": "bike",
    "hiking": "hike",
    "walking": "walk",
    "swimming": "swim",
    "lap_swimming": "swim",
    "open_water_swimming": "swim",
    "stand_up_paddleboarding": "sup",
    "paddling": "sup",
    "volleyball": "volleyball",
    "beach_volleyball": "volleyball",
}

RUNNING_TYPE_KEYS = {
    "running",
    "trail_running",
    "treadmill_running",
    "track_running",
    "street_running",
}

NAME_TYPE_KEYWORDS = {
    "padel": "padel",
    "football": "football",
    "soccer": "football",
    "hike": "hike",
    "hiking": "hike",
    "tennis": "tennis",
    "basketball": "basketball",
    "cycling": "bike",
    "bike": "bike",
    "cycle": "bike",
    "swim": "swim",
    "swimming": "swim",
    "walk": "walk",
    "walking": "walk",
    "yoga": "yoga",
    "paddleboard": "sup",
    "paddleboarding": "sup",
    "paddle boarding": "sup",
    "sup": "sup",
    "volleyball": "volleyball",
}

EASY_LABELS = {"RECOVERY", "BASE", "AEROBIC_BASE", "MAINTAINING"}

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


def guess_type_from_name(name: str, fallback: str) -> str:
    lower = name.lower()
    for kw, t in NAME_TYPE_KEYWORDS.items():
        if kw in lower:
            return t
    return fallback
