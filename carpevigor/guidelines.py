"""The public numbers a week is planned around, each with the source that states it and the words it states it in.

Models write the plan; these numbers are not theirs to choose. Each entry quotes its source word for word, and
`check()` finds that quote in the fetched text, so a number here is never one nobody can point to. Where the sources
disagree (saturated fat: WHO under 10% of calories, MedlinePlus under 7%), both are kept and shown: the person's
doctor picks, not the app.

They are numbers for people in general, never a target for this person: that one is set by their doctor (checkup.py).

    python -m carpevigor.guidelines      # is every quote still in the fetched text?
"""
from __future__ import annotations

import re
import sys

from . import sources

# A MedlinePlus library page (sources.py library), not a topic source: the only one of ours that gives adults' sleep
# in hours as a plain recommendation.
_SLEEP_PAGE = {"id": "mlp-1598", "name": "MedlinePlus — How to Prevent Heart Disease",
               "url": "https://medlineplus.gov/howtopreventheartdisease.html"}

# topic: the plan topic it belongs to (sources.TOPICS), or None for every week
NUMBERS = [
    {"key": "sodium", "topic": "blood_pressure", "says": "Under 2,000 mg of sodium a day (less than 5 g of salt)",
     "source": "who-sodium", "quote": "less than 2000 mg/day sodium (equivalent to < 5 g/day salt"},
    {"key": "sodium", "topic": "blood_pressure", "says": "No more than 2,300 mg of sodium a day (about 1 teaspoon of salt)",
     "source": "medlineplus-chol", "quote": "no more than 2,300 milligrams (about 1 teaspoon of salt) a day"},
    {"key": "saturated_fat", "topic": "cholesterol", "says": "No more than 10% of calories from saturated fat",
     "source": "who-diet", "quote": "No more than 10% of total energy intake should come from saturated fat"},
    {"key": "saturated_fat", "topic": "cholesterol", "says": "Less than 7% of calories from saturated fat",
     "source": "medlineplus-chol", "quote": "less than 7% of your daily calories should come from saturated fat"},
    {"key": "free_sugars", "topic": "sugar", "says": "Free sugars under 10% of calories (about 50 g on 2,000 calories)",
     "source": "who-sugar", "quote": "free sugars should be limited to less than 10% of total daily energy intake"},
    {"key": "fruit_veg", "topic": None, "says": "At least 400 g of fruit and vegetables a day",
     "source": "who-diet", "quote": "at least 400 grams of fruits and vegetables per day"},
    {"key": "fiber", "topic": "fiber", "says": "At least 25 g of fiber a day",
     "source": "who-diet", "quote": "at least 25 grams of naturally-occurring dietary fibre"},
    {"key": "aerobic", "topic": None, "says": "150 to 300 minutes of moderate activity a week, like brisk walking",
     "source": "hhs-pag-top10", "quote": "at least 150 to 300 minutes of moderate-intensity aerobic activity"},
    {"key": "strength", "topic": None, "says": "Muscle-strengthening activity at least 2 days a week",
     "source": "hhs-pag-top10", "quote": "muscle-strengthening activity, like lifting weights or doing push-ups, at least 2 days each week"},
    {"key": "sleep", "topic": None, "says": "7 to 9 hours of sleep a night for adults",
     "source": "mlp-1598", "quote": "try to get 7 to 9 hours of sleep per night"},
]


def source_of(source_id: str) -> dict:
    for topic in sources.TOPICS.values():
        for src in topic["sources"]:
            if src["id"] == source_id:
                return src
    if source_id == _SLEEP_PAGE["id"]:
        return _SLEEP_PAGE
    raise KeyError(source_id)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def found(entry: dict) -> bool | None:
    """True if the quote is in the fetched text, False if the text is there and the quote is not, None if not fetched."""
    text = sources.text_of(entry["source"])
    return None if text is None else _flat(entry["quote"]) in _flat(text)


def for_week(topic_keys: list[str]) -> list[dict]:
    """The numbers for this week's topics plus the ones for every week, each with its source and whether its quote
    was found. A number whose source text says otherwise (False) is left out: it is not shown, nor given to the planner."""
    out = []
    for e in NUMBERS:
        if e["topic"] is None or e["topic"] in topic_keys:
            ok = found(e)
            if ok is not False:
                out.append({**e, "src": source_of(e["source"]), "checked": ok is True})
    return out


def as_task(entries: list[dict]) -> str:
    """The numbers as lines for the planner's task: the plan's evidence lines cite these, not numbers of its own."""
    return "\n".join(f"- {e['says']} [{e['src']['name']}]" for e in entries)


def check() -> int:
    bad = 0
    for e in NUMBERS:
        ok = found(e)
        mark = "ok" if ok else ("NOT FETCHED" if ok is None else "QUOTE NOT FOUND")
        bad += ok is False
        print(f"{mark:16} {e['key']:14} {e['source']:18} {e['says']}")
    return bad


if __name__ == "__main__":
    sys.exit(1 if check() else 0)
