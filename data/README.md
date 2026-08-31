# Data files

Hand-maintained via chat with Claude. Each rebuild reads these plus live Garmin data.

## trainings.json
Non-running sessions (gym/padel/football/hike) — running comes from Garmin automatically.
```json
{
  "date": "2026-08-14",
  "type": "gym",              // gym | padel | football | hike | other
  "subtype": "push",          // free text, e.g. a data/muscle_presets.json gym_splits key
  "duration_min": 60,         // omit entirely (not null) to make this an annotation - see below
  "muscle_groups": {"chest": 1.0, "triceps": 0.9},  // 0-1 intensity, ids from muscle_presets.json
  "notes": "bench 4x8@80kg",
  "exercises": [{"name": "Incline DB Press", "target_sets": 4, "target_reps": "8-10", "sets_completed": 4}]  // optional, from a finished workout-plan checklist
}
```
**Annotation vs standalone:** an entry with no `duration_min` key is an annotation — it supplies subtype/muscle_groups/exercises for whatever Garmin activity syncs on that (date, type), and shows as "pending Garmin sync" in the app until that match happens. An entry WITH `duration_min` is a standalone record, shown as-is regardless of Garmin. Default to annotations (omit duration_min) whenever the workout was done wearing the watch — which is the normal case.

## workout_plan.json
The coach-assigned plan for today, rendered as an interactive checklist in the Training tab. Single object, not an array — gets replaced each time a new plan is set.
```json
{
  "date": "2026-08-14",
  "name": "Push Day",
  "exercises": [
    {"name": "Incline DB Press", "target_sets": 4, "target_reps": "8-10"},
    {"name": "Shoulder Press", "target_sets": 3, "target_reps": "8-10"}
  ]
}
```
Only shown in the app when `date` matches the build date. Checklist progress lives in the browser's localStorage, not here — when the user finishes and pastes the summary back, log the result into `trainings.json` as an annotation (see above), using the `exercises` field to capture what was actually completed. If today's date isn't in here, the Workout tab falls back to `training_split.json` below rather than showing nothing — so this file is only needed for a one-off override of what the standing split would otherwise show today.

## training_split.json
The standing weekly split — a fixed rotation, not something re-asked each morning. Single object.
```json
{
  "schedule": {"0": "long_run", "1": "push", "2": "pull", "3": "legs", "4": "rest", "5": "light_run", "6": "bodyweight_circuit"},
  "append_finisher_to": ["push", "pull", "legs"],
  "templates": {
    "push": {"name": "Push Day", "exercises": [{"name": "Incline Dumbbell Bench Press", "target_sets": 4, "target_reps": "10"}]},
    "bodyweight_circuit": {"name": "Bodyweight Circuit", "note": "Freeform — no fixed reps agreed yet."}
  }
}
```
`schedule` keys are Python `date.weekday()` ints (Mon=0..Sun=6). Each `templates` entry is either a checklist (`exercises`, same shape as `workout_plan.json`) or a plain `note` for a day with no fixed reps yet. `append_finisher_to` names which template slots get the `abs_finisher` template's exercises tacked onto the end. Edit this by hand (or ask Claude to) when the split itself changes — it's not something the daily check-ins write to.

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

## lifestyle.json
Factors that measurably affect sleep/recovery but aren't training or food.
```json
{
  "date": "2026-08-14",
  "cigarettes_level": "usual",   // low (0-5) | usual (5-15) | alot (15-20/one pack) | extreme (more than a pack) | null
  "alcohol_drinks": 0,           // count, null if not mentioned that day
  "cannabis_used": false,        // true/false/null
  "vacation": false,             // true if this day wasn't tracked because of travel/vacation
  "notes": null
}
```
One entry per day. Cigarettes default to "usual" going forward once the user gives a baseline — only log a different level when they mention a day was notably different. Don't fabricate entries for days never mentioned; leave the day absent rather than guessing.

`vacation: true` marks a day as deliberately untracked rather than missing — the Nutrition tab's calendar shows a distinct beach icon for these days instead of reading as a logging gap.
