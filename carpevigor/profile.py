"""Screen 1 — "My doctor said".

The person writes, in their own words, what their doctor told them ("I have high blood pressure,
eat less salt, lose a few pounds"), plus constraints (allergies, dislikes, budget) and what they
cook with. A lab report may be attached, but it is used only to pick topics — the app never reads a
value and never judges it. Anything that sounds clinical (medicines, doses, diagnoses to make) is
sent back to the doctor: that is the board's rule, applied before a model is even asked.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from . import kitchen, llm, sources

DEVICES = kitchen.NAMES  # each with its own rules and checks (kitchen.py)


class Guidance(BaseModel):
    goals: list[str] = Field(description="What the doctor asked for, as 2-4 short lifestyle goals in plain words (food, movement, sleep, habits only)")
    constraints: list[str] = Field(description="Food constraints to respect: allergies, intolerances, dislikes, 'low sodium', 'less saturated fat', 'less sugar', budget")
    topics: list[str] = Field(description="Topic keys among: blood_pressure, cholesterol, weight, activity, fiber, sugar")
    to_the_doctor: list[str] = Field(description="Anything in the text that is clinical (medicines, doses, diagnoses, lab values to interpret): quoted, to be taken back to the doctor, not handled here")


SYSTEM = """You read what a person says their doctor told them and turn it into lifestyle goals the app can plan \
for: food, movement, sleep, habits. You never diagnose, never interpret a lab value, never mention a medicine. \
Anything clinical goes, quoted, into to_the_doctor. Keep the person's own words where you can."""


def read(doctor_said: str, device: str, extra_constraints: str = "", attached_report: bool = False) -> Guidance:
    task = (f"WHAT THE DOCTOR SAID (the person's words): {doctor_said}\n"
            f"COOKS WITH: {device}\nOTHER CONSTRAINTS: {extra_constraints or 'none given'}\n"
            f"LAB REPORT ATTACHED: {'yes — use it only to pick topics, never quote a value' if attached_report else 'no'}")
    guidance = llm.ask(SYSTEM, task, Guidance, tier="mid")  # a short reading: the fast model (argon took 25 s)
    # Code, not the model, has the last word on topics and on what goes back to the doctor.
    guidance.topics = [t for t in dict.fromkeys(guidance.topics + sources.topics_for(doctor_said)) if t in sources.TOPICS]
    if sources.mentions_clinical(doctor_said) and not guidance.to_the_doctor:
        guidance.to_the_doctor = ["Your note mentions medicines or values: that part is for your doctor, not for this app."]
    return guidance


def _mock_guidance(task: str) -> Guidance:
    said = task.split("WHAT THE DOCTOR SAID (the person's words):", 1)[-1].split("\n", 1)[0].strip()
    topics = sources.topics_for(said)
    goals = {"blood_pressure": "Eat less salt", "cholesterol": "Less saturated fat, more fiber", "weight": "Lose weight slowly",
             "activity": "Move every day", "fiber": "More fiber", "sugar": "Fewer sugary drinks and sweets"}
    constraints = {"blood_pressure": "low sodium", "cholesterol": "less saturated fat", "weight": "weight", "sugar": "less sugar"}
    return Guidance(goals=[goals[t] for t in topics], constraints=[constraints[t] for t in topics if t in constraints],
                    topics=topics, to_the_doctor=[])


llm.mock_answers.setdefault("Guidance", _mock_guidance)
