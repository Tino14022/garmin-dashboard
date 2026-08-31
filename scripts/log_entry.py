#!/usr/bin/env python3
"""Append or replace one entry in a data/*.json file.

Exists so the morning agents never have to read these files into context to
write to them. They grow forever; the agent's context should not. The agent
sends one JSON object on stdin and this handles read, merge, validate and write.

    echo '{"date":"2026-08-16","weight_kg":98.35}' | python scripts/log_entry.py body_comp
    echo '{"date":"2026-08-16","name":"Pull Day","exercises":[]}' | python scripts/log_entry.py workout_plan
    echo '{"date":"2026-08-19","amount_den":500,"note":"sports betting"}' | python scripts/log_entry.py gambling

Same-date entries replace rather than duplicate, so re-running after a
correction is safe.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Only these files, and only these fields. Anything else is rejected rather
# than written, so a confused agent cannot invent a schema.
ALLOWED = {
    "body_comp": {
        "kind": "list",
        "required": {"date"},
        "fields": {
            "date", "time", "weight_kg", "bmi", "body_fat_pct", "muscle_mass_kg",
            "skeletal_muscle_kg", "water_pct", "protein_pct", "bone_mass_kg",
            "visceral_fat", "subcutaneous_fat_pct", "bmr", "scale_heart_rate",
            "body_score",
        },
    },
    "workout_plan": {
        "kind": "object",
        "required": {"date", "name"},
        "fields": {"date", "name", "exercises"},
    },
    "nutrition": {
        "kind": "list",
        "required": {"date", "description"},
        "fields": {"date", "meal", "description", "grams", "calories",
                   "protein_g", "carbs_g", "fat_g"},
    },
    "trainings": {
        "kind": "list",
        "required": {"date", "type"},
        "fields": {"date", "type", "subtype", "notes", "duration_min",
                   "muscle_groups", "exercises"},
    },
    "lifestyle": {
        "kind": "list",
        "required": {"date"},
        "fields": {"date", "cigarettes_level", "alcohol_drinks", "cannabis_used", "notes", "vacation"},
    },
    "gambling": {
        "kind": "list",
        "required": {"date", "amount_den"},
        "fields": {"date", "amount_den", "note"},
    },
}


def validate(name: str, entry: dict) -> dict:
    spec = ALLOWED[name]
    if not isinstance(entry, dict):
        raise ValueError("entry must be a JSON object")
    unknown = set(entry) - spec["fields"]
    if unknown:
        raise ValueError(f"unknown field(s) for {name}: {', '.join(sorted(unknown))}")
    missing = spec["required"] - set(entry)
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(sorted(missing))}")
    date = entry["date"]
    if not isinstance(date, str) or len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise ValueError("date must be YYYY-MM-DD")
    # Drop nulls rather than storing them; absent means "the scale didn't say".
    return {k: v for k, v in entry.items() if v is not None}


def apply(name: str, entry: dict, path: Path) -> str:
    spec = ALLOWED[name]
    entry = validate(name, entry)

    if spec["kind"] == "object":
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return f"wrote {path.name}: {entry.get('name', entry['date'])}"

    rows = []
    if path.exists():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path.name} is not valid JSON, refusing to overwrite: {e}")
        if not isinstance(rows, list):
            raise ValueError(f"{path.name} is not a JSON array")

    # body_comp holds one reading per day. Merge rather than replace: a
    # correction that resends a single field must not wipe the other fourteen.
    # nutrition and lifestyle can hold several entries per day, so append.
    if name == "body_comp":
        existing = next((r for r in rows if r.get("date") == entry["date"]), None)
        if existing is not None:
            rows = [r for r in rows if r is not existing]
            entry = {**existing, **entry}
            action = "updated"
        else:
            action = "logged"
    else:
        action = "appended"
    rows.append(entry)
    rows.sort(key=lambda r: (r.get("date") or "", r.get("time") or ""))
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return f"{action} {name} for {entry['date']} ({len(rows)} total)"


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ALLOWED:
        print(f"usage: log_entry.py [{'|'.join(ALLOWED)}]  (entry JSON on stdin)", file=sys.stderr)
        return 2
    name = argv[1]
    try:
        entry = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(f"stdin is not valid JSON: {e}", file=sys.stderr)
        return 1
    try:
        print(apply(name, entry, DATA_DIR / f"{name}.json"))
    except ValueError as e:
        print(f"rejected: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
