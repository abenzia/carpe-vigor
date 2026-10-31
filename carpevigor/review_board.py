"""The review board, from Carpe Class, with a new job: health claims instead of lessons.

Nothing about the person's health reaches the screen before five reviewers have read it. Three fact
jurors, each a different model, rule on every written statement against the named public source
(MedlinePlus, WHO, NHS, AHA — sources.py); a statement is corrected only when at least two agree, so
one model's slip does not become a correction. A safety reviewer blocks anything that reads as a
diagnosis, a therapy, or a promise about the person's own values. A clarity reviewer asks for plain
words. None sees another's opinion.

The reviewers are language models reading sources: they are not health professionals and they do
not replace the person's doctor. In the story, the doctor is the board's chair; the board sends to
them whatever is not lifestyle.

Carried over from carpe-class/servizio/review_board.py (Amazon Developer Hackathon entry), minus
Bee and the TV, plus the two new reviewer roles.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from . import config, llm

QUORUM = 2
AT_ONCE = 6


class Ruling(BaseModel):
    n: int = Field(description="Number of the statement, as numbered in the list you were given")
    finding: Literal["supported", "contradicted", "not_in_reference"] = Field(
        description="supported: the source says the same; contradicted: the source says otherwise; "
                    "not_in_reference: the source does not speak of it")
    reference_says: str = Field(description="What the source says on this point, in one short sentence; empty if it does not speak of it")


class Rulings(BaseModel):
    rulings: list[Ruling] = Field(description="One ruling for EVERY numbered statement, in order, none skipped")


class Correction(BaseModel):
    n: int = Field(description="Number of the statement with the problem")
    says: str = Field(description="The words that are wrong, unsafe or unclear, quoted")
    should_be: str = Field(description="What it should say instead, or 'Remove it'")
    why: str = Field(description="One sentence: the reason")


class Verdict(BaseModel):
    approved: bool = Field(description="True if the text can go to the person as it is")
    checks: list[str] = Field(description="Exactly three short lines, each stating one thing you verified and what you found")
    corrections: list[Correction] = Field(description="Problems that must be fixed; empty if there are none")


COMMON = """You sit on the review board of a health and lifestyle text produced automatically for one person. \
Nobody has checked it yet; you are the check. Report only what you actually find in the material you are \
given: do not invent problems to look thorough, and do not approve what you could not verify."""

FACTS = COMMON + """

You are a fact juror. You are given numbered statements and the text of a named public health source. Rule \
on every statement, one by one: look up what the source says, then decide. Every word counts: a statement \
with one wrong number, direction or condition is contradicted. A simplification or a different wording of \
the same fact is supported. A statement that claims more than the source does (a cause, a cure, a figure, a \
"always" or "never" that the source does not state) is not_in_reference, however reasonable it sounds."""

JURORS = [
    {"id": "facts1", "name": "Fact juror", "tier": "strong", "question": "Does the source say this?"},
    {"id": "facts2", "name": "Fact juror", "tier": "mid", "question": "Does the source say this?"},
    {"id": "facts3", "name": "Fact juror", "tier": "light", "question": "Does the source say this?"},
]
EXPERTS = [
    {"id": "safety", "name": "Safety reviewer", "tier": "strong",
     "question": "Is anything here a diagnosis, a therapy or a promise?",
     "role": "You are the safety reviewer. The text may only talk about food, movement, sleep and habits in general terms "
             "and about what public sources say happens on average. Any sentence that names or implies a diagnosis for "
             "this person, recommends, changes or stops a medicine, supplement or treatment, gives a personal prediction "
             "of their values ('your pressure will be…'), or discourages seeing a doctor is a correction: quote it and say "
             "'Remove it' or give the general wording that would be acceptable. Population-level evidence with a source "
             "and the word 'on average' is acceptable. Each of your three checks is one plain sentence."},
    {"id": "clarity", "name": "Clarity reviewer", "tier": "strong",
     "question": "Would a person understand it at a glance?",
     "role": "You are the clarity reviewer. Judge whether an ordinary person, not a clinician, understands each line at "
             "first reading: plain words, one idea per sentence, numbers with their units, no jargon left unexplained. "
             "Do not judge the facts. Only something that would mislead or lose the reader is a correction. Each of your "
             "three checks is one plain sentence."},
]
REVIEWERS = JURORS + EXPERTS


def statements_of(text: str) -> list[str]:
    """The sentences of a text that make a claim: longer than a scrap, with at least one letter. No cut after "e.g.",
    "i.e.", "etc." or "approx.", nor before a "[Source]" that follows the full stop: a citation alone is not a claim,
    and a juror rejecting it would take down every sentence that cites that source."""
    parts = re.split(r"(?<=[.!?])(?<!e\.g\.)(?<!i\.e\.)(?<!etc\.)(?<!approx\.)\s+(?!\[)|(?<=\])\s+(?=[A-Z])", text.strip())
    return [s.strip() for s in parts if len(s.strip()) > 3 and re.search(r"[^\W\d_]", s)]


def rule(juror: dict, statements: list[str], reference: str) -> dict[int, Ruling]:
    wanted = set(range(1, len(statements) + 1))
    numbered = "\n".join(f"{n}. {s}" for n, s in enumerate(statements, 1))
    task = f"STATEMENTS TO RULE ON\n{numbered}\n\n{reference}"
    found: dict[int, Ruling] = {}
    for attempt in range(2):
        missing = sorted(wanted - set(found))
        if not missing:
            break
        ask = task if attempt == 0 else task + f"\n\nRule on statements {', '.join(map(str, missing))}: you skipped them."
        try:
            answer = llm.ask(FACTS, ask, Rulings, tier=juror["tier"])
        except Exception:
            continue
        found.update({r.n: r for r in answer.rulings if r.n in wanted and r.n not in found})
    return found


def jury(statements: list[str], reference: str, pool: ThreadPoolExecutor, strict: bool) -> tuple[list[dict], list[dict], list[dict], int]:
    faults = ("contradicted", "not_in_reference") if strict else ("contradicted",)
    jobs = {j["id"]: pool.submit(rule, j, statements, reference) for j in JURORS}
    ruled = {jid: job.result() for jid, job in jobs.items()}
    total = len(statements)
    cards, upheld, set_aside = [], [], []
    for juror in JURORS:
        mine = list(ruled[juror["id"]].values())
        count = lambda f: sum(1 for r in mine if r.finding == f)
        cards.append({
            "id": juror["id"], "name": juror["name"], "maker": llm.model_for(juror["tier"]), "question": juror["question"],
            "absent": len(mine) < total, "approved": len(mine) == total and not any(r.finding in faults for r in mine),
            "checks": [f"Ruled on {len(mine)} of {total} statements",
                       f"{count('supported')} match the source, {count('not_in_reference')} are not covered by it",
                       f"{count('contradicted')} contradict the source"],
            "corrections": [],
        })
    present = sum(1 for c in cards if not c["absent"])
    for n, text in enumerate(statements, 1):
        against = [(j, ruled[j["id"]][n]) for j in JURORS if n in ruled[j["id"]] and ruled[j["id"]][n].finding in faults]
        if not against:
            continue
        unsaid = all(r.finding == "not_in_reference" for _, r in against)
        entry = {"n": n, "says": text,
                 "should_be": "Remove it, or say only what the source says" if unsaid else
                              next(r.reference_says for _, r in against if r.finding == "contradicted"),
                 "why": "The source does not say this." if unsaid else "The source says otherwise.",
                 "raised_by": [llm.model_for(j["tier"]) for j, _ in against], "votes": f"{len(against)} of {len(JURORS)} fact jurors"}
        for j, _ in against:
            next(c for c in cards if c["id"] == j["id"])["corrections"].append({k: entry[k] for k in ("n", "says", "should_be", "why")})
        (upheld if len(against) >= QUORUM else set_aside).append(entry)
    return cards, upheld, set_aside, present


def expert(reviewer: dict, text: str) -> dict:
    card = {k: reviewer[k] for k in ("id", "name", "question")} | {"maker": llm.model_for(reviewer["tier"])}
    try:
        verdict = llm.ask(COMMON + "\n\n" + reviewer["role"], text, Verdict, tier=reviewer["tier"])
    except Exception as error:
        return {**card, "absent": True, "approved": False, "checks": [], "corrections": [], "error": f"{type(error).__name__}: {str(error)[:180]}"}
    corrections = [c.model_dump() for c in verdict.corrections if c.says.strip() != c.should_be.strip()]
    return {**card, "absent": False, "approved": verdict.approved and not corrections, "checks": verdict.checks[:3], "corrections": corrections}


def convene(text: str, reference: str, strict: bool = True, facts: str | None = None) -> dict:
    """Review `text` against `reference` (the source text, headed by its name and URL). Returns the board's report.
    `facts`: the part of `text` that claims something about health, the only part the fact jurors can check against a
    source (a line describing a dish is checked by the safety and clarity reviewers, who always read all of `text`)."""
    started = time.time()
    statements = statements_of(text)
    numbered = "\n".join(f"{n}. {s}" for n, s in enumerate(statements, 1))
    claims = statements_of(facts) if facts is not None else statements
    with ThreadPoolExecutor(max_workers=AT_ONCE) as pool:
        experts = [pool.submit(expert, r, f"TEXT, as numbered statements\n{numbered}") for r in EXPERTS]
        if claims:
            jurors, upheld, set_aside, present = jury(claims, reference, pool, strict)
        else:  # no health claim in the text (only dish descriptions): nothing for the fact jurors, and the report says so
            jurors, upheld, set_aside, present = [], [], [], 0
        experts = [job.result() for job in experts]
    for card in experts:
        upheld += [{**c, "raised_by": [card["name"]], "votes": card["name"]} for c in card["corrections"]]
    return {
        "reviewed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "seconds": round(time.time() - started, 1),
        "provider": llm.provider(),
        "quorum": QUORUM,
        "statements": statements,
        "approved": (present >= QUORUM or not claims) and not upheld and all(e["approved"] and not e["absent"] for e in experts),
        "fact_jury": "ruled" if claims else "nothing to rule on: no health claim in the text",
        "corrections": upheld,
        "set_aside": set_aside,
        "reviewers": jurors + experts,
    }


# --- mock provider: a board that reads nothing and says so --------------------------------------------------------

def _mock_rulings(task: str) -> Rulings:
    count = len(re.findall(r"^\d+\. ", task.split("STATEMENTS TO RULE ON\n", 1)[-1], flags=re.M))
    return Rulings(rulings=[Ruling(n=n, finding="supported", reference_says="(simulated board: not checked)") for n in range(1, count + 1)])


def _mock_verdict(task: str) -> Verdict:
    return Verdict(approved=True, corrections=[], checks=["Simulated reviewer: no model was called",
                                                           "Set LLM_PROVIDER=vertex (or bedrock) to run the real board",
                                                           "Nothing here was verified"])


llm.mock_answers.setdefault("Rulings", _mock_rulings)
llm.mock_answers.setdefault("Verdict", _mock_verdict)
