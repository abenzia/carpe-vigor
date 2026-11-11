"""What Apple Health sends, through an iPhone shortcut: steps, exercise minutes, weight, sleep, resting heart rate, blood pressure.

Apple gives web apps no access to Health; the Shortcuts app does ("Find Health Samples"), and a shortcut posts what it
found to /api/meal's sibling /api/health with the same secret token. The person sets it up and can run it by hand or
every evening. Nothing is kept without the consent given on the measures page.

Shortcuts sends numbers as an iPhone writes them: "8.234 passi" on an Italian phone, "92,5 kg", one value per line when
it passes a list. So every field is read from text: integers with any thousands separator, decimals with a comma or a
dot. A value outside what a body can measure is dropped and named in the answer, never stored.
Where each value goes: steps -> the week's steps (30% of the reward: now measured, not typed); weight -> the measures
(BMI, energy, portions; never the reward); resting heart rate and blood pressure -> My numbers, next to the doctor's
targets, never judged; sleep -> the measures, for the coach.
"""
from __future__ import annotations

import re
from datetime import date

from . import activity, checkup, config, health

RANGES = {"steps": (0, 100_000), "exercise_min": (0, 1440),"weight_kg": (30, 300), "sleep_hours": (0, 16), "resting_hr": (30, 200),
          "systolic": (60, 260), "diastolic": (30, 160)}
_TOKEN = re.compile(r"\d[\d.,'   ]*")


def integers(value) -> list[int]:
    """'8.234 passi\\n6,100 steps' -> [8234, 6100]. Steps are whole numbers: any separator is a thousands separator."""
    if isinstance(value, (int, float)):
        return [int(value)]
    if isinstance(value, list):
        return [n for v in value for n in integers(v)]
    return [int(re.sub(r"\D", "", t)) for t in _TOKEN.findall(str(value)) if re.sub(r"\D", "", t)]


def decimal(value) -> float | None:
    """'92,5 kg' -> 92.5; a list or several lines -> the last value (the most recent sample)."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        return decimal(value[-1]) if value else None
    found = re.findall(r"\d+(?:[.,]\d+)?", str(value))
    return float(found[-1].replace(",", ".")) if found else None


def apply(payload: dict, store, today: str | None = None) -> dict:
    """Store what came in; returns what was kept and what was dropped, for the answer the phone reads aloud."""
    today = today or date.today().isoformat()
    kept, dropped = {}, []
    lo, hi = RANGES["steps"]
    if payload.get("steps") not in (None, ""):
        steps = [s for s in integers(payload["steps"]) if lo <= s <= hi][-7:]
        if steps:
            kept["steps"] = steps
        else:
            dropped.append("steps")
    if payload.get("exercise_min") not in (None, ""):
        lo, hi = RANGES["exercise_min"]
        minutes = [m for m in integers(payload["exercise_min"]) if lo <= m <= hi][-31:]
        if minutes:
            kept["exercise_min"] = minutes
        else:
            dropped.append("exercise_min")
    # each day under its date, for the report (activity.py): the last value sent is today's
    activity.record(store, {k: kept[k] for k in activity.FIELDS if k in kept}, today)
    if "steps" in kept:
        # the reward's week comes from the dated days: a shortcut may send today only (each evening) or several days
        store.put("steps", activity.week_steps(store, today))
    h = dict(store.get("health") or {})
    rows = store.get("numbers", [])
    for key in ("weight_kg", "sleep_hours", "resting_hr", "systolic", "diastolic"):
        if payload.get(key) in (None, ""):
            continue
        v = decimal(payload[key])
        if key == "sleep_hours" and v is not None and v > 24:
            # a shortcut summing sleep samples' durations sends minutes (up to a day's 1,440) or seconds
            v = v / 60 if v <= 1440 else v / 3600
        lo, hi = RANGES[key]
        if v is None or not lo <= v <= hi:
            dropped.append(key)
            continue
        kept[key] = round(v, 1)
        if key == "weight_kg":
            h["weight_kg"] = kept[key]
            if h.get("height_cm"):
                h["bmi"] = health.bmi(h["height_cm"], h["weight_kg"])
        elif key == "sleep_hours":
            h["sleep_hours"] = kept[key]
        # weight, heart rate and pressure also join My numbers, one reading a day (a daily sync replaces today's)
        measure = {"weight_kg": "weight", "resting_hr": "resting_hr", "systolic": "systolic", "diastolic": "diastolic"}.get(key)
        if measure:
            rows = [r for r in rows if not (r["key"] == measure and r["date"] == today)]
            rows = checkup.add(rows, measure, kept[key], today)
    h["synced"] = {"at": today, "from": "Apple Health", "fields": sorted(kept)}
    store.put("health", h)
    store.put("numbers", rows)
    return {"kept": kept, "dropped": dropped}


def spoken(result: dict) -> str:
    """The notification the shortcut shows: in the app's voice language (config.VOICE_LANG), like the diary's answer."""
    if config.VOICE_LANG == "it":
        return _spoken_it(result)
    k = result["kept"]
    parts = []
    if "steps" in k:
        parts.append(f"{len(k['steps'])} days of steps, {k['steps'][-1]:,} today" if len(k["steps"]) > 1
                     else f"{k['steps'][0]:,} steps today")
    if "exercise_min" in k:
        parts.append(f"{k['exercise_min'][-1]} exercise minutes today")
    if "weight_kg" in k:
        parts.append(f"weight {k['weight_kg']:g} kilograms")
    if "sleep_hours" in k:
        parts.append(f"{k['sleep_hours']:g} hours of sleep")
    if "resting_hr" in k:
        parts.append(f"resting heart rate {k['resting_hr']:g}")
    if "systolic" in k and "diastolic" in k:
        parts.append(f"blood pressure {k['systolic']:g} over {k['diastolic']:g}")
    said = "Carpe Vigor updated: " + ", ".join(parts) + "." if parts else "Nothing new was received."
    if result["dropped"]:
        said += f" Not kept, out of range: {', '.join(result['dropped'])}."
    return said


_IT_NAMES = {"steps": "passi", "exercise_min": "minuti di esercizio", "weight_kg": "peso", "sleep_hours": "sonno",
             "resting_hr": "battito a riposo", "systolic": "pressione massima", "diastolic": "pressione minima"}


def _spoken_it(result: dict) -> str:
    k, it = result["kept"], lambda v: f"{v:,}".replace(",", ".")
    parts = []
    if "steps" in k:
        parts.append(f"{len(k['steps'])} giorni di passi, {it(k['steps'][-1])} oggi" if len(k["steps"]) > 1
                     else f"{it(k['steps'][0])} passi oggi")
    if "exercise_min" in k:
        parts.append(f"{k['exercise_min'][-1]} minuti di esercizio oggi")
    if "weight_kg" in k:
        parts.append(f"peso {k['weight_kg']:g} chili".replace(".", ","))
    if "sleep_hours" in k:
        parts.append(f"{k['sleep_hours']:g} ore di sonno".replace(".", ","))
    if "resting_hr" in k:
        parts.append(f"battito a riposo {k['resting_hr']:g}")
    if "systolic" in k and "diastolic" in k:
        parts.append(f"pressione {k['systolic']:g} su {k['diastolic']:g}")
    said = "Carpe Vigor aggiornato: " + ", ".join(parts) + "." if parts else "Non è arrivato niente di nuovo."
    if result["dropped"]:
        said += f" Non tenuti, fuori dai valori possibili: {', '.join(_IT_NAMES[d] for d in result['dropped'])}."
    return said
