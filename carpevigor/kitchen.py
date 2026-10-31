"""The kitchen devices a week can be written for, and the checks a recipe must pass on the person's own device.

A model writes the recipes; whether a step can be done on the machine the person has is not its call. The limits here
come from the makers' published specs (Vorwerk support pages, Oct 2026), and `check()` reads every step against them:
a Thermomix TM31 cannot be set to 120 °C, a TM7 steams in its steaming mode, not at a "Varoma" temperature. The same
check holds the plan to its own word on portions and leftovers: a dinner that feeds tomorrow's lunch is cooked for it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    name: str
    rules: str                    # what the planner is told about this device
    max_c: int | None = None      # highest temperature a step may set by hand; None = not checked
    mode_c: int | None = None     # higher temperature reachable only in a named mode (TM6, TM7)
    varoma_setting: bool = True   # whether "Varoma" is a temperature setting on this machine


_BIMBY = ("Settings are written as time/temperature/speed, e.g. '5 min/100°C/speed 1', with 'Reverse' and "
          "'speed spoon' for gentle stirring and the butterfly whisk where needed. Never fill the bowl past its "
          "capacity. ")

# The first is the form's default and the device the demo week (data/demo_plan.json) is written for.
DEVICES = [
    Device("Thermomix / Bimby TM6",
           _BIMBY + "TM6: bowl 2.2 litres. Manual temperatures up to 120°C, or 'Varoma' for steaming; up to 160°C only "
           "in 'Browning mode', named as such.", max_c=120, mode_c=160),
    Device("Thermomix / Bimby TM7",
           _BIMBY + "TM7: bowl 2.2 litres. Manual temperatures up to 120°C; up to 160°C only inside its high-temperature "
           "modes, named as 'Browning mode'. Steaming uses the 'Steaming mode' (maximum speed 5), never a temperature "
           "called 'Varoma': write e.g. 'Steaming mode 20 min/speed 1'.",
           max_c=120, mode_c=160, varoma_setting=False),
    Device("Thermomix / Bimby TM5",
           _BIMBY + "TM5: bowl 2.2 litres. Temperatures up to 120°C, or 'Varoma' for steaming. No browning mode.", max_c=120),
    Device("Thermomix / Bimby TM31",
           _BIMBY + "TM31: bowl 2.0 litres. Temperatures up to 100°C only: there is no 120°C; to sauté or steam use "
           "'Varoma' as the temperature. No browning mode.", max_c=100),
    Device("Instant Pot", "Electric pressure cooker: Sauté, Pressure Cook (High/Low) with minutes and natural or quick "
           "release, Steam, Slow Cook."),
    Device("Air fryer", "Air fryer: temperatures in °C and minutes, shake or turn halfway; a pan or stovetop only when "
           "the step cannot be done in the basket."),
    Device("Oven and stovetop", "Oven (°C, minutes, which shelf) and stovetop (low/medium/high heat, minutes)."),
    Device("Microwave only", "Microwave only: power in watts and minutes, a microwave-safe covered dish, stir halfway. "
           "No oven, no stovetop."),
]
NAMES = [d.name for d in DEVICES]
# Plans made before the Thermomix models were told apart said only this
_OLD_NAMES = {"Thermomix / Bimby": "Thermomix / Bimby TM6"}


def device(name: str) -> Device:
    name = _OLD_NAMES.get(name, name)
    return next((d for d in DEVICES if d.name == name), Device(name, f"Cooking with: {name}."))


DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# A machine setting ("12 min/120°C/speed 1"), not any temperature: a Bimby week may still bake a frittata at 180°C
_TEMP = re.compile(r"(?:min|sec)\.?\s*/\s*(\d{2,3})\s*°\s*C", re.I)
_VAROMA_SETTING = re.compile(r"/\s*varoma\s*/|varoma\s*/\s*speed", re.I)
_MODE = re.compile(r"browning|high[- ]temperature", re.I)
# "as per Monday's quinoa", "same as Tue lunch", "see Wednesday": a recipe has to be cookable on its own
_ELSEWHERE = re.compile(r"\b(?:as (?:per|in|for|on)|same as|see|like)\b[^.;]*\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\b"
                        r"|\b(?:mon|tues|wednes|thurs|fri|satur|sun)day's\b", re.I)


def _servings(n: int) -> str:
    return f"{n} serving" + ("" if n == 1 else "s")


def meal_key(r: dict) -> str:
    return f"{r.get('day', '')} {r.get('meal', '')}".strip().lower()


def check(recipes: list[dict], dev: Device, people: int) -> dict[int, list[str]]:
    """Recipe index → what is wrong with it, in words a cook (or the model asked to fix it) can act on."""
    problems: dict[int, list[str]] = {}
    by_meal = {meal_key(r): r for r in recipes}
    for i, r in enumerate(recipes):
        out = []
        for n, step in enumerate(r.get("steps", []), 1):
            for t in map(int, _TEMP.findall(step)):
                if dev.max_c is None or t <= dev.max_c:
                    continue
                if dev.mode_c and t <= dev.mode_c and _MODE.search(step):
                    continue
                out.append(f"Step {n} sets {t}°C: the {dev.name} goes up to {dev.max_c}°C"
                           + (f" (up to {dev.mode_c}°C only in Browning mode, named in the step)" if dev.mode_c else ""))
            if not dev.varoma_setting and _VAROMA_SETTING.search(step):
                out.append(f"Step {n} sets 'Varoma' as a temperature: the {dev.name} steams in Steaming mode")
            if _ELSEWHERE.search(step):
                out.append(f"Step {n} refers to another recipe: write the times and amounts here")
        servings = r.get("servings") or 0
        feeds = (r.get("leftovers_for") or "").strip().lower()
        uses = (r.get("from_leftovers") or "").strip().lower()
        if feeds:
            other = by_meal.get(feeds)
            if not other or (other.get("from_leftovers") or "").strip().lower() != meal_key(r):
                out.append(f"It says it also makes {r['leftovers_for']}, but that meal is not cooked from it")
            if servings < 2 * people:
                out.append(f"It cooks {_servings(servings)} but feeds {people} now and {people} at {r['leftovers_for']}: "
                           f"cook {2 * people} servings, with the amounts for them")
        elif servings and servings < people:
            out.append(f"It cooks {_servings(servings)} for {people} people")
        if uses:
            other = by_meal.get(uses)
            if not other or (other.get("leftovers_for") or "").strip().lower() != meal_key(r):
                out.append(f"It is made from the leftovers of {r['from_leftovers']}, but that meal does not cook extra for it")
        elif any("leftover" in str(x).lower() for x in r.get("ingredients", [])):
            out.append("It uses leftovers without saying which meal cooks them")
        for b in r.get("buy", []):
            if isinstance(b, dict) and not b.get("amount"):
                out.append(f"It buys {b.get('name')} without saying how much")
        if out:
            problems[i] = out
    return problems
