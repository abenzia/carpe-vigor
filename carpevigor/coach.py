"""The coach: the week's movement, its own member of the team.

The coach (a model) writes seven days of movement for this person: the doctor's goals, their activity level, their
steps. Plain code then holds it to the US Physical Activity Guidelines for adults (guidelines.py quotes them): 150 to
300 minutes of moderate activity a week, muscle-strengthening at least 2 days. Each day says its minutes and whether
it strengthens, so the totals are added by code, not claimed by the model; a week outside them goes back once, and
what is still outside is said on the page.

`areas_worked` reads a day's line and names the body areas it works, for the 3D body page: words to areas, no model.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from . import llm

MIN_MINUTES, MAX_MINUTES, MIN_STRENGTH = 150, 300, 2   # US HHS Physical Activity Guidelines, adults


class Day(BaseModel):
    day: str = Field(description="Mon..Sun")
    text: str = Field(description="One line a person can follow: what, how long, how hard ('30-minute brisk walk, then "
                                  "2 sets of 10 wall push-ups'). Never a medical exercise prescription.")
    moderate_minutes: int = Field(description="Minutes of moderate (or brisk) activity in this day's line; 0 for rest")
    strength: bool = Field(description="True if the line includes muscle-strengthening (push-ups, squats, bands...)")


class MovementPlan(BaseModel):
    days: list[Day] = Field(description="7 days, Mon..Sun")


COACH = """You are the coach of a health team. You plan one week of movement for one adult, within the US Physical \
Activity Guidelines: 150 to 300 minutes of moderate activity a week and muscle-strengthening on at least 2 days. Build \
from where the person is (their activity level and recent steps): a gentle start when they move little, progress later. \
Simple things done at home or outdoors, no gym needed. Anything the doctor said comes first. Never diagnose, never \
mention medicines, never promise a result. Each day: one line, its moderate minutes, whether it strengthens."""


def totals(plan: MovementPlan) -> dict:
    minutes = sum(max(d.moderate_minutes, 0) for d in plan.days)
    strength = sum(1 for d in plan.days if d.strength)
    problems = []
    if len(plan.days) != 7:
        problems.append(f"the week has {len(plan.days)} days, not 7")
    if not MIN_MINUTES <= minutes <= MAX_MINUTES:
        problems.append(f"{minutes} moderate minutes in the week: keep between {MIN_MINUTES} and {MAX_MINUTES}")
    if strength < MIN_STRENGTH:
        problems.append(f"{strength} strength days: at least {MIN_STRENGTH}")
    return {"minutes": minutes, "strength_days": strength, "problems": problems, "within": not problems}


def plan_week(goals: list[str], activity: str | None, steps: list[int], extra: str = "") -> tuple[list[str], dict]:
    """Seven movement lines and the coach's report (minutes and strength days, added by code)."""
    where = (f"ACTIVITY LEVEL: {activity or 'not given'}\nRECENT STEPS A DAY: "
             f"{round(sum(steps) / len(steps)) if steps else 'not given'}\n")
    task = f"DOCTOR'S GOALS: {'; '.join(goals)}\n{where}{extra}"
    plan = llm.ask(COACH, task, MovementPlan, tier="mid", temperature=0.3)
    first = totals(plan)
    if first["problems"]:
        plan = llm.ask(COACH, f"{task}\n\nYOUR WEEK\n{plan.model_dump_json()}\n\nFIX: {'; '.join(first['problems'])}",
                       MovementPlan, tier="mid", temperature=0.1)
    report = totals(plan) | {"fixed": bool(first["problems"])}
    return [f"{d.day}: {d.text}" for d in plan.days], report


def _mock_plan(task: str) -> MovementPlan:
    """No model: the demo week's movement lines, their minutes read from the words."""
    import json
    from . import config
    with open(config.DATA / "demo_plan.json", encoding="utf-8") as f:
        lines = json.load(f)["movement"]
    days = []
    for n, line in enumerate(lines[:7]):
        minutes = sum(int(m) for m in re.findall(r"(\d+)[- ]minute", line))
        days.append(Day(day=("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[n], text=line.split(": ", 1)[-1],
                        moderate_minutes=minutes, strength=bool(re.search(r"push-?up|squat|lunge|plank|strength", line, re.I))))
    return MovementPlan(days=days)


llm.mock_answers.setdefault("MovementPlan", _mock_plan)


AREAS = ("legs", "glutes", "core", "chest", "arms", "back", "shoulders")
# words of a movement line -> the areas they work
_WORDS = [
    (r"walk|stroll|hike|stairs|steps|march|jog|run|cycl|bike|swim|danc", ("legs", "glutes")),
    (r"squat|lunge|step-?up|calf|bridge|deadlift|leg", ("legs", "glutes")),
    (r"push-?up|press|plank|dip|chest", ("chest", "arms", "shoulders")),
    (r"plank|crunch|core|abs|sit-?up|bird-?dog|dead-?bug|twist", ("core",)),
    (r"row|pull|superman|back|band", ("back", "arms")),
    (r"swim|yoga|stretch|pilates|tai ?chi|mobility", ("back", "shoulders", "core")),
]


def areas_worked(line: str) -> list[str]:
    found: list[str] = []
    for pattern, areas in _WORDS:
        if re.search(pattern, line or "", re.I):
            found += [a for a in areas if a not in found]
    return [a for a in AREAS if a in found]
