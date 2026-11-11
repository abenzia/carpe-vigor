"""My training: a structured home program, day by day, held to the person's own health record.

The rule (CLAUDE.md): the app does not diagnose, and anything the doctor said comes first. So the program is built by
plain code from public guidelines, and every choice that comes from the person's record is shown with its reason and
its source:
- the doctor's words: a model reads them once into movement limits (no impact, joints to spare, an intensity cap),
  quoting the words it read; code applies them;
- the readiness questions (after the public PAR-Q+): chest pain, fainting or "supervised exercise only" stop the program
  until the doctor is seen; any other yes keeps it gentle until the person says their doctor cleared it;
- the measures: under 18 or pregnant, no program (the doctor plans it); 65 and over, balance on 3 days (EpiCentro) and a
  prudent start; BMI 30 and over, low impact and no floor work (getting down and up is a load of its own);
- the numbers against the doctor's targets (checkup.py): blood pressure or resting heart rate above target keep the effort
  moderate (5-6 out of 10, Ministero della Salute) with short holds and no breath-holding; blood sugar above target,
  never two days in a row without moving (ADA).
The plan itself: 4-week blocks (the 4th lighter), strength on non-consecutive days, the week's aerobic minutes built up
toward 150-300 (HHS). It moves with the person: each exercise goes one rung up or down a ladder (exercises.py) on their
"too easy" / "too hard" / "it hurt", and a block grows only if the one before was done.
Nothing here pays: the reward still counts measured steps (reward.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from . import checkup, llm
from .exercises import COOL_DOWN, LADDERS, WARM_UP, Exercise, all_exercises

SOURCES = {
    "hhs": ("US HHS — Physical Activity Guidelines for Americans, 2nd edition",
            "https://health.gov/our-work/nutrition-physical-activity/physical-activity-guidelines"),
    "rpe": ("Ministero della Salute — Attività fisica negli adulti",
            "https://www.salute.gov.it/new/it/tema/attivita-fisica/attivita-fisica-negli-adulti/"),
    "balance": ("EpiCentro (Istituto Superiore di Sanità) — Attività fisica: livelli consigliati",
                "https://www.epicentro.iss.it/attivita_fisica/Livelli-Consigliati"),
    "parq": ("PAR-Q+ — Physical Activity Readiness Questionnaire for Everyone", "https://eparmedx.com/"),
    "ada": ("American Diabetes Association — Standards of Care: physical activity",
            "https://diabetesjournals.org/care/article/48/Supplement_1/S86/157564/5-Facilitating-Positive-Health-Behaviors-and"),
    "impact": ("NIDDK — Tips to help you get active", "https://www.niddk.nih.gov/health-information/weight-management/tips-get-active"),
    "breath": ("American Heart Association — Strength and resistance training exercise",
               "https://www.heart.org/en/healthy-living/fitness/fitness-basics/strength-and-resistance-training-exercise"),
}

# After the PAR-Q+ general questions, in our words. Medicines are not asked: the app does not deal with them.
QUESTIONS = [
    ("heart", "Has a doctor ever said you have a heart condition or high blood pressure?"),
    ("chest", "Do you feel pain in your chest at rest, in daily activities or when you are active?"),
    ("dizzy", "In the last 12 months, have you lost your balance because of dizziness, or fainted?"),
    ("chronic", "Do you live with another long-term condition that your doctor follows?"),
    ("joints", "Do you have a bone, joint or muscle problem that could get worse if you move more?"),
    ("supervised", "Has a doctor said you should only exercise under medical supervision?"),
]
STOP = {"chest", "dizzy", "supervised"}   # a yes here: see the doctor before any program

LEVELS = ("beginner", "intermediate", "advanced")
RPE_TARGET = {"beginner": 5, "intermediate": 6, "advanced": 7}       # out of 10 (Ministero: moderate 5-6, vigorous 7-8)
REST_SECONDS = {"beginner": 60, "intermediate": 75, "advanced": 90}
# sets x reps, week 1..4 of a block (the 4th lighter)
VOLUME = {"beginner": [(2, 10), (2, 12), (3, 10), (2, 8)], "intermediate": [(3, 10), (3, 12), (4, 10), (2, 10)],
          "advanced": [(3, 12), (4, 12), (4, 15), (3, 10)]}
HOLD = {"beginner": [15, 20, 25, 15], "intermediate": [25, 30, 40, 20], "advanced": [40, 45, 60, 30]}   # seconds
AEROBIC = {"beginner": 90, "intermediate": 150, "advanced": 180}    # week's aerobic minutes at the start
WEEK_FACTOR = [1.0, 1.1, 1.2, 0.8]
MAX_AEROBIC = 300
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# which weekdays carry what, by days a week: S strength, C cardio (aerobic), L longer cardio; the rest is active rest
SCHEDULE = {3: {0: "S", 2: "C", 4: "S"}, 4: {0: "S", 1: "C", 3: "S", 5: "C"},
            5: {0: "S", 1: "C", 3: "S", 4: "C", 5: "L"}, 6: {0: "S", 1: "C", 2: "S", 3: "C", 4: "S", 5: "L"}}
STRENGTH_A, STRENGTH_B = ("squat", "push", "hinge", "core"), ("lunge", "pull", "calf", "core")
PATTERN_NAMES = {"squat": "Squats", "hinge": "Hip hinges", "push": "Push-ups", "pull": "Rows", "lunge": "Lunges and step-ups",
                 "core": "Core", "calf": "Calf raises", "balance": "Balance"}


class DoctorLimits(BaseModel):
    avoid_impact: bool = Field(default=False, description="The doctor said no running, jumping or high-impact activity")
    spare: list[Literal["knees", "back", "shoulders"]] = Field(default_factory=list,
                                                               description="Joints the doctor said to spare or protect")
    intensity: Literal["light", "moderate", "any"] = Field(default="any", description="The highest effort the doctor allowed")
    quote: str = Field(default="", description="The doctor's words these limits come from, word for word; empty if none")


READ = """You read what a person says their doctor told them and pick out ONLY what limits their physical activity: \
no running or jumping, joints to spare (knees, back, shoulders), the highest effort allowed. Quote the words you used. \
If the doctor said nothing about movement limits, return no limits and an empty quote. Never add limits of your own."""


def read_doctor(doctor_said: str) -> DoctorLimits:
    if not (doctor_said or "").strip():
        return DoctorLimits()
    return llm.ask(READ, f"WHAT THE DOCTOR SAID: {doctor_said}", DoctorLimits, tier="mid")


def _mock_read(task: str) -> DoctorLimits:
    """No model: the plain words, in English or Italian."""
    said = task.split("WHAT THE DOCTOR SAID:", 1)[-1]
    low = said.lower()
    spare = [j for j, w in (("knees", r"knee|ginocch"), ("back", r"back|schiena|lombar"), ("shoulders", r"shoulder|spalla|spalle"))
             if re.search(w, low)]
    impact = bool(re.search(r"no running|not run|avoid running|jump|non correre|niente corsa|evit\w* (la )?corsa|salti", low))
    light = bool(re.search(r"gentle|light activity|legger|dolce", low))
    moderate = bool(re.search(r"moderate|moderat|not too hard|senza esagerare", low))
    hit = re.search(r"[^.]*(knee|ginocch|back|schiena|shoulder|spall|run|corr|jump|salt|gentle|legger|moderat)[^.]*\.?", said, re.I)
    return DoctorLimits(avoid_impact=impact, spare=spare, intensity="light" if light else "moderate" if moderate else "any",
                        quote=hit.group(0).strip() if hit and (spare or impact or light or moderate) else "")


llm.mock_answers.setdefault("DoctorLimits", _mock_read)


@dataclass
class Limits:
    stop: str = ""                   # no program, and why
    gentle: bool = False             # until the doctor clears it
    low_impact: bool = False
    no_floor: bool = False
    spare: set[str] = field(default_factory=set)
    max_rpe: int = 8
    max_hold: int = 60
    balance_days: int = 0
    never_two_still: bool = False
    level_cap: int = 2
    reasons: list[dict] = field(default_factory=list)   # what, why, source

    def because(self, what: str, why: str, source: str) -> None:
        self.reasons.append({"what": what, "why": why, "source": source})


def limits(health: dict, rows: list[dict], doctor: DoctorLimits | dict | None, answers: dict, cleared: bool) -> Limits:
    """Everything the person's record asks of the program, each with its reason."""
    doctor = DoctorLimits(**doctor) if isinstance(doctor, dict) else doctor or DoctorLimits()
    L = Limits()
    age, bmi = health.get("age"), health.get("bmi")
    if bmi is None and health.get("height_cm") and health.get("weight_kg"):
        bmi = round(health["weight_kg"] / (health["height_cm"] / 100) ** 2, 1)
    if age is not None and age < 18:
        L.stop = "This program is for adults: under 18, movement is planned with your doctor or pediatrician."
        return L
    if health.get("pregnant"):
        L.stop = "In pregnancy or breastfeeding, movement is planned with your doctor or midwife: no program here."
        return L
    stops = [q for k, q in QUESTIONS if k in STOP and answers.get(k)]
    if stops:
        L.stop = ("You answered yes to: “" + stops[0] + "” Please see your doctor before starting a program; "
                  "when they say you can, come back and tell us here.")
        if not cleared:
            return L
        L.stop = ""
    yes = [q for k, q in QUESTIONS if k not in STOP and answers.get(k)]
    if (yes or stops) and not cleared:
        L.gentle, L.max_rpe, L.level_cap = True, 5, 0
        L.because("Gentle start: walking and the easiest rung of each exercise, effort up to 5 out of 10",
                  "you answered yes to a readiness question; talk to your doctor, then tick that they cleared you", "parq")
    if age is not None and age >= 65:
        L.balance_days, L.level_cap = 3, min(L.level_cap, 1)
        L.because("Balance exercises on 3 days a week, and a prudent start", f"you are {age}", "balance")
    if bmi is not None and bmi >= 30:
        L.low_impact, L.no_floor = True, True
        L.because("Low impact (no jumping or jogging) and exercises done standing or on a chair, not on the floor",
                  f"BMI {bmi:g}: easier on the joints, and getting down and up again is a load of its own", "impact")
    off = checkup.topics(rows)
    hr_off = any(v["key"] == "resting_hr" and v["target"] is not None and not v["status"].startswith("at ")
                 for v in checkup.view(rows))
    if "blood_pressure" in off or hr_off:
        L.max_rpe, L.max_hold = min(L.max_rpe, 6), 20
        L.because("Moderate effort (5-6 out of 10), holds of 20 seconds at most, breathing out on every effort",
                  "your " + ("blood pressure" if "blood_pressure" in off else "resting heart rate") +
                  " is above your doctor's target: no breath-holding, no all-out efforts", "breath")
    if "sugar" in off:
        L.never_two_still = True
        L.because("Some movement every day, and a 10-minute walk after main meals on rest days",
                  "your blood sugar is above your doctor's target: never two days in a row without moving", "ada")
    if doctor.avoid_impact:
        L.low_impact = True
    L.spare |= set(doctor.spare)
    if doctor.intensity == "light":
        L.max_rpe, L.level_cap = min(L.max_rpe, 4), 0
    elif doctor.intensity == "moderate":
        L.max_rpe = min(L.max_rpe, 6)
    if doctor.quote and (doctor.avoid_impact or doctor.spare or doctor.intensity != "any"):
        parts = (["no impact"] if doctor.avoid_impact else []) + [f"sparing the {j}" for j in doctor.spare] + \
                ([f"{doctor.intensity} effort only"] if doctor.intensity != "any" else [])
        L.because("As your doctor said: " + ", ".join(parts), f"your doctor's words: “{doctor.quote.strip().rstrip('.')}”", "doctor")
    return L


def allowed(e: Exercise, L: Limits) -> bool:
    return not ((e.floor and L.no_floor) or (e.impact and L.low_impact) or (e.knees and "knees" in L.spare) or
                (e.back and "back" in L.spare) or (e.shoulders and "shoulders" in L.spare) or
                (e.hold and L.max_hold < 15))


def level(health: dict, steps: list[int], L: Limits) -> int:
    """0 beginner, 1 intermediate, 2 advanced: the activity the person reports and the steps they really take."""
    act = {"sedentary": 0, "light": 0.5, "moderate": 1, "active": 2, "very active": 2}.get(health.get("activity"))
    walked = None
    if steps:
        avg = sum(steps) / len(steps)
        walked = 0 if avg < 5000 else 1 if avg < 9000 else 2
    known = [x for x in (act, walked) if x is not None]
    return min(L.level_cap, round(sum(known) / len(known)) if known else 0)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _planned_kinds(days: int) -> dict[int, str]:
    return SCHEDULE[min(6, max(3, days))]


def block_shift(state: dict, upto: date) -> int:
    """How much the program has grown, block by block, until the block containing `upto`: up when a block was
    done (8 sessions in 10) without straining, down when fewer than half were done."""
    start, log = _monday(date.fromisoformat(state["start"])), state.get("log", {})
    kinds = _planned_kinds(state["setup"]["days"])
    shift, b = 0, 0
    while True:
        first = start + timedelta(weeks=4 * b)
        if first + timedelta(weeks=4) > _monday(upto):
            return shift
        planned = [first + timedelta(days=i) for i in range(28) if i % 7 in kinds]
        done = [log[d.isoformat()] for d in planned if log.get(d.isoformat(), {}).get("done")]
        share = len(done) / len(planned) if planned else 0
        rpes = [e["rpe"] for e in done if e.get("rpe")]
        strained = rpes and sum(rpes) / len(rpes) > RPE_TARGET[LEVELS[min(2, max(0, state.get("level", 0) + shift))]] + 1
        shift += 1 if share >= 0.8 and not strained else -1 if share < 0.5 else 0
        shift = max(-1, min(2, shift))
        b += 1


def rung_moves(state: dict, before: date) -> tuple[dict[str, int], set[str]]:
    """Each pattern's steps up or down from the person's feedback, and the patterns that hurt twice (dropped)."""
    by_id = {e.id: p for p, ladder in LADDERS.items() for e in ladder}
    moves: dict[str, int] = {}
    hurts: dict[str, int] = {}
    for on, entry in sorted(state.get("log", {}).items()):
        if on >= before.isoformat():
            break
        for ex, said in (entry.get("feedback") or {}).items():
            p = by_id.get(ex)
            if not p:
                continue
            moves[p] = moves.get(p, 0) + {"easy": 1, "hard": -1, "hurt": -1}.get(said, 0)
            if said == "hurt":
                hurts[p] = hurts.get(p, 0) + 1
    return moves, {p for p, n in hurts.items() if n >= 2}


def pick(pattern: str, want: int, L: Limits) -> Exercise | None:
    """The allowed rung nearest to the wanted one, preferring easier."""
    ladder = LADDERS[pattern]
    want = max(0, min(len(ladder) - 1, want))
    for distance in range(len(ladder)):
        for i in (want - distance, want + distance):
            if 0 <= i < len(ladder) and allowed(ladder[i], L):
                return ladder[i]
    return None


def _cardio(kind: str, minutes: int, lvl: int, L: Limits) -> dict:
    rpe = min(L.max_rpe, RPE_TARGET[LEVELS[lvl]])
    if lvl >= 2 and not L.low_impact and L.max_rpe >= 8 and kind == "C":
        what, how = "Walk-jog intervals", f"5 minutes brisk walking, then 1 minute easy jog and 2 minutes walking, repeated, 5 minutes easy walk to finish"
    elif lvl >= 1 and L.max_rpe >= 7:
        what, how = "Brisk walk with faster stretches", "Every few minutes walk faster for 1 minute (you can talk, not sing), then 2 minutes at your usual brisk pace"
    else:
        what, how = "Brisk walk", "A pace where you can talk but not sing: the talk test for moderate effort"
    if kind == "L":
        what = "Longer " + what[0].lower() + what[1:]
    alt = "or cycling, swimming, a stationary bike" if L.low_impact else "or cycling, swimming, dancing"
    return {"what": what, "minutes": minutes, "how": how, "alt": alt, "rpe": rpe}


def day(state: dict, health: dict, steps: list[int], L: Limits, on: date) -> dict:
    """One day of the program: a strength session, aerobic, or active rest, with its numbers."""
    setup = state["setup"]
    start = _monday(date.fromisoformat(state["start"]))
    weeks = max(0, (_monday(on) - start).days // 7)
    wk = weeks % 4
    lvl0 = state.get("level", 0)
    shift = block_shift(state, on)
    lvl = max(0, min(L.level_cap, lvl0 + max(0, shift)))
    name = LEVELS[lvl]
    kinds = _planned_kinds(setup["days"])
    kind = kinds.get(on.weekday(), "R")
    strength_days = [d for d, k in sorted(kinds.items()) if k == "S"]
    aerobic_days = [d for d, k in sorted(kinds.items()) if k in "CL"]
    total = min(MAX_AEROBIC, round((AEROBIC[name] + 20 * max(0, shift)) * WEEK_FACTOR[wk]))
    if L.gentle:
        total = min(total, 90)
    budget = setup["minutes"]
    finisher = 10 if budget >= 30 else 0
    share = max(10, (total - finisher * len(strength_days)) / max(1, len(aerobic_days) + 0.5 * ("L" in kinds.values())))
    out = {"on": on.isoformat(), "weekday": DAY_NAMES[on.weekday()], "kind": kind, "week_of_block": wk + 1,
           "block": weeks // 4 + 1, "level": name, "aerobic_week": total, "rpe": min(L.max_rpe, RPE_TARGET[name])}
    if kind == "R":
        walk = 15 if not L.never_two_still else 20
        out.update(title="Active rest", minutes=walk,
                   items=[f"Easy {walk}-minute walk", "The cool-down stretches, slowly"] +
                         (["A 10-minute walk after lunch and after dinner"] if L.never_two_still else []))
        return out
    if kind in "CL":
        minutes = min(round(share * (1.5 if kind == "L" else 1)), max(budget, 20) if kind == "C" else max(budget + 15, 30))
        cardio = _cardio(kind, minutes, lvl, L)
        out.update(title=cardio["what"], minutes=minutes, cardio=cardio)
        return out
    moves, dropped = rung_moves(state, on)
    patterns = STRENGTH_A if strength_days.index(on.weekday()) % 2 == 0 else STRENGTH_B
    sets, reps = VOLUME[name][wk]
    hold = min(L.max_hold, HOLD[name][wk])
    blocks, left_out = [], []
    for p in patterns:
        if p in dropped:
            left_out.append(f"{PATTERN_NAMES[p]}: it hurt twice — leave it out and ask your doctor")
            continue
        e = pick(p, 0 if L.gentle else lvl + moves.get(p, 0), L)
        if not e:
            left_out.append(f"{PATTERN_NAMES[p]}: every version loads what your record asks to spare")
        if e:
            blocks.append({"id": e.id, "name": e.name, "sets": sets, "reps": None if e.hold else reps,
                           "seconds": hold if e.hold else None, "rest": REST_SECONDS[name], "exercise": e})
    if L.balance_days and strength_days.index(on.weekday()) < L.balance_days:
        e = pick("balance", lvl + moves.get("balance", 0), L)
        if e:
            blocks.append({"id": e.id, "name": e.name, "sets": 2, "reps": None, "seconds": min(30, 15 + 5 * wk),
                           "rest": 30, "exercise": e})
    work = sum(b["sets"] * ((b["seconds"] or b["reps"] * 4) + b["rest"]) for b in blocks) / 60
    out.update(title="Strength " + ("A" if patterns == STRENGTH_A else "B"), blocks=blocks, warm_up=WARM_UP,
               cool_down=COOL_DOWN, minutes=round(10 + work + finisher), finisher=finisher,
               left_out=left_out)
    return out


def week(state: dict, health: dict, steps: list[int], L: Limits, any_day: date) -> list[dict]:
    monday = _monday(any_day)
    days = [day(state, health, steps, L, monday + timedelta(days=i)) for i in range(7)]
    if L.balance_days:  # the 3rd balance day falls on an aerobic day when there are only 2 strength days
        have = sum(1 for d in days if any(b["exercise"].balance and b["seconds"] for b in d.get("blocks", [])))
        for d in days:
            if have >= L.balance_days:
                break
            if d["kind"] in "CL":
                e = pick("balance", 0, L)
                if e:
                    d["balance"] = {"id": e.id, "name": e.name, "sets": 2, "seconds": 20, "exercise": e}
                    have += 1
    return days


def month(state: dict, on: date) -> list[list[dict]]:
    """The month's calendar, Monday first: each cell its date, what is planned and whether it was done."""
    first = on.replace(day=1)
    last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    kinds = _planned_kinds(state["setup"]["days"])
    start = date.fromisoformat(state["start"])
    log = state.get("log", {})
    cells, d = [], _monday(first)
    while d <= last + timedelta(days=6 - last.weekday()):
        entry = log.get(d.isoformat(), {})
        cells.append({"on": d.isoformat(), "day": d.day, "in_month": d.month == first.month, "kind": kinds.get(d.weekday(), "R"),
                      "started": d >= start, "done": bool(entry.get("done")), "skipped": entry.get("done") is False,
                      "today": d == date.today()})
        d += timedelta(days=1)
    return [cells[i:i + 7] for i in range(0, len(cells), 7)]


def summary(days: list[dict], L: Limits) -> dict:
    aerobic = sum(d["minutes"] for d in days if d["kind"] in "CL") + sum(d.get("finisher", 0) for d in days)
    return {"aerobic": aerobic, "strength_days": sum(1 for d in days if d["kind"] == "S"),
            "balance_days": sum(1 for d in days if d.get("balance") or any(b["exercise"].balance and b["seconds"]
                                                                              for b in d.get("blocks", []))),
            "week_target": days[0]["aerobic_week"] if days else 0}


def log_session(state: dict, on: str, done: bool, rpe: int | None, feedback: dict[str, str], minutes: int | None) -> dict:
    """What the person says about a day: done or not, how hard (0-10), and each exercise easy / ok / hard / hurt."""
    date.fromisoformat(on)
    clean = {k: v for k, v in feedback.items() if v in ("easy", "ok", "hard", "hurt") and k in all_exercises()}
    entry = {"done": done, "rpe": max(0, min(10, rpe)) if rpe is not None else None, "feedback": clean,
             "minutes": max(0, min(300, minutes)) if minutes is not None else None}
    return {**state, "log": {**state.get("log", {}), on: entry}}
