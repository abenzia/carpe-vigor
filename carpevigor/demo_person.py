"""The example person of the public demo: the week filmed for the video (invented doctor's words, an invented lab
report, sample steps and meals), so a judge can walk every screen without the AI writing anything.

`data/demo_person.json` was recorded on 12 Nov 2026. Steps, meals and training sessions are moved forward to today, so
"today", "this week" and "this month" are never empty. The money is not moved: the authorization, capture, release and
refund are the real sandbox records of 10 Nov 2026, with their PayPal ids.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .store import Store

FILE = Path(__file__).resolve().parent.parent / "data" / "demo_person.json"
SHIFTED = ("days", "diary", "training")  # the person's own days; everything else keeps its date
_DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)")


def _shift(value, days: int):
    text = json.dumps(value, ensure_ascii=False)
    moved = _DATE.sub(lambda m: date.fromordinal(date.fromisoformat(m.group(1)).toordinal() + days).isoformat(), text)
    return json.loads(moved)


def load(store: Store, today: date | None = None):
    """Replace whatever is in `store` with the example person, their days moved to end on `today`."""
    saved = json.loads(FILE.read_text(encoding="utf-8"))
    days = ((today or date.today()) - date.fromisoformat(saved["recorded_on"])).days
    store.reset()
    for key, value in saved["kv"].items():
        store.put(key, _shift(value, days) if key in SHIFTED else value)
    with store._lock:
        for e in saved["log"]:
            store.conn.execute("INSERT INTO log (at, kind, data) VALUES (?, ?, ?)",
                               (e["at"], e["kind"], json.dumps(e["data"], ensure_ascii=False)))
        store.conn.commit()
