"""Body composition: classification against reference ranges, and what it means.

A scale reading is a list of numbers until something says which of them matter.
This grades each metric against adult-male reference bands and then reads them
against each other — a BMI that says "overweight" means something different on
75kg of muscle than it does otherwise.
"""
from __future__ import annotations

from datetime import date

from .formatting import parse_iso

# status ordering, worst first, for sorting attention
STATUS_RANK = {"very_high": 0, "high": 1, "low": 2, "fair": 3, "normal": 4, "optimal": 5}


def _band(value, bands):
    """bands: list of (upper_exclusive_or_None, status, label)."""
    for upper, status, label in bands:
        if upper is None or value < upper:
            return status, label
    return bands[-1][1], bands[-1][2]


# Adult-male reference ranges. These are the bands consumer bioimpedance scales
# grade against; treat them as orientation, not diagnosis.
def _body_fat(v, _):
    return _band(v, [
        (10, "low", "Very lean"),
        (16, "optimal", "Athletic"),
        (21, "fair", "Fair"),
        (26, "high", "High"),
        (None, "very_high", "Very high"),
    ])


def _bmi(v, _):
    return _band(v, [
        (18.5, "low", "Underweight"),
        (25, "optimal", "Normal"),
        (28, "fair", "High-normal"),
        (32, "high", "Obese range"),
        (None, "very_high", "Severely obese range"),
    ])


def _water(v, _):
    return _band(v, [
        (50, "low", "Low"),
        (55, "fair", "Fair"),
        (66, "optimal", "Optimal"),
        (None, "high", "High"),
    ])


def _protein(v, _):
    return _band(v, [
        (16, "low", "Low"),
        (20, "normal", "Standard"),
        (None, "optimal", "Optimal"),
    ])


def _visceral(v, _):
    return _band(v, [
        (10, "normal", "Normal"),
        (15, "high", "High"),
        (None, "very_high", "Very high"),
    ])


def _subcutaneous(v, _):
    return _band(v, [
        (8.6, "low", "Low"),
        (16.7, "normal", "Normal"),
        (None, "high", "High"),
    ])


def _skeletal_pct(v, ctx):
    """Graded as a share of bodyweight rather than absolute kg."""
    weight = ctx.get("weight_kg") or 0
    if not weight:
        return "normal", "—"
    return _band(v / weight * 100, [
        (34, "low", "Low"),
        (39, "normal", "Standard"),
        (None, "optimal", "High"),
    ])


def _muscle_mass(v, ctx):
    # Scale reference for men above ~75kg.
    return _band(v, [
        (54.4, "low", "Low"),
        (60.3, "normal", "Standard"),
        (None, "optimal", "Above average"),
    ])


def _bone(v, ctx):
    weight = ctx.get("weight_kg") or 0
    expected = 3.9 if weight >= 75 else 3.3 if weight >= 60 else 2.5
    if v < expected - 0.5:
        return "low", "Below average"
    if v > expected + 0.5:
        return "optimal", "Above average"
    return "normal", "Normal"


METRICS = [
    ("weight_kg", "Weight", "kg", None, "Total mass. On its own it cannot tell muscle from fat, which is what the rest of this panel is for."),
    ("bmi", "BMI", "", _bmi, "Weight against height only. It has no way to know how much of you is muscle, so it overstates risk for heavier trained bodies."),
    ("body_fat_pct", "Body fat", "%", _body_fat, "The number that actually tracks fatness. Under ~16% is athletic for men; the low twenties is ordinary."),
    ("muscle_mass_kg", "Muscle mass", "kg", _muscle_mass, "Total muscle including the water held in it. Protect this in a deficit — it is what a half-marathon build tends to erode."),
    ("skeletal_muscle_kg", "Skeletal muscle", "kg", _skeletal_pct, "The muscle you actually train and move with, graded as a share of bodyweight."),
    ("water_pct", "Body water", "%", _water, "Hydration at the moment you stepped on. Reads low after a fasted morning or a hard session the day before, so judge it over several mornings."),
    ("protein_pct", "Protein", "%", _protein, "Protein as a share of bodyweight — a slow-moving marker of how well lean tissue is being maintained."),
    ("bone_mass_kg", "Bone mass", "kg", _bone, "Barely moves month to month; useful mainly as a sanity check on the other readings."),
    ("visceral_fat", "Visceral fat", "", _visceral, "Fat around the organs, the fat that carries real metabolic risk. Under 10 is where you want it."),
    ("subcutaneous_fat_pct", "Subcutaneous fat", "%", _subcutaneous, "Fat under the skin — the visible kind, and the less medically loaded kind."),
    ("bmr", "BMR", "kcal", None, "Calories burned at complete rest. The floor your intake should never sit under."),
    ("scale_heart_rate", "Standing HR", "bpm", None, "Taken while you stand on the scale, so it runs well above your true resting heart rate — the overnight figure on the Analysis tab is the one to judge fitness by."),
    ("body_score", "Body score", "", None, "The scale's own roll-up of everything above."),
]


def katch_mcardle_bmr(weight_kg: float, body_fat_pct: float) -> int:
    """BMR predicted from lean mass. Unlike Mifflin-St Jeor it needs no age,
    and it is the better fit for a muscular body."""
    lean = weight_kg * (1 - body_fat_pct / 100)
    return round(370 + 21.6 * lean)


def _sorted_entries(body_comp: list[dict]) -> list[dict]:
    return sorted(
        [b for b in body_comp if parse_iso(b.get("date"))],
        key=lambda b: b["date"],
    )


def build_body_view(body_comp: list[dict], *, height_cm: int, today: date) -> dict | None:
    entries = _sorted_entries(body_comp)
    if not entries:
        return None

    latest = entries[-1]
    previous = entries[-2] if len(entries) > 1 else None
    weight = latest.get("weight_kg")
    ctx = {"weight_kg": weight, "height_cm": height_cm}

    metrics = []
    for key, label, unit, classifier, meaning in METRICS:
        value = latest.get(key)
        if value is None:
            continue
        status, status_label = classifier(value, ctx) if classifier else ("normal", "")
        delta = None
        if previous and previous.get(key) is not None:
            delta = round(value - previous[key], 2)
        metrics.append({
            "key": key,
            "label": label,
            "unit": unit,
            "value": value,
            "status": status,
            "status_label": status_label,
            "meaning": meaning,
            "delta": delta,
        })

    # Composition split in kg — more actionable than percentages alone.
    fat_mass = lean_mass = None
    if weight and latest.get("body_fat_pct") is not None:
        fat_mass = round(weight * latest["body_fat_pct"] / 100, 1)
        lean_mass = round(weight - fat_mass, 1)

    findings = _analyse(latest, previous, metrics, fat_mass, lean_mass, height_cm, entries)

    return {
        "latest": latest,
        "measured_on": latest.get("date"),
        "entry_count": len(entries),
        "metrics": metrics,
        "attention": [m for m in metrics if m["status"] in ("low", "high", "very_high")],
        "fat_mass_kg": fat_mass,
        "lean_mass_kg": lean_mass,
        "findings": findings,
    }


def _analyse(latest, previous, metrics, fat_mass, lean_mass, height_cm, entries) -> list[dict]:
    out: list[dict] = []
    weight = latest.get("weight_kg")
    bmi = latest.get("bmi")
    bf = latest.get("body_fat_pct")

    # The single most misread pair on any consumer scale.
    if bmi is not None and bf is not None and bmi >= 25 and bf < 22:
        out.append({
            "severity": "good",
            "title": "Ignore the BMI flag",
            "detail": (
                f"BMI {bmi} lands in the overweight band, but body fat is {bf}% and you are carrying "
                f"{latest.get('muscle_mass_kg', '?')}kg of muscle. BMI cannot tell those apart — at "
                f"{height_cm}cm it reads your muscle as excess weight. Body fat and visceral fat are the "
                "numbers to judge yourself on here, and both are fine."
            ),
        })

    if fat_mass is not None:
        out.append({
            "severity": "info",
            "title": "What you are actually made of",
            "detail": (
                f"{lean_mass}kg lean mass, {fat_mass}kg fat mass. Losing fat without losing the lean is the "
                "whole game in a race build — that is what the protein target and the strength sessions are protecting."
            ),
        })

    water = latest.get("water_pct")
    if water is not None and water < 50:
        out.append({
            "severity": "warn",
            "title": f"Body water low at {water}%",
            "detail": (
                "Under 50% is below the male reference range. A single morning reading is weak evidence — "
                "bioimpedance is sensitive to when you last drank, ate, and trained. If it stays under 50 across "
                "several mornings while training volume climbs, that is genuine under-hydration and it will show up "
                "as worse sleep and higher resting heart rate before you feel it."
            ),
        })

    visceral = latest.get("visceral_fat")
    if visceral is not None and visceral < 10:
        out.append({
            "severity": "good",
            "title": f"Visceral fat {visceral}, inside the healthy range",
            "detail": "This is the fat that carries metabolic risk, and yours is in the normal band. It is the reassuring counterweight to the BMI number.",
        })

    bmr = latest.get("bmr")
    if bmr and weight and bf is not None:
        predicted = katch_mcardle_bmr(weight, bf)
        diff = bmr - predicted
        direction = "above" if diff > 0 else "below"
        out.append({
            "severity": "info",
            "title": f"Resting burn {bmr} kcal",
            "detail": (
                f"Katch-McArdle predicts about {predicted} kcal from your lean mass, so the scale's figure is "
                f"{abs(diff)} kcal {direction} that — close enough to trust. Note this is rest only: your actual "
                "daily burn including training is the number the nutrition tab compares intake against."
            ),
        })

    if previous:
        dw = round(weight - previous.get("weight_kg", weight), 1) if weight else 0
        dbf = (
            round(bf - previous["body_fat_pct"], 1)
            if bf is not None and previous.get("body_fat_pct") is not None
            else None
        )
        dmuscle = (
            round(latest.get("muscle_mass_kg", 0) - previous.get("muscle_mass_kg", 0), 1)
            if latest.get("muscle_mass_kg") and previous.get("muscle_mass_kg")
            else None
        )
        if dw or dbf or dmuscle:
            # The question that matters: was the change fat or muscle?
            if dw and dmuscle is not None and dbf is not None:
                if dw > 0 and dmuscle > 0 and dbf <= 0:
                    verdict = "That is weight gained as muscle, not fat — the good version."
                elif dw < 0 and dmuscle < 0:
                    verdict = "Some of that loss was lean mass. Push protein and keep lifting through the build."
                elif dw < 0 and dbf < 0:
                    verdict = "Fat down with lean mass held — exactly what you want in a race build."
                else:
                    verdict = "Mixed movement; another reading or two will show the direction."
            else:
                verdict = "Another reading or two will show whether the change is fat or lean mass."
            out.append({
                "severity": "info",
                "title": f"Since {previous['date']}",
                "detail": (
                    f"Weight {dw:+}kg"
                    + (f", body fat {dbf:+}%" if dbf is not None else "")
                    + (f", muscle {dmuscle:+}kg" if dmuscle is not None else "")
                    + ". " + verdict
                ),
            })
    else:
        out.append({
            "severity": "info",
            "title": "First reading — this is your baseline",
            "detail": (
                "Nothing here is a trend yet. Weigh in on the same morning routine (after waking, before eating or "
                "drinking) a couple of times a week and the fat-versus-muscle split becomes readable in two to three weeks."
            ),
        })

    return out
