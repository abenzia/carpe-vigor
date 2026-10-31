"""What I ate today: the meals of the plan marked as cooked, and anything else said in a few words ("cacio e pepe",
"a slice of pizza and a beer"), added up for the day.

Nobody weighs what they eat, so the diary asks for a sentence, typed, dictated, or sent from an Apple Watch shortcut
(app.py /api/meal). A model turns the sentence into the ingredients of a typical portion with their raw grams; the
values come from USDA FoodData Central through nutrition.py, never from the model. That is an estimate, and it is
shown as one; a meal of the plan is counted from its own recipe. The diary shows numbers: it sets no calorie target
(the doctor's, if any) and it does not count toward the reward (what is said cannot be checked).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from . import llm, nutrition

PORTIONS = {"small": 0.7, "normal": 1.0, "large": 1.4}   # times a typical portion


class Part(BaseModel):
    name: str = Field(description="A plain food name a food database would use: 'spaghetti', 'pecorino romano', 'beer'")
    grams: float = Field(description="Raw weight in grams in one typical portion (a drink: its millilitres)")


class Breakdown(BaseModel):
    dish: str = Field(description="What was eaten, in a few words, as the person said it; empty if it is not food")
    parts: list[Part] = Field(description="The ingredients of one typical adult portion; empty if it is not food")
    assumed: str = Field(default="", description="One short line on what was assumed: 'a typical restaurant plate, "
                                                 "100 g of dry pasta'")


SPLIT = """You turn what a person says they are eating or drinking into the ingredients of one typical adult portion, \
each with its raw weight in grams, as a food database would name them. Several foods: list them all. A known dish \
(cacio e pepe, carbonara, a cheeseburger): its classic ingredients in usual amounts. Do not comment on health, do not \
judge, do not give advice. If the text is not about food or drink, return an empty dish and no parts."""


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def say(text: str, portion: Literal["small", "normal", "large"] = "normal") -> dict:
    """A sentence -> a diary entry with the values of the portion. Raises ValueError when there is nothing to count."""
    text = text.strip()
    if not text:
        raise ValueError("Say what you are eating, for example: a plate of cacio e pepe.")
    split = llm.ask(SPLIT, f"THE PERSON SAYS: {text}", Breakdown, tier="mid")
    if not split.parts:
        raise ValueError(f'"{text}" does not sound like food or drink: nothing was added.')
    factor = PORTIONS.get(portion, 1.0)
    values = nutrition.count([(p.name, p.grams * factor) for p in split.parts], 1)
    if values is None:
        raise ValueError("The food database is not on this machine: run python -m carpevigor.nutrition fetch.")
    return {"at": _now().isoformat(timespec="minutes"), "said": text, "dish": split.dish or text, "portion": portion,
            "assumed": split.assumed, "estimate": True, "nutrition": values.model_dump()}


def from_plan(recipe: dict) -> dict | None:
    """A meal of the plan marked as cooked: one serving of its own recipe, not an estimate."""
    if not recipe.get("nutrition"):
        return None
    return {"at": _now().isoformat(timespec="minutes"), "said": "", "dish": recipe["title"], "portion": "one serving",
            "assumed": "", "estimate": False, "plan": f"{recipe['day']} {recipe['meal']}", "nutrition": recipe["nutrition"]}


def day(entries: list[dict], on: str | None = None) -> dict:
    """The entries of one day (YYYY-MM-DD, today by default) and their total."""
    on = on or _now().date().isoformat()
    todays = [e for e in entries if e["at"][:10] == on]
    keys = ("kcal", "protein_g", "fat_g", "sat_fat_g", "carbs_g", "fiber_g", "sugars_g", "sodium_mg")
    total = {k: round(sum(e["nutrition"].get(k, 0) for e in todays), 1) for k in keys}
    return {"on": on, "entries": todays, "total": total, "estimated": any(e["estimate"] for e in todays),
            "sodium_at_most": any(e["nutrition"].get("sodium_at_most") for e in todays)}


def spoken(entry: dict, today: dict) -> str:
    """The answer a watch reads aloud."""
    n, t = entry["nutrition"], today["total"]
    about = "about " if entry["estimate"] else ""
    return (f"{entry['dish']}: {about}{round(n['kcal'])} calories, {round(n['protein_g'])} grams of protein, "
            f"{round(n['sodium_mg'])} milligrams of sodium. Today so far: {round(t['kcal'])} calories.")


def _mock_split(task: str) -> Breakdown:
    """No model: the sentence as one food of 300 g, which the database may or may not know."""
    said = task.split("THE PERSON SAYS:", 1)[-1].strip()
    return Breakdown(dish=said, parts=[Part(name=said, grams=300)], assumed="no model: one typical 300 g portion")


llm.mock_answers.setdefault("Breakdown", _mock_split)
