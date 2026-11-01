"""A lab report, read once: the person uploads a PDF or a photo, a model reads the values printed on it, the person
checks every one before anything is kept.

What the model may do: copy values, units and the test date as printed, and say which of our measures each one is.
What it may not: judge a value, read the lab's ranges as a verdict, or guess a number that is not printed. Plain code
then checks the unit (converting mmol/L to mg/dL with the standard factors) and that the value is one a body can have;
anything doubtful is shown as such and left unticked. Nothing is saved until the person confirms, and only the
confirmed values are kept (checkup.py): the file itself is never stored. Reading it means sending it to Google Vertex
AI, and the upload form says so before the person sends it.
"""
from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field

from . import checkup, llm

TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_BYTES = 10 * 1024 * 1024
# plausible values for an adult, in our units: outside them a reading is shown as doubtful, never ticked
PLAUSIBLE = {"systolic": (60, 260), "diastolic": (30, 160), "ldl": (10, 500), "hdl": (5, 200),
             "total_cholesterol": (50, 700), "triglycerides": (10, 3000), "glucose": (20, 600), "a1c": (3, 20),
             "waist": (40, 200), "weight": (30, 300), "resting_hr": (30, 200)}
# mmol/L -> mg/dL (cholesterol 38.67, triglycerides 88.57, glucose 18.016); mmol/mol HbA1c -> % (IFCC to NGSP)
_MMOL = {"ldl": 38.67, "hdl": 38.67, "total_cholesterol": 38.67, "triglycerides": 88.57, "glucose": 18.016}


class Reading(BaseModel):
    measure: str = Field(description="One of: " + ", ".join(checkup.MEASURES) + "; or 'other' for anything else")
    printed_name: str = Field(description="The test's name exactly as printed on the report")
    value: float = Field(description="The number exactly as printed (a decimal comma becomes a point)")
    unit: str = Field(description="The unit exactly as printed, e.g. 'mg/dL', 'mmol/L', '%', 'mmol/mol'")


class Extracted(BaseModel):
    test_date: str = Field(description="The date the sample was taken, YYYY-MM-DD, or empty if not printed")
    readings: list[Reading]


READ = """You copy values from a medical lab report into a list. For each test printed, give its name as printed, \
the value and the unit exactly as printed, and which of the listed measures it is ('other' when none). Copy only \
what is printed: never guess a missing value, never convert units, never judge or comment on any value, and ignore \
the lab's reference ranges and flags. Give the date the sample was taken if it is printed."""


def _unit_ok(measure: str, value: float, unit: str) -> tuple[float, str] | None:
    """The value in our unit, or None when the unit is not one we can read safely."""
    want = checkup.MEASURES[measure]["unit"].lower()
    u = unit.strip().lower().replace(" ", "")
    if u in (want.replace(" ", ""), want.replace("dl", "100ml")):
        return value, ""
    if measure in _MMOL and u in ("mmol/l", "mmol/litro"):
        return round(value * _MMOL[measure], 1), f"converted from {value:g} mmol/L"
    if measure == "a1c" and u == "mmol/mol":
        return round(value / 10.929 + 2.15, 1), f"converted from {value:g} mmol/mol"
    if measure == "weight" and u == "kg" or measure in ("systolic", "diastolic") and u == "mmhg":
        return value, ""
    return None


def read(data: bytes, mime: str) -> dict:
    """The draft the person checks: each reading with what code thinks of it. Raises ValueError on a bad file."""
    if mime not in TYPES:
        raise ValueError("Send a PDF or a photo (JPEG, PNG, HEIC).")
    if not data or len(data) > MAX_BYTES:
        raise ValueError("The file is empty or larger than 10 MB.")
    got = llm.ask(READ, "Read this lab report.", Extracted, tier="mid", attachment=(data, mime))
    on = got.test_date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", got.test_date or "") else ""
    if on and on > date.today().isoformat():
        on = ""
    rows = []
    for r in got.readings[:40]:
        row = {"measure": r.measure, "printed": r.printed_name[:80], "printed_value": r.value, "printed_unit": r.unit[:20],
               "value": None, "note": "", "ok": False}
        if r.measure in checkup.MEASURES:
            converted = _unit_ok(r.measure, r.value, r.unit)
            if converted is None:
                row["note"] = f"unit '{r.unit}' not recognised: check it on the report"
            else:
                row["value"], row["note"] = converted
                lo, hi = PLAUSIBLE[r.measure]
                row["ok"] = lo <= row["value"] <= hi
                if not row["ok"]:
                    row["note"] = "this value looks unlikely: check it on the report"
        else:
            row["note"] = "not one of the measures this app keeps"
        rows.append(row)
    return {"test_date": on, "rows": rows}


def confirm(rows: list[dict], draft: dict, picked: dict[int, tuple[str, str, str]]) -> list[dict]:
    """Keep the readings the person ticked, with the value, date and doctor's target they confirmed."""
    for i, (value, on, target) in picked.items():
        r = draft["rows"][i]
        if r["measure"] not in checkup.MEASURES:
            continue
        v = float(value.replace(",", "."))
        lo, hi = PLAUSIBLE[r["measure"]]
        if not lo <= v <= hi:
            raise ValueError(f"{r['printed']}: {v:g} is outside what this app can keep; check it.")
        rows = checkup.add(rows, r["measure"], v, on, float(target.replace(",", ".")) if target.strip() else None)
    return rows


def _mock_read(task: str) -> Extracted:
    """No model: nothing can be read from a file."""
    return Extracted(test_date="", readings=[])


llm.mock_answers.setdefault("Extracted", _mock_read)
