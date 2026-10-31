"""The person's measures, shared with their consent, and what plain arithmetic draws from them.

The rule (CLAUDE.md, Ale 1 Nov 2026): the more the person shares, the more the plan is theirs; judging and clinical
targets stay with the doctor. So this module computes and quotes, it does not diagnose:
- BMI, shown with NHLBI's adult categories (the same 25 and 30 as WHO), never as a verdict on the person;
- energy needs with the Mifflin-St Jeor equation (Am J Clin Nutr, 1990) times an activity factor;
- a weight goal the PERSON chose: how long it takes at the public pace, inside public limits. The limits are not
  ours: about 0.5 to 1 kg a week (CDC), not under 1,200 kcal a day for women or 1,500 for men without a health
  professional (Harvard Health), no goal under BMI 18.5 (NHLBI's "underweight"), and no weight-loss goal for minors
  or in pregnancy or breastfeeding. A calorie number the doctor wrote wins over the estimate.
Weight never pays (reward.py does not read this).
"""
from __future__ import annotations

import math

SOURCES = {
    "bmi": ("NHLBI — Calculate your Body Mass Index", "https://www.nhlbi.nih.gov/health/educational/lose_wt/BMI/bmicalc.htm"),
    "who": ("WHO — Obesity and overweight (fact sheet)", "https://www.who.int/news-room/fact-sheets/detail/obesity-and-overweight"),
    "pace": ("CDC — Losing weight", "https://www.cdc.gov/healthy-weight-growth/losing-weight/index.html"),
    "floor": ("Harvard Health — Calorie counting made easy", "https://www.health.harvard.edu/staying-healthy/calorie-counting-made-easy"),
}
ACTIVITY = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very active": 1.9}
PACE = 0.5            # kg a week: the public pace a goal is estimated at
MAX_PACE = 1.0        # kg a week: the upper end of the public range
FLOOR = {"female": 1200, "male": 1500}   # kcal a day, without a health professional
KCAL_PER_KG = 7700    # energy in a kilogram of body weight, the usual working figure


def bmi(height_cm: float, weight_kg: float) -> float:
    return round(weight_kg / (height_cm / 100) ** 2, 1)


def bmi_category(value: float) -> str:
    """NHLBI's adult categories, word for word."""
    return ("Underweight" if value < 18.5 else "Healthy" if value < 25 else "Overweight" if value < 30 else "Obesity")


def energy(h: dict) -> int | None:
    """Daily energy needs (kcal) to keep today's weight: Mifflin-St Jeor times the activity factor."""
    try:
        base = 10 * h["weight_kg"] + 6.25 * h["height_cm"] - 5 * h["age"] + (5 if h["sex"] == "male" else -161)
        return round(base * ACTIVITY[h["activity"]])
    except (KeyError, TypeError):
        return None


def read(h: dict) -> dict:
    """Everything the page shows from the measures: BMI, energy, and the goal with its estimate and limits."""
    out: dict = {"notes": []}
    if h.get("height_cm") and h.get("weight_kg"):
        out["bmi"] = bmi(h["height_cm"], h["weight_kg"])
        out["bmi_category"] = bmi_category(out["bmi"])
    keep = energy(h)
    out["energy"] = keep
    floor = FLOOR.get(h.get("sex"), 1500)
    # Minors and pregnancy: no calorie number at all (the equation does not fit them); the doctor plans
    if (h.get("age") is not None and h["age"] < 18) or h.get("pregnant"):
        out["target_kcal"] = None
        out["notes"].append("Under 18, or in pregnancy or breastfeeding: no calorie number or weight goal here; "
                            "your doctor plans it.")
        return out
    doctor = h.get("doctor_kcal")
    if doctor and doctor < floor:  # typed by the person: below the general minimum it is not taken on trust
        out["notes"].append(f"{doctor:g} kcal is under the {floor} a day advised without supervision (Harvard Health): "
                            f"the plan uses {floor} until you confirm the number with your doctor.")
        doctor = floor
    elif doctor:
        out["notes"].append(f"Your doctor's number: {doctor:g} kcal a day. It is the one the plan uses.")
    out["target_kcal"] = doctor or keep
    goal = h.get("goal_kg")
    if not goal or not h.get("weight_kg") or not h.get("height_cm"):
        return out
    lose = round(h["weight_kg"] - goal, 1)
    if lose <= 0:
        out["notes"].append("Gaining weight is a plan for your doctor: the app keeps portions at today's needs.")
        return out
    if h.get("age") is None:  # an adult's goal only: unknown age, no goal
        out["notes"].append("Add your age to set a weight goal: goals are for adults only.")
        return out
    lowest = round(18.5 * (h["height_cm"] / 100) ** 2, 1)
    if goal < lowest:
        out["notes"].append(f"A goal under {lowest} kg would be a BMI under 18.5 (NHLBI: underweight): not set here.")
        return out
    pace = min(max(h.get("pace") or PACE, 0.25), MAX_PACE)
    if doctor or keep is None:
        weeks = math.ceil(lose / pace)
        out.update(goal_kg=goal, lose_kg=lose, pace=pace, weeks=weeks)
        return out
    wanted = keep - pace * KCAL_PER_KG / 7
    target = max(round(wanted), floor)
    if target > wanted:   # the floor holds: slower than asked, and the page says why
        pace = round((keep - target) * 7 / KCAL_PER_KG, 2)
        out["notes"].append(f"To stay at or above {floor} kcal a day (Harvard Health), the pace is {pace} kg a week.")
    if pace <= 0:
        out["notes"].append("Your needs are already near the lowest daily calories advised: ask your doctor for a plan.")
        out["target_kcal"] = keep
        return out
    out.update(goal_kg=goal, lose_kg=lose, pace=pace, weeks=math.ceil(lose / pace), target_kcal=target)
    return out


def for_planner(h: dict) -> str:
    """The lines the dietitian gets: the household's energy for the day and what lunch and dinner should carry."""
    r = read(h)
    if not r.get("target_kcal"):
        return ""
    meals = round(r["target_kcal"] * 0.6)
    return (f"ENERGY (from the person's own measures{', with their chosen goal' if r.get('weeks') else ''}): about "
            f"{r['target_kcal']} kcal a day; lunch and dinner together about {meals} kcal for this person: size their "
            f"portions to it. Never state a calorie target to the person; the doctor sets targets.")
