"""Today's workout, resolved from the standing weekly split.

Before this, the Workout tab only showed anything on days a plan had been
chat-logged for that exact date — every gym day needed a fresh conversation
just to populate a checklist that barely changes week to week. The split is
now fixed (see data/training_split.json), so most days resolve on their own;
a chat-logged `workout_plan.json` entry for today still wins when present,
which is how a one-off swap ("actually let's do legs today") keeps working.
"""
from __future__ import annotations

from datetime import date

from .formatting import iso

CHECKLIST_KINDS = {"push", "pull", "legs"}


def resolve_todays_workout(payload: dict, today: date, split: dict) -> dict:
    today_iso = iso(today)

    override = payload.get("workout_plan")
    if override and override.get("date") == today_iso and override.get("exercises"):
        return {
            "date": today_iso,
            "kind": "checklist",
            "source": "override",
            "name": override.get("name") or "Today's Workout",
            "exercises": override["exercises"],
        }

    schedule = split.get("schedule") or {}
    slot = schedule.get(str(today.weekday()))
    templates = split.get("templates") or {}
    template = templates.get(slot) or {}

    if slot in CHECKLIST_KINDS:
        exercises = list(template.get("exercises") or [])
        finisher_slot = "abs_finisher"
        if slot in (split.get("append_finisher_to") or []) and finisher_slot in templates:
            exercises = exercises + list(templates[finisher_slot].get("exercises") or [])
        return {
            "date": today_iso,
            "kind": "checklist",
            "source": "standing_split",
            "name": template.get("name") or slot.title(),
            "exercises": exercises,
        }

    if slot in ("long_run", "light_run"):
        race_plan = payload.get("race_plan") or {}
        target_km = race_plan.get("next_long_run_km") if slot == "long_run" else None
        return {
            "date": today_iso,
            "kind": "run",
            "source": "standing_split",
            "name": "Long Run" if slot == "long_run" else "Light Run",
            "target_km": target_km,
        }

    if slot == "rest":
        return {
            "date": today_iso,
            "kind": "rest",
            "source": "standing_split",
            "name": "Rest Day",
        }

    if template.get("note"):
        return {
            "date": today_iso,
            "kind": "note",
            "source": "standing_split",
            "name": template.get("name") or (slot.replace("_", " ").title() if slot else "Today"),
            "note": template["note"],
        }

    # No schedule entry for this weekday and no chat-logged override — nothing to show.
    return {
        "date": today_iso,
        "kind": "none",
        "source": "standing_split",
        "name": None,
    }
