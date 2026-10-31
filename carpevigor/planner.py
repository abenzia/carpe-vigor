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
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

from . import config, guidelines, kitchen, llm, rag, review_board, sources
from .catalog import Catalog
from .profile import Guidance

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Buy(BaseModel):
    name: str = Field(description="A name copied EXACTLY from the STORE list")
    amount: float = Field(description="How much this dish uses, for all its servings")
    unit: Literal["g", "ml", "piece"] = Field(description="g, ml, or piece (eggs, lemons, avocados)")


class Recipe(BaseModel):
    day: str = Field(description="Mon..Sun")
    meal: str = Field(description="lunch or dinner")
    title: str
    servings: int = Field(description="How many servings this dish cooks: the number of people, or twice that when it "
                                      "also makes another meal (leftovers_for)")
    leftovers_for: str = Field(default="", description="The meal this dish also cooks for, as 'Tue lunch', or empty")
    from_leftovers: str = Field(default="", description="The meal whose extra servings this dish is made from, as "
                                                        "'Mon dinner', or empty")
    ingredients: list[str] = Field(description="Each with its amount for all the servings, e.g. '300 g chicken breast', "
                                               "'1 tbsp olive oil'")
    buy: list[Buy] = Field(default_factory=list,
                           description="What to buy for this dish, with the amount it uses. Leave out water and leftovers. "
                                       "An ingredient the store does not sell is simply not listed here.")
    steps: list[str] = Field(description="3-6 steps written for the person's kitchen device, with real settings for that "
                                         "device and the amounts; complete on their own, never 'as in Monday's recipe'")
    why: str = Field(description="One sentence on what is IN this dish that fits the goals (e.g. 'No added salt: herbs and "
                                 "lemon instead'). Never an effect on health or weight, never 'you' or 'your'.")
    evidence: str = Field(description="One complete sentence saying only what the public source says, 'on average' when it "
                                      "speaks of people in general, with the source name in brackets; never a prediction for this person")
    removed: list[str] = Field(default_factory=list, description="Always empty: filled by the review board")
    kitchen_flags: list[str] = Field(default_factory=list, description="Always empty: filled by the kitchen check")


class WeekPlan(BaseModel):
    title: str
    summary: str = Field(description="Two sentences: what this week does for the goals, in plain words")
    recipes: list[Recipe] = Field(description="14 recipes: lunch and dinner for each of the 7 days")
    movement: list[str] = Field(description="7 short lines, one per day, of movement a person can do (walk, stairs, light strength); never a medical exercise prescription")


SYSTEM = """You plan one week of lunches and dinners for a household, following the lifestyle goals the person's \
doctor gave them and the constraints they stated. You write for their kitchen device with its real settings (times, \
temperatures, speeds), within the device rules you are given. Each recipe can be cooked on its own: amounts in grams \
or pieces for all its servings, every time and setting written out, never 'as in Monday's recipe'. Lunch and dinner \
are both full meals. A dinner may cook extra for the next day's lunch: then it cooks twice the servings, says so in \
leftovers_for, and that lunch names it in from_leftovers. You never mention medicines, never diagnose, never predict \
this person's values. Every 'why' line says what is in the dish that fits a stated goal (no added salt, vegetables, \
whole grains, fish) and never claims what the dish will do for the person's health or weight. Every 'evidence' line is \
one complete sentence stating only what the given public source says, on average, with the source's name in brackets. \
Simple dishes, common ingredients, nothing exotic."""

FIX_RECIPES = """You fix recipes of a week's meal plan that a check found wrong for the person's kitchen device or for \
the plan's own portions. For each recipe you get its index, the recipe and what is wrong. Return the whole recipe \
corrected, keeping its day, meal, idea and its why and evidence lines unchanged unless the dish itself changed. Follow \
the device rules exactly. Each recipe is complete on its own, with amounts for all its servings."""

REWRITE = """You fix sentences of a meal plan that its review board sent back. For each sentence you get its id, the \
text and what the board said. A 'why' sentence says only what is in the dish (no added salt, vegetables, whole grains), \
never an effect on health or weight, never 'you' or 'your'. An 'evidence' sentence says only what the given source \
says, as one complete sentence, 'on average' when it speaks of people in general, with the source name in brackets. \
Never mention medicines, never predict this person's values. Return one rewrite per id."""

FIELDS = ("why", "evidence")
# A correction that quotes only a citation ("[WHO — Healthy diet]") says nothing about one sentence: traced, it would
# take down every sentence citing that source.
CITATION_ONLY = re.compile(r"\[[^\]]*\]\.?")


class Rewrite(BaseModel):
    id: str = Field(description="The id you were given, e.g. 'r3.why'")
    text: str = Field(description="The corrected sentence")


class Rewrites(BaseModel):
    rewrites: list[Rewrite]


class FixedRecipe(BaseModel):
    index: int = Field(description="The index you were given")
    recipe: Recipe


class FixedRecipes(BaseModel):
    recipes: list[FixedRecipe]


def make(guidance: Guidance, device: str, people: int = 1) -> tuple[WeekPlan, dict, list[dict]]:
    """The plan, the board's report on its claims, and the sources used."""
    reference, used = sources.reference_for(guidance.topics)
    dev = kitchen.device(device)
    # The planner picks the products; plain code (cart_agent) prices them and keeps the cart under budget.
    # Junk (sweets, snacks, cured meat, butter) is not offered: the plan never buys what lowers the person's reward
    catalog = Catalog.load()
    store = "\n".join(sorted(i.name for i in catalog.items.values() if catalog.kind(i.sku) != "unhealthy"))
    task = (f"GOALS: {'; '.join(guidance.goals)}\nCONSTRAINTS: {'; '.join(guidance.constraints) or 'none'}\n"
            f"COOKING FOR: {people} {'person' if people == 1 else 'people'}\n"
            f"KITCHEN DEVICE: {dev.name}\nDEVICE RULES: {dev.rules}\n\n"
            f"STORE (cook mostly with what it sells; copy these names into 'buy'):\n{store}\n\n"
            f"PUBLIC NUMBERS FOR PEOPLE IN GENERAL (plan within them; cite these, never numbers of your own):\n"
            f"{guidelines.as_task(guidelines.for_week(guidance.topics))}\n\n"
            f"PUBLIC SOURCES YOU MAY CITE (use only what they say):\n{reference or '(sources not fetched yet)'}")
    plan = llm.ask(SYSTEM, task, WeekPlan, temperature=0.3)
    # Before the board reads a word: the recipes must be cookable on this device and keep their own portions
    kitchen_report = fix_recipes(plan, dev, people)
    claims = " ".join(f"{r.why} {r.evidence}" for r in plan.recipes)
    if reference:
        # 'why' describes the dish (no source speaks of this dish): safety and clarity read it; the fact jurors rule on
        # the 'evidence' lines, the health claims, against the sources.
        facts = " ".join(r.evidence for r in plan.recipes)
        board_reference, retrieval = rag.reference(review_board.statements_of(facts), guidance.topics)
        report = review_board.convene(claims, board_reference, strict=True, facts=facts)
        report["retrieval"] = retrieval
        if not report["approved"]:
            report = revise(plan, report, reference, guidance.topics)
    else:
        report = {"approved": False, "provider": llm.provider(), "reviewers": [], "corrections": [], "set_aside": [],
                  "statements": review_board.statements_of(claims), "note": "Sources not fetched: run `python -m carpevigor.sources fetch`."}
    report["kitchen"] = kitchen_report
    return plan, report, used


def fix_recipes(plan: WeekPlan, dev: kitchen.Device, people: int) -> dict:
    """One round of fixes: the recipes the kitchen check finds wrong go back to the model, whole, with what is wrong;
    the check reads them again. What is still wrong stays on the recipe as a flag the person sees: never hidden."""
    def problems() -> dict[int, list[str]]:
        return kitchen.check([r.model_dump() for r in plan.recipes], dev, people)
    first = problems()
    if first:
        asked = "\n\n".join(f"INDEX {i}\n{plan.recipes[i].model_dump_json(exclude={'removed', 'kitchen_flags'})}\n"
                            f"WRONG: " + "; ".join(p) for i, p in first.items())
        fixed = llm.ask(FIX_RECIPES, f"COOKING FOR: {people}\nKITCHEN DEVICE: {dev.name}\nDEVICE RULES: {dev.rules}\n\n"
                                     f"RECIPES TO FIX\n{asked}", FixedRecipes, temperature=0.1)
        for f in fixed.recipes:
            if f.index in first:
                plan.recipes[f.index] = f.recipe.model_copy(update={"removed": [], "kitchen_flags": []})
    still = problems() if first else {}
    for i, p in still.items():
        plan.recipes[i].kitchen_flags = p
    return {"device": dev.name, "people": people, "found": sum(map(len, first.values())), "recipes_fixed": len(first),
            "still": sum(map(len, still.values()))}


def _text(plan: WeekPlan, fid: str) -> str:
    i, field = fid[1:].split(".")
    return getattr(plan.recipes[int(i)], field)


def flagged(plan: WeekPlan, corrections: list[dict], among: set[str] | None = None) -> dict[str, list[dict]]:
    """Which plan sentences (id 'r<recipe>.<why|evidence>') the board's corrections point at. A juror quotes a whole
    statement, a safety or clarity reviewer a few words: either way the quote is found inside the sentence (or, when the
    board's sentence split ran across the two lines, the sentence inside the quote)."""
    out: dict[str, list[dict]] = {}
    for i in range(len(plan.recipes)):
        for field in FIELDS:
            fid = f"r{i}.{field}"
            text = _text(plan, fid).strip()
            if not text or (among is not None and fid not in among):
                continue
            hits = [c for c in corrections if c["says"].strip() and not CITATION_ONLY.fullmatch(c["says"].strip())
                    and (c["says"].strip() in text or text in c["says"])]
            if hits:
                out[fid] = hits
    return out


def revise(plan: WeekPlan, report: dict, reference: str, topics: list[str] | None = None) -> dict:
    """One round of corrections: the sentences the board sent back are rewritten, and the same board reads the
    rewrites. What it sends back again is removed: nothing the board rejected reaches the screen. The first round's
    report stays the one shown, with `revision` saying what happened after it."""
    started = time.time()
    first = flagged(plan, report["corrections"])
    if not first:
        return report  # the corrections could not be traced to a sentence: shown as sent back, nothing hidden
    asked = "\n\n".join(f"{fid}: {_text(plan, fid)}\nBOARD: " + " | ".join(f"{c['why']} Should be: {c['should_be']}" for c in cs)
                        for fid, cs in first.items())
    fixed = llm.ask(REWRITE, f"SENTENCES TO FIX\n{asked}\n\nPUBLIC SOURCES\n{reference}", Rewrites, temperature=0.1)
    for rw in fixed.rewrites:
        if rw.id in first and rw.text.strip():
            i, field = rw.id[1:].split(".")
            setattr(plan.recipes[int(i)], field, rw.text.strip())
    facts = " ".join(_text(plan, fid) for fid in first if fid.endswith(".evidence"))
    if topics:  # the rewritten claims are new: retrieve their own passages
        reference, _ = rag.reference(review_board.statements_of(facts), topics)
    second = review_board.convene(" ".join(_text(plan, fid) for fid in first), reference, strict=True, facts=facts)
    still = flagged(plan, second["corrections"], among=set(first))
    for fid in still:
        i, field = fid[1:].split(".")
        setattr(plan.recipes[int(i)], field, "")
        plan.recipes[int(i)].removed.append(field)
    # Approved only if the second reading was complete and every one of its rejections (counted once, however many
    # sentences it matched) was traced to a sentence that is now removed.
    removed = {id(c) for cs in still.values() for c in cs}
    resolved = all(id(c) in removed for c in second["corrections"])
    complete = not any(r.get("absent") for r in second["reviewers"])
    return {**report, "approved": complete and (second["approved"] or resolved),
            "revision": {"rewritten": len(first), "removed": len(still), "approved": second["approved"],
                         "seconds": round(time.time() - started, 1), "reviewers": second["reviewers"]}}


def _mock_plan(task: str) -> WeekPlan:
    with open(config.DATA / "demo_plan.json", encoding="utf-8") as f:
        return WeekPlan.model_validate(json.load(f))


llm.mock_answers.setdefault("WeekPlan", _mock_plan)
# No model, no fixes: what the kitchen check finds stays on the recipe as a flag
llm.mock_answers.setdefault("FixedRecipes", lambda task: FixedRecipes(recipes=[]))
