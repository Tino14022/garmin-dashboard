"""Cross-domain analysis.

Each tab can already report its own domain. What none of them can do is answer
"does the thing I did over here show up over there" — whether training wrecks
your sleep, whether bad sleep shows up in tomorrow's pace, whether the weight
moving is fat or muscle. That is what this computes.

Every finding carries its sample size and a confidence grade, because most of
these relationships are being read off a handful of days and saying so is the
difference between an insight and a horoscope. Analyses are registered in a
list: adding one means appending a function, not editing a dispatcher.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from . import rank as rank_scale
from .formatting import parse_iso

# Below this many paired observations, a correlation is noise.
MIN_PAIRS = 5
SOLID_N = 12
TENTATIVE_N = 7


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    try:
        sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    except statistics.StatisticsError:
        return None
    if sx == 0 or sy == 0:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    return cov / (sx * sy)


def confidence(n: int) -> str:
    if n >= SOLID_N:
        return "solid"
    if n >= TENTATIVE_N:
        return "tentative"
    return "early"


def strength(r: float) -> str:
    a = abs(r)
    if a >= 0.6:
        return "strong"
    if a >= 0.35:
        return "moderate"
    if a >= 0.2:
        return "weak"
    return "none"


def finding(id_, domains, headline, detail, *, n, severity="info", r=None):
    return {
        "id": id_,
        "domains": domains,
        "headline": headline,
        "detail": detail,
        "n": n,
        "confidence": confidence(n),
        "severity": severity,
        "rank": rank_scale.from_severity(severity),
        "r": round(r, 2) if r is not None else None,
    }


class Context:
    """Everything the analyses read, indexed by date for cheap joins."""

    def __init__(self, payload: dict, today: date):
        self.today = today
        self.sleep = {s["date"]: s for s in payload.get("sleep_trend") or [] if s.get("date")}
        self.load = {l["date"]: l for l in payload.get("load_trend") or [] if l.get("date")}
        self.rhr = {r["date"]: r["rhr"] for r in payload.get("rhr_trend") or [] if r.get("date")}
        self.hrv = {h["date"]: h for h in payload.get("hrv_trend") or [] if h.get("date")}
        self.burn = {c["date"]: c for c in payload.get("calorie_trend") or [] if c.get("date")}
        self.lifestyle = {l["date"]: l for l in payload.get("lifestyle") or [] if l.get("date")}
        self.body = sorted(
            [b for b in payload.get("body_comp") or [] if b.get("date")],
            key=lambda b: b["date"],
        )
        self.runs = [r for r in payload.get("recent_runs") or [] if r.get("date")]
        self.sessions = [s for s in (payload.get("training") or {}).get("sessions") or [] if s.get("date")]
        self.nutrition_view = payload.get("nutrition_view") or {}
        self.race_plan = payload.get("race_plan") or {}
        self.vo2max = payload.get("vo2max_trend") or []

        self.training_days = {s["date"] for s in self.sessions}
        self.intake: dict[str, float] = {}
        self.protein: dict[str, float] = {}
        for n in payload.get("nutrition") or []:
            d = n.get("date")
            if not d:
                continue
            self.intake[d] = self.intake.get(d, 0) + (n.get("calories") or 0)
            self.protein[d] = self.protein.get(d, 0) + (n.get("protein_g") or 0)

    def day_before(self, iso_date: str) -> str | None:
        d = parse_iso(iso_date)
        return (d - timedelta(days=1)).isoformat() if d else None


# --------------------------------------------------------------------------
# Analyses. Each takes a Context and returns a finding dict or None.
# --------------------------------------------------------------------------

def sleep_after_training(ctx: Context):
    after, rest = [], []
    for iso_date, s in ctx.sleep.items():
        score = s.get("score")
        prev = ctx.day_before(iso_date)
        if score is None or prev is None:
            continue
        (after if prev in ctx.training_days else rest).append(score)
    if len(after) < 3 or len(rest) < 3:
        return None
    a, r = statistics.fmean(after), statistics.fmean(rest)
    gap = round(a - r)
    n = len(after) + len(rest)
    if abs(gap) < 3:
        return finding(
            "sleep_vs_training", ["sleep", "training"],
            "Training isn't costing you sleep",
            f"Sleep score averages {round(a)} after a training day against {round(r)} after rest "
            f"({len(after)} vs {len(rest)} nights). No meaningful difference, which means your current "
            "load is inside what you recover from.",
            n=n,
        )
    if gap > 0:
        return finding(
            "sleep_vs_training", ["sleep", "training"],
            f"You sleep {gap} points better after training",
            f"{round(a)} average after a training day against {round(r)} after rest "
            f"({len(after)} vs {len(rest)} nights). Training is helping you sleep, so the load is well matched "
            "to your recovery — no reason to hold back on volume for sleep's sake.",
            n=n, severity="good",
        )
    return finding(
        "sleep_vs_training", ["sleep", "training"],
        f"Training costs you {abs(gap)} points of sleep",
        f"{round(a)} average after a training day against {round(r)} after rest "
        f"({len(after)} vs {len(rest)} nights). Worth checking how late you train — finishing hard sessions "
        "within about three hours of bed keeps core temperature and heart rate up into the night.",
        n=n, severity="warn",
    )


def sleep_vs_next_day_pace(ctx: Context):
    scores, paces = [], []
    for run in ctx.runs:
        pace = run.get("pace_sec_per_km")
        night = ctx.sleep.get(run["date"])
        if not pace or not night or night.get("score") is None:
            continue
        # Easy runs vary by intent, not fitness; compare like with like.
        if run.get("label") not in ("BASE", "RECOVERY", "AEROBIC_BASE", "MAINTAINING"):
            continue
        scores.append(night["score"])
        paces.append(pace)
    if len(scores) < MIN_PAIRS:
        return None
    r = pearson(scores, paces)
    if r is None or strength(r) == "none":
        return finding(
            "sleep_vs_pace", ["sleep", "running"],
            "Sleep isn't visibly moving your easy pace",
            f"Across {len(scores)} easy runs there's no consistent link between the night's sleep score and "
            "the pace you held. Easy pace is a blunt instrument for this — it would show up in hard sessions first.",
            n=len(scores), r=r,
        )
    # Negative r = better sleep, lower (faster) pace.
    if r < 0:
        return finding(
            "sleep_vs_pace", ["sleep", "running"],
            "Better sleep shows up as faster easy running",
            f"A {strength(r)} relationship across {len(scores)} easy runs: the nights you sleep well are the "
            "days you hold a quicker pace at the same effort. Protecting sleep is doing real work for your training.",
            n=len(scores), r=r, severity="good",
        )
    return finding(
        "sleep_vs_pace", ["sleep", "running"],
        "Your faster easy runs follow worse sleep",
        f"A {strength(r)} relationship across {len(scores)} runs, which is backwards from the usual pattern and "
        "most likely coincidence at this sample size — or you're pushing easy days harder when you feel flat.",
        n=len(scores), r=r,
    )


def lifestyle_vs_sleep(ctx: Context):
    if not ctx.lifestyle:
        return None
    results = []
    for substance, label in (("alcohol_units", "alcohol"), ("cannabis", "cannabis"), ("cigarettes", "cigarettes")):
        on, off = [], []
        for iso_date, night in ctx.sleep.items():
            score = night.get("score")
            prev = ctx.day_before(iso_date)
            if score is None or prev is None:
                continue
            entry = ctx.lifestyle.get(prev)
            used = bool(entry and entry.get(substance))
            (on if used else off).append(score)
        if len(on) >= 2 and len(off) >= 3:
            results.append((label, round(statistics.fmean(on) - statistics.fmean(off)), len(on), len(off)))
    if not results:
        return None
    parts = [
        f"{label} {gap:+} points ({n_on} night{'s' if n_on != 1 else ''} vs {n_off} without)"
        for label, gap, n_on, n_off in results
    ]
    worst = min(results, key=lambda x: x[1])
    severity = "warn" if worst[1] <= -4 else "info"
    return finding(
        "lifestyle_vs_sleep", ["lifestyle", "sleep"],
        f"{worst[0].capitalize()} nights cost you {abs(worst[1])} sleep points"
        if worst[1] < 0 else "No clear lifestyle hit to your sleep yet",
        "Sleep score on nights after use, against nights without: " + "; ".join(parts) +
        ". Small samples — this sharpens as more days are logged.",
        n=sum(r[2] + r[3] for r in results), severity=severity,
    )


def load_vs_recovery(ctx: Context):
    """Acute training load against overnight HRV — the earliest overreaching signal."""
    loads, hrvs = [], []
    for iso_date, night in ctx.sleep.items():
        hrv = night.get("avg_overnight_hrv")
        load = ctx.load.get(iso_date, {}).get("atl")
        if hrv is None or load is None:
            continue
        loads.append(load)
        hrvs.append(hrv)
    if len(loads) < MIN_PAIRS:
        return None
    r = pearson(loads, hrvs)
    if r is None or strength(r) == "none":
        return finding(
            "load_vs_hrv", ["training", "recovery"],
            "Your HRV is holding steady against training load",
            f"Across {len(loads)} nights, overnight HRV doesn't drop as acute load rises. That's the signal you "
            "want — it means the current build is inside your capacity to absorb.",
            n=len(loads), r=r, severity="good",
        )
    if r < 0:
        return finding(
            "load_vs_hrv", ["training", "recovery"],
            "HRV drops as your training load climbs",
            f"A {strength(r)} inverse relationship across {len(loads)} nights. Some of this is normal and expected. "
            "Watch it if HRV keeps falling while load is flat — that's the point where fatigue is accumulating "
            "faster than you're clearing it.",
            n=len(loads), r=r, severity="warn",
        )
    return None


def bedtime_consistency(ctx: Context):
    hours = [n["bedtime_hour"] for n in ctx.sleep.values() if n.get("bedtime_hour") is not None]
    scores = [
        (n["bedtime_hour"], n["score"])
        for n in ctx.sleep.values()
        if n.get("bedtime_hour") is not None and n.get("score") is not None
    ]
    if len(hours) < MIN_PAIRS:
        return None
    spread = statistics.pstdev(hours)
    r = pearson([h for h, _ in scores], [s for _, s in scores]) if len(scores) >= MIN_PAIRS else None
    detail = (
        f"Your bedtime varies by about {spread:.1f} hours night to night across {len(hours)} nights. "
    )
    if spread >= 1.5:
        detail += (
            "That's a wide swing — an irregular schedule blunts sleep quality independently of how long you "
            "spend in bed, because your body never settles on when to start recovering."
        )
        severity = "warn"
        headline = f"Bedtime swings by {spread:.1f} hours"
    else:
        detail += "That's reasonably consistent, which is worth more for sleep quality than any single long night."
        severity = "good"
        headline = "Your bedtime is consistent"
    if r is not None and strength(r) != "none":
        detail += (
            f" Later nights also track {'worse' if r < 0 else 'better'} sleep scores in your own data."
        )
    return finding("bedtime", ["sleep"], headline, detail, n=len(hours), severity=severity, r=r)


def energy_balance_vs_weight(ctx: Context):
    if len(ctx.body) < 2:
        return None
    first, last = ctx.body[0], ctx.body[-1]
    d1, d2 = parse_iso(first["date"]), parse_iso(last["date"])
    if not d1 or not d2 or d1 == d2:
        return None
    days = (d2 - d1).days
    dw = round((last.get("weight_kg") or 0) - (first.get("weight_kg") or 0), 1)
    balance = ctx.nutrition_view.get("week_balance_kcal")
    detail = f"Weight moved {dw:+}kg over {days} days. "
    if balance is not None:
        implied = round(balance * days / 7700, 1)
        detail += (
            f"Your logged energy balance of {balance:+} kcal/day predicts about {implied:+}kg over that stretch. "
        )
        if abs(implied - dw) > 1.0:
            detail += (
                "The gap between predicted and actual is large, which usually means the food log is incomplete "
                "rather than that your metabolism is unusual."
            )
        else:
            detail += "Prediction and reality line up, so the food log is tracking reality reasonably well."
    dbf = (
        round((last.get("body_fat_pct") or 0) - (first.get("body_fat_pct") or 0), 1)
        if last.get("body_fat_pct") is not None and first.get("body_fat_pct") is not None
        else None
    )
    if dbf is not None:
        detail += f" Body fat moved {dbf:+}% across the same window."
    return finding(
        "balance_vs_weight", ["nutrition", "body"],
        f"Weight {dw:+}kg over {days} days",
        detail, n=len(ctx.body),
    )


def fuelling_risk(ctx: Context):
    nv = ctx.nutrition_view
    balance = nv.get("week_balance_kcal")
    protein = nv.get("week_avg_protein_g")
    target = nv.get("protein_target_g")
    days = nv.get("week_days_compared") or 0
    if balance is None or days < 2:
        return None
    weekly_km = sum(r.get("distance_km") or 0 for r in ctx.runs)
    if balance <= -500:
        severity, headline = "warn", f"Running a {abs(balance)} kcal/day deficit through a race build"
        detail = (
            f"Across {days} compared days you averaged {abs(balance)} kcal/day under your measured burn while "
            f"covering {weekly_km:.1f}km of running. A deficit that size during a build costs you adaptation and "
            "lean mass, not just fat — the long runs are what suffer first."
        )
    elif balance >= 500:
        severity, headline = "info", f"Running a {balance} kcal/day surplus"
        detail = (
            f"Across {days} compared days you averaged {balance} kcal/day over your measured burn. Fine if you're "
            "deliberately building, worth trimming if you'd rather not carry the extra weight over 21.1km."
        )
    else:
        severity, headline = "good", "Intake is roughly matched to your burn"
        detail = (
            f"Averaging {balance:+} kcal/day against measured burn across {days} days — close to maintenance, "
            "which is the right place to sit during a build."
        )
    if protein is not None and target:
        pct = round(protein / target * 100)
        detail += (
            f" Protein is averaging {protein}g against a {target}g target ({pct}%)"
            + (", which is where it should be." if pct >= 85 else " — short, and that matters most while in a deficit.")
        )
    return finding("fuelling", ["nutrition", "training"], headline, detail, n=days, severity=severity)


def mileage_vs_resting_hr(ctx: Context):
    if len(ctx.rhr) < MIN_PAIRS:
        return None
    pairs = []
    for iso_date, rhr in ctx.rhr.items():
        d = parse_iso(iso_date)
        if not d:
            continue
        week_km = sum(
            r.get("distance_km") or 0
            for r in ctx.runs
            if (pd := parse_iso(r["date"])) and 0 <= (d - pd).days < 7
        )
        pairs.append((week_km, rhr))
    if len(pairs) < MIN_PAIRS:
        return None
    r = pearson([p[0] for p in pairs], [p[1] for p in pairs])
    if r is None or strength(r) == "none":
        return None
    rising = r > 0
    # A weak correlation is worth mentioning but not worth alarming over; only
    # a moderate-or-better rise in resting HR earns a warning.
    weak = strength(r) == "weak"
    if rising:
        headline = (
            "Resting heart rate drifts up slightly with mileage"
            if weak
            else "Resting heart rate climbs with your mileage"
        )
        tail = (
            "Weak enough to be noise at this sample size — worth watching rather than acting on."
            if weak
            else "Rising resting HR alongside volume is the classic sign that recovery isn't keeping up — "
            "worth a genuinely easy week if it continues."
        )
        severity = "info" if weak else "warn"
    else:
        headline = "Resting heart rate falls as mileage rises"
        tail = "That's aerobic fitness improving: more running, lower resting heart rate. Exactly the direction you want."
        severity = "info" if weak else "good"
    return finding(
        "mileage_vs_rhr", ["running", "recovery"], headline,
        f"A {strength(r)} relationship across {len(pairs)} days. " + tail,
        n=len(pairs), r=r, severity=severity,
    )


def race_weight(ctx: Context):
    if not ctx.body or not ctx.race_plan:
        return None
    latest = ctx.body[-1]
    weight = latest.get("weight_kg")
    bf = latest.get("body_fat_pct")
    distance = ctx.race_plan.get("race_distance_km")
    if not weight or not distance or bf is None:
        return None
    # Widely used rule of thumb: roughly 2 seconds per km per kg carried.
    fat_mass = weight * bf / 100
    spare = max(0.0, fat_mass - weight * 0.12)  # 12% is a sane floor for a male runner
    seconds = round(spare * 2 * distance)
    if spare < 1:
        return None
    mins, secs = divmod(seconds, 60)
    return finding(
        "race_weight", ["body", "running"],
        f"About {spare:.0f}kg of spare mass to carry over {distance}km",
        (
            f"At {weight}kg and {bf}% body fat you're carrying roughly {fat_mass:.0f}kg of fat, of which about "
            f"{spare:.0f}kg is above what a lean male runner would hold. On the usual rule of two seconds per "
            f"kilometre per kilogram that's around {mins}:{secs:02d} over the race. Worth knowing, not worth "
            "crash-dieting for mid-build — losing it slowly while protecting muscle is the only version that helps."
        ),
        n=1,
    )


def recovery_debt(ctx: Context):
    """Consecutive training days with no rest — where injury risk actually lives."""
    if not ctx.sessions:
        return None
    days = sorted({parse_iso(s["date"]) for s in ctx.sessions if parse_iso(s["date"])}, reverse=True)
    if not days:
        return None
    streak = 1
    for a, b in zip(days, days[1:]):
        if (a - b).days == 1:
            streak += 1
        else:
            break
    if streak < 5:
        return None
    return finding(
        "recovery_debt", ["training", "recovery"],
        f"{streak} consecutive training days without a rest day",
        (
            f"You've trained {streak} days in a row. Streaks feel productive and the badge rewards them, but "
            "adaptation happens on the rest days — this is where a build usually turns into an injury. One full "
            "day off costs you nothing and buys back the week."
        ),
        n=streak, severity="warn",
    )


def sleep_debt(ctx: Context):
    recent = sorted(ctx.sleep.items(), reverse=True)[:7]
    hours = [n.get("hours") for _, n in recent if n.get("hours")]
    needs = [n.get("sleep_need_min") for _, n in recent if n.get("sleep_need_min")]
    if len(hours) < 4:
        return None
    avg = statistics.fmean(hours)
    need = statistics.fmean(needs) / 60 if needs else 8.0
    debt = round((need - avg) * len(hours), 1)
    if debt <= 1:
        detail = (
            f"Over the last {len(hours)} nights you're meeting what your watch says you need. That is the single "
            "biggest lever on both training adaptation and appetite control."
        )
        # Garmin's "need" adapts to your own habits, so it can settle low and call
        # a chronically short sleeper adequately rested.
        if avg < 7:
            detail += (
                f" Worth a caveat though: {avg:.1f}h is short in absolute terms, and the {need:.1f}h target is "
                "your watch's estimate of your need rather than a physiological floor — it drifts toward whatever "
                "you habitually sleep. Most adults training this much do better nearer 8."
            )
            severity = "info"
        else:
            severity = "good"
        return finding(
            "sleep_debt", ["sleep"],
            f"Sleeping {avg:.1f}h against a {need:.1f}h need",
            detail, n=len(hours), severity=severity,
        )
    return finding(
        "sleep_debt", ["sleep", "training"],
        f"About {debt}h of sleep debt over {len(hours)} nights",
        (
            f"Averaging {avg:.1f}h against the {need:.1f}h your watch estimates you need. Debt at this level "
            "blunts training adaptation, raises perceived effort on easy runs, and pushes appetite up — it shows "
            "up in every other panel on this page before it shows up as feeling tired."
        ),
        n=len(hours), severity="warn",
    )


ANALYSES = [
    sleep_debt,
    sleep_after_training,
    sleep_vs_next_day_pace,
    bedtime_consistency,
    load_vs_recovery,
    fuelling_risk,
    energy_balance_vs_weight,
    mileage_vs_resting_hr,
    recovery_debt,
    lifestyle_vs_sleep,
    race_weight,
]

SEVERITY_ORDER = {"warn": 0, "good": 1, "info": 2}


def build_insights(payload: dict, today: date) -> dict:
    ctx = Context(payload, today)
    findings = []
    for analyse in ANALYSES:
        try:
            result = analyse(ctx)
        except Exception as e:  # noqa: BLE001 - one bad analysis must not kill the page
            print(f"  ! insight {analyse.__name__} failed: {e}")
            continue
        if result:
            findings.append(result)
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 3), -f["n"]))
    return {
        "findings": findings,
        "counts": {
            "warn": sum(1 for f in findings if f["severity"] == "warn"),
            "good": sum(1 for f in findings if f["severity"] == "good"),
            "total": len(findings),
        },
    }
