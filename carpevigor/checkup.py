"""My numbers: the test results a person chooses to enter, shown back against the target their doctor set.

Optional. Whoever does not enter anything gets the same app, steered by the doctor's words and the cart. Whoever
does gets help with them:
- each measure over time, next to the doctor's target, with the direction it is moving;
- "above the doctor's target" adds that measure's topic to the week's plan (planner via app.py);
- what the public sources say about the measure, quoted with the source's name (rag.py, in the screen).

The app compares a number with the doctor's own target and nothing else: no thresholds of its own, no diagnosis,
no prediction. The measures are a closed list, so a value always has its unit, its right side and its topic.

The check-up bonus: at the next visit the doctor gives a verdict on the goals they set (met / improving / not
yet); the bonus is a share of the grocery spend since the previous check-up, added to the month's reward.
"""
from __future__ import annotations

from datetime import date

from . import config

# key: label, unit, which side of the doctor's target is the right one, the plan topic it steers
MEASURES = {
    "systolic": {"label": "Blood pressure, systolic (upper)", "unit": "mmHg", "good": "below", "topic": "blood_pressure"},
    "diastolic": {"label": "Blood pressure, diastolic (lower)", "unit": "mmHg", "good": "below", "topic": "blood_pressure"},
    "ldl": {"label": "LDL cholesterol", "unit": "mg/dL", "good": "below", "topic": "cholesterol"},
    "hdl": {"label": "HDL cholesterol", "unit": "mg/dL", "good": "above", "topic": "cholesterol"},
    "total_cholesterol": {"label": "Total cholesterol", "unit": "mg/dL", "good": "below", "topic": "cholesterol"},
    "triglycerides": {"label": "Triglycerides", "unit": "mg/dL", "good": "below", "topic": "cholesterol"},
    "glucose": {"label": "Fasting blood glucose", "unit": "mg/dL", "good": "below", "topic": "sugar"},
    "a1c": {"label": "HbA1c", "unit": "%", "good": "below", "topic": "sugar"},
    "waist": {"label": "Waist", "unit": "cm", "good": "below", "topic": "weight"},
    "weight": {"label": "Weight", "unit": "kg", "good": "below", "topic": "weight"},
    "resting_hr": {"label": "Resting heart rate", "unit": "bpm", "good": "below", "topic": "activity"},
}
VERDICTS = ("met", "improving", "not yet")


def add(rows: list[dict], key: str, value: float, on: str, target: float | None = None) -> list[dict]:
    """A new reading. Without a target, the doctor's last target for that measure is kept."""
    if key not in MEASURES:
        raise ValueError(f"Unknown measure: {key}")
    if value <= 0 or (target is not None and target <= 0):
        raise ValueError("Values and targets are positive numbers")
    date.fromisoformat(on)
    if target is None:
        target = next((r["target"] for r in sorted(rows, key=lambda r: r["date"], reverse=True)
                       if r["key"] == key and r.get("target")), None)
    return rows + [{"key": key, "value": value, "date": on, "target": target}]


def _right_side(key: str, value: float, target: float) -> bool:
    return value <= target if MEASURES[key]["good"] == "below" else value >= target


def view(rows: list[dict]) -> list[dict]:
    """One entry per measure entered: its readings oldest first, the doctor's target, where the latest stands
    against it, and whether it moved toward or away from it since the reading before."""
    out = []
    for key, m in MEASURES.items():
        mine = sorted((r for r in rows if r["key"] == key), key=lambda r: r["date"])
        if not mine:
            continue
        latest, target = mine[-1], mine[-1].get("target")
        if target is None:
            status, trend = "no target from your doctor yet", ""
        else:
            status = "at your doctor's target" if _right_side(key, latest["value"], target) else "above your doctor's target" \
                if m["good"] == "below" else "below your doctor's target"
            trend = ""
            if len(mine) > 1 and mine[-2]["value"] != latest["value"]:
                closer = abs(latest["value"] - target) < abs(mine[-2]["value"] - target)
                trend = "toward the target" if closer or _right_side(key, latest["value"], target) else "away from the target"
        out.append({"key": key, **m, "readings": mine, "latest": latest, "target": target, "status": status, "trend": trend})
    return out


def topics(rows: list[dict]) -> list[str]:
    """The plan topics of the measures off the doctor's target, in the order of MEASURES, each once."""
    off = [v["topic"] for v in view(rows) if v["target"] is not None and not v["status"].startswith("at ")]
    return list(dict.fromkeys(off))


def bonus(verdict: str, spent_since_last: float) -> float:
    """The doctor's verdict at a check-up, as a share of the grocery spend since the previous check-up."""
    if verdict not in VERDICTS:
        raise ValueError(f"Unknown verdict: {verdict}")
    return round(spent_since_last * config.CHECKUP_BONUS[verdict], 2)
