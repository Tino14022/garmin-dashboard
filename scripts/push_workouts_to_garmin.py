#!/usr/bin/env python3
"""Push the race-plan workouts in data/race_plan_workouts.json to Garmin Connect.

Builds one structured running workout per planned session and schedules it onto
its date in the Garmin calendar, so the watch prompts you through each step.

The plan lives in data/race_plan_workouts.json, not in this file — when the plan
changes, edit that and re-run with --replace. That is the whole point of doing
this as a script rather than by hand in the Connect UI: a plan change becomes a
re-run rather than an evening of clicking.

    python scripts/push_workouts_to_garmin.py                    # dry run, prints what it would do
    python scripts/push_workouts_to_garmin.py --push             # create and schedule
    python scripts/push_workouts_to_garmin.py --push --replace   # wipe previous HM26 workouts first

Credentials come from GARMIN_EMAIL / GARMIN_PASSWORD if set, otherwise you are
prompted. Nothing is written to disk by this script; garth caches the login
token under ~/.garminconnect so later runs skip the password.

Workout payloads are built as plain dicts rather than through
garminconnect.workout's typed models, because those models need pydantic, which
garminconnect does not install. Raw dicts keep this working on a bare install.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path
from typing import Any

# garminconnect is imported inside connect(), not here: everything that builds
# the workout payload is pure dict manipulation and stays importable (and
# testable) on a machine that has never installed the client library.

PLAN_PATH = Path(__file__).resolve().parent.parent / "data" / "race_plan_workouts.json"
TOKENSTORE = os.path.expanduser("~/.garminconnect")

RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}

# (stepTypeId, stepTypeKey, displayOrder) as Garmin numbers them.
STEP_TYPES = {
    "warmup": (1, "warmup", 1),
    "cooldown": (2, "cooldown", 2),
    "run": (3, "interval", 3),
    "recover": (4, "recovery", 4),
}
DISTANCE_CONDITION = {
    "conditionTypeId": 3,
    "conditionTypeKey": "distance",
    "displayOrder": 3,
    "displayable": True,
}
TIME_CONDITION = {
    "conditionTypeId": 2,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}
ITERATIONS_CONDITION = {
    "conditionTypeId": 7,
    "conditionTypeKey": "iterations",
    "displayOrder": 7,
    "displayable": False,
}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
PACE_TARGET = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}


def speed_bounds(pace_range: list[int]) -> tuple[float, float]:
    """[fast, slow] seconds per km -> (slower m/s, faster m/s).

    Garmin stores a pace target as a *speed* range in metres per second, so the
    faster pace is the larger number. Getting this backwards silently produces
    a target the watch treats as inverted.
    """
    fast_sec, slow_sec = pace_range
    return 1000.0 / slow_sec, 1000.0 / fast_sec


def build_step(spec: dict, order: int, paces: dict) -> dict[str, Any]:
    type_id, type_key, display_order = STEP_TYPES[spec["kind"]]
    pace_range = paces.get(spec["pace"]) if spec.get("pace") else None

    step: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {
            "stepTypeId": type_id,
            "stepTypeKey": type_key,
            "displayOrder": display_order,
        },
        "targetType": PACE_TARGET if pace_range else NO_TARGET,
    }

    if "distance_m" in spec:
        step["endCondition"] = DISTANCE_CONDITION
        step["endConditionValue"] = float(spec["distance_m"])
    else:
        step["endCondition"] = TIME_CONDITION
        step["endConditionValue"] = float(spec["seconds"])

    if pace_range:
        slower, faster = speed_bounds(pace_range)
        step["targetValueOne"] = round(slower, 4)
        step["targetValueTwo"] = round(faster, 4)

    return step


def build_steps(specs: list[dict], paces: dict, start_order: int = 1) -> list[dict[str, Any]]:
    """Flatten a session's step specs into Garmin steps, expanding repeats."""
    steps: list[dict[str, Any]] = []
    order = start_order
    for spec in specs:
        if spec["kind"] == "repeat":
            children = []
            child_order = order + 1
            for child in spec["steps"]:
                children.append(build_step(child, child_order, paces))
                child_order += 1
            steps.append(
                {
                    "type": "RepeatGroupDTO",
                    "stepOrder": order,
                    "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                    "numberOfIterations": spec["times"],
                    "workoutSteps": children,
                    "endCondition": ITERATIONS_CONDITION,
                    "endConditionValue": float(spec["times"]),
                    "smartRepeat": False,
                }
            )
            order = child_order
        else:
            steps.append(build_step(spec, order, paces))
            order += 1
    return steps


def estimate_seconds(specs: list[dict], paces: dict) -> int:
    """Rough duration so Garmin shows something sane before you start."""
    total = 0.0
    for spec in specs:
        if spec["kind"] == "repeat":
            total += spec["times"] * estimate_seconds(spec["steps"], paces)
        elif "distance_m" in spec:
            pace = paces.get(spec.get("pace")) or [360, 360]
            total += spec["distance_m"] / 1000.0 * ((pace[0] + pace[1]) / 2)
        else:
            total += spec["seconds"]
    return int(total)


def build_workout(session: dict, paces: dict, prefix: str) -> dict[str, Any]:
    name = f"{prefix} {session['date'][5:]} {session['name']}"
    return {
        "workoutName": name[:80],
        "sportType": RUNNING,
        "estimatedDurationInSecs": estimate_seconds(session["steps"], paces),
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": RUNNING,
                "workoutSteps": build_steps(session["steps"], paces),
            }
        ],
    }


def fmt_pace(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def describe(session: dict, paces: dict) -> str:
    def one(spec: dict, indent: str = "    ") -> str:
        if spec["kind"] == "repeat":
            inner = "".join("\n" + one(s, indent + "  ") for s in spec["steps"])
            return f"{indent}{spec['times']}x:{inner}"
        pace = paces.get(spec.get("pace"))
        pace_txt = f" @ {fmt_pace(pace[0])}-{fmt_pace(pace[1])}/km" if pace else ""
        amount = f"{spec['distance_m'] / 1000:g}km" if "distance_m" in spec else f"{spec['seconds']}s"
        return f"{indent}{spec['kind']:8s} {amount}{pace_txt}"

    return "\n".join([f"  {session['date']}  {session['name']}"] + [one(s) for s in session["steps"]])


def connect():
    from garminconnect import Garmin

    email = os.environ.get("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.environ.get("GARMIN_PASSWORD") or getpass("Garmin password: ")
    client = Garmin(email, password, prompt_mfa=lambda: input("MFA code: ").strip())
    client.login(TOKENSTORE)
    return client


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Push race-plan workouts to Garmin Connect.")
    ap.add_argument("--push", action="store_true", help="actually create and schedule (default is a dry run)")
    ap.add_argument("--replace", action="store_true", help="delete existing workouts with this plan's prefix first")
    args = ap.parse_args(argv[1:])

    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    paces, prefix, sessions = plan["paces"], plan["name_prefix"], plan["sessions"]

    print(f"{len(sessions)} sessions in {PLAN_PATH.name}\n")
    for session in sessions:
        print(describe(session, paces))
    print()

    if not args.push:
        print("Dry run — nothing sent. Re-run with --push to create these in Garmin Connect.")
        return 0

    client = connect()
    print("Logged in.\n")

    if args.replace:
        existing = [
            w for w in client.get_workouts(limit=200)
            if (w.get("workoutName") or "").startswith(prefix)
        ]
        for workout in existing:
            client.delete_workout(workout["workoutId"])
        print(f"Removed {len(existing)} previous '{prefix}' workout(s).\n")

    for session in sessions:
        payload = build_workout(session, paces, prefix)
        created = client.upload_workout(payload)
        workout_id = created.get("workoutId")
        if workout_id is None:
            print(f"  !! {session['date']} upload returned no workoutId: {created}")
            continue
        client.schedule_workout(workout_id, session["date"])
        print(f"  {session['date']}  {payload['workoutName']}")

    print(f"\nDone — {len(sessions)} workouts created and scheduled.")
    print("Sync your watch (Garmin Connect app -> device sync) to pull them down.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
