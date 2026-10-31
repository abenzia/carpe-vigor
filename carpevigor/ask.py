"""Ask the sources: a free question, answered only from passages of the public sources, checked before it is shown.

1. The question (plus, if the person entered them, which of their numbers are off their doctor's target) is
   searched across every source and the MedlinePlus library (rag.py): the K closest passages.
2. A model writes a short answer from those passages only, each sentence citing its passage [n]. If the passages
   do not answer, it says so. A part of the question that is for the doctor (a diagnosis, a medicine, what the
   person's own numbers mean or will become) is named apart, not answered.
3. The safety reviewer of the board reads the answer before the person does. If it holds the answer back, the
   person sees the passages and why, never the answer.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import checkup, llm, rag, review_board, sources

K = 6

SYSTEM = """You answer a person's question about food, movement, sleep, stress, smoking and everyday habits, using ONLY \
the numbered passages from public health sources you are given. Write 3 to 6 plain sentences in general terms — what \
the sources say about food and habits, for people in general ("Eating more soluble fiber, as in oats and beans, can help \
lower LDL cholesterol [2]") — and end each sentence with the number of its passage, like [2]. If the passages do not \
answer the question, say so in one sentence. Do not talk about this person's body or repeat their numbers: their \
numbers, if given, only tell you which passages matter. Never diagnose, never mention medicines, supplements or doses, \
never predict anyone's values. 'for_the_doctor' is only for a part of the QUESTION that asks for a diagnosis, a \
medicine, or what the person's own numbers mean or will become; otherwise leave it empty."""

FIX = SYSTEM + """

Your previous answer was held back by the safety reviewer. Rewrite it from the same passages so that it says only what \
they say, in general terms, fixing each point the reviewer raised."""


class Answer(BaseModel):
    answer: str = Field(description="3 to 6 plain sentences from the passages only, each ending with its passage number like [2]")
    cited: list[int] = Field(description="The numbers of the passages the answer uses")
    for_the_doctor: str = Field(description="One sentence naming the part of the question that is for the doctor "
                                            "(diagnosis, medicines, what their own numbers mean or will become); empty if none")


def context(rows: list[dict]) -> str:
    """The person's numbers that are off their doctor's target, in words: what a question is also searched with."""
    off = [v for v in checkup.view(rows) if v["target"] is not None and not v["status"].startswith("at ")]
    return "; ".join(f"{v['label']} {v['status']}" for v in off)


def answer(question: str, rows: list[dict]) -> dict:
    about_me = context(rows)
    # The question alone finds what it asks; the person's off-target numbers add two passages, not more: appended to
    # every query they pulled "how much should I walk?" toward cholesterol pages.
    everything = rag.everything()
    passages = rag.quotes(question, srcs=everything, k=K)
    if about_me:
        seen = {p["text"] for p in passages}
        passages += [p for p in rag.quotes(f"{question} ({about_me})", srcs=everything, k=K) if p["text"] not in seen][:2]
    out = {"question": question, "context": about_me, "passages": passages, "answer": None, "cited": [],
           "for_the_doctor": "", "safety": None, "held_back": ""}
    if not passages:
        out["held_back"] = "The sources cannot be searched right now, so there is no answer: nothing is made up."
        return out
    numbered = "\n\n".join(f"[{n}] {p['name']}\n{p['text']}" for n, p in enumerate(passages, 1))
    task = f"QUESTION: {question}\n" + (f"THEIR NUMBERS, OFF THEIR DOCTOR'S TARGET: {about_me}\n" if about_me else "") + \
           f"\nPASSAGES\n{numbered}"
    made = llm.ask(SYSTEM, task, Answer, tier="mid", temperature=0.1)
    safety = _review(made.answer)
    if not safety["approved"] and not safety.get("absent"):  # one rewrite on the reviewer's points, read again
        raised = "\n".join(f"- {c['says']} → {c['should_be']} ({c['why']})" for c in safety["corrections"])
        made = llm.ask(FIX, f"{task}\n\nYOUR ANSWER\n{made.answer}\n\nTHE REVIEWER RAISED\n{raised}", Answer, tier="mid", temperature=0.1)
        safety = _review(made.answer)
        out["rewritten"] = True
    # The note for the doctor is shown when the QUESTION is clinical (plain words, sources.CLINICAL), not when the
    # model feels like adding one: it used to send "your LDL is above target" itself to the doctor.
    out.update(safety=safety, for_the_doctor=made.for_the_doctor if sources.mentions_clinical(question) else "",
               cited=[n for n in made.cited if 1 <= n <= len(passages)])
    if safety["approved"]:
        out["answer"] = made.answer
    else:
        why = "; ".join(c["why"] for c in safety.get("corrections", [])) or safety.get("error", "the reviewer did not answer")
        out["held_back"] = f"The safety reviewer held this answer back: {why} The passages below are the sources' own words."
    return out


def _review(text: str) -> dict:
    role = next(r for r in review_board.EXPERTS if r["id"] == "safety")
    return review_board.expert(role, f"TEXT, as numbered statements\n1. {text}")


def _mock_answer(task: str) -> Answer:
    first = task.split("[1] ", 1)[1].split("\n", 2)[1] if "[1] " in task else ""
    sentence = (first.split(". ")[0].strip().rstrip(".") + ".") if first else "The passages do not answer this."
    return Answer(answer=f"{sentence} [1] (simulated: no model was called)", cited=[1], for_the_doctor="")


llm.mock_answers.setdefault("Answer", _mock_answer)
