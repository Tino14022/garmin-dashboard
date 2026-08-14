# Data files

Hand-maintained via chat with Claude. Each rebuild reads these plus live Garmin data.

## trainings.json
Non-running sessions (gym/padel/football/hike) — running comes from Garmin automatically.
```json
{
  "date": "2026-08-14",
  "type": "gym",              // gym | padel | football | hike | other
  "subtype": "push",          // free text, e.g. a data/muscle_presets.json gym_splits key
  "duration_min": 60,
  "muscle_groups": {"chest": 1.0, "triceps": 0.9},  // 0-1 intensity, ids from muscle_presets.json
  "notes": "bench 4x8@80kg"
}
```

## nutrition.json
```json
{
  "date": "2026-08-14",
  "meal": "lunch",             // breakfast | lunch | dinner | snack
  "description": "one plate of lasagna",
  "grams": null,               // if the user gave a precise weight instead
  "calories": 650,
  "protein_g": 30,
  "carbs_g": 55,
  "fat_g": 32
}
```
Macros are Claude's estimate from the description, made at logging time.

## body_comp.json
Mi Scale readings.
```json
{
  "date": "2026-08-14",
  "weight_kg": 95.0,
  "body_fat_pct": 22.5,
  "muscle_mass_kg": 68.0,
  "water_pct": 55.0,
  "bone_mass_kg": 3.2,
  "visceral_fat": 12,
  "bmr": 1950
}
```
Only include fields the user actually provided.
