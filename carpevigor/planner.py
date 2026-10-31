"""Screen 2 — the week: seven days of meals for the kitchen device the person has, each with a
"why" line tied to the doctor's goals and an "evidence" line that says what the public source says
on average — never a prediction about this person.

Who writes it: one agent writes the plan (the provider's strong model: Gemini on Vertex, or Nova on Bedrock). Who checks it: the review
board reads every "why" and "evidence" sentence against the fetched sources (review_board.py). A plan
reaches the screen with the board's report attached, approved or sent back. In mock mode the demo
plan is served from `data/demo_plan.json` and the board says it was simulated.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from . import config, llm, review_board, sources
from .profile import Guidance

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Recipe(BaseModel):
    day: str = Field(description="Mon..Sun")
    meal: str = Field(description="lunch or dinner")
    title: str
    ingredients: list[str] = Field(description="Plain grocery names, one per line, e.g. 'chicken breast', 'spinach', 'olive oil'")
    steps: list[str] = Field(description="3-6 steps written for the person's kitchen device, with real settings for that device")
    why: str = Field(description="One sentence tying this dish to the doctor's goals (e.g. 'Low in sodium: herbs instead of salt, because you were told to cut salt')")
    evidence: str = Field(description="One sentence saying what the public source says on average, with the source name in brackets; never a prediction for this person")


class WeekPlan(BaseModel):
    title: str
    summary: str = Field(description="Two sentences: what this week does for the goals, in plain words")
    recipes: list[Recipe] = Field(description="14 recipes: lunch and dinner for each of the 7 days")
    movement: list[str] = Field(description="7 short lines, one per day, of movement a person can do (walk, stairs, light strength); never a medical exercise prescription")


SYSTEM = """You plan one week of lunches and dinners for one person, following the lifestyle goals their doctor gave \
them and the constraints they stated. You write for their kitchen device with real settings (times, temperatures, \
speeds). You never mention medicines, never diagnose, never predict this person's values. Every 'why' line ties the \
dish to a stated goal; every 'evidence' line states only what the given public source says, on average, with the \
source's name in brackets. Simple dishes, common ingredients, nothing exotic."""


def make(guidance: Guidance, device: str) -> tuple[WeekPlan, dict, list[dict]]:
    """The plan, the board's report on its claims, and the sources used."""
    reference, used = sources.reference_for(guidance.topics)
    task = (f"GOALS: {'; '.join(guidance.goals)}\nCONSTRAINTS: {'; '.join(guidance.constraints) or 'none'}\n"
            f"KITCHEN DEVICE: {device}\n\nPUBLIC SOURCES YOU MAY CITE (use only what they say):\n{reference or '(sources not fetched yet)'}")
    plan = llm.ask(SYSTEM, task, WeekPlan, temperature=0.3)
    claims = " ".join(f"{r.why} {r.evidence}" for r in plan.recipes)
    if reference:
        report = review_board.convene(claims, reference, strict=True)
    else:
        report = {"approved": False, "provider": llm.provider(), "reviewers": [], "corrections": [], "set_aside": [],
                  "statements": review_board.statements_of(claims), "note": "Sources not fetched: run `python -m carpevigor.sources fetch`."}
    return plan, report, used


def _mock_plan(task: str) -> WeekPlan:
    with open(config.DATA / "demo_plan.json", encoding="utf-8") as f:
        return WeekPlan.model_validate(json.load(f))


llm.mock_answers.setdefault("WeekPlan", _mock_plan)
