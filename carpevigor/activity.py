"""Day by day: what the watch and the phone counted, and what was eaten, against the week's goals.

Apple Health sends, through the person's shortcut, the last days of steps and exercise minutes (Apple's "Exercise
Minutes", the green ring: brisk movement or more). Each value is kept under its date, so the report can show a day, a
week or a month. The goals are the ones the app already uses, not new ones: STEPS_GOAL steps a day (the reward's
"moved" days) and the US guidelines' 150 moderate minutes a week (coach.py). Calories eaten come from the diary and are
shown next to the energy reference of the measures page: a reference, never a goal that pays.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from . import coach, config

FIELDS = ("steps", "exercise_min")


def record(store, values: dict[str, list[int]], today: str | None = None) -> None:
    """{"steps": [... , today]} -> each value under its date, the last one today's. A later sync replaces a day."""
    end = date.fromisoformat(today) if today else date.today()
    days = dict(store.get("days") or {})
    for field, series in values.items():
        for back, v in enumerate(reversed(series)):
            on = (end - timedelta(days=back)).isoformat()
            days[on] = {**days.get(on, {}), field: int(v)}
    store.put("days", days)


def _eaten(diary: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for e in diary:
        out[e["at"][:10]] = out.get(e["at"][:10], 0) + e["nutrition"].get("kcal", 0)
    return out


def report(store, view: str = "week", today: str | None = None, kcal_reference: int | None = None) -> dict:
    """The bars of one view (day, week, month) and how the goals stand, all added up here by plain arithmetic."""
    end = date.fromisoformat(today) if today else date.today()
    span = {"day": 1, "week": 7, "month": 30}.get(view, 7)
    days, eaten = store.get("days") or {}, _eaten(store.get("diary", []))
    rows = []
    for back in range(span - 1, -1, -1):
        on = (end - timedelta(days=back)).isoformat()
        d = days.get(on, {})
        rows.append({"on": on, "label": f"{on[8:10]}/{on[5:7]}", "steps": d.get("steps"), "exercise_min": d.get("exercise_min"),
                     "kcal": round(eaten[on]) if on in eaten else None})
    known = [r for r in rows if r["steps"] is not None]
    minutes = sum(r["exercise_min"] or 0 for r in rows)
    weekly = coach.MIN_MINUTES * span / 7  # 150 a week, spread over the days shown
    return {"view": view, "rows": rows, "steps_goal": config.STEPS_GOAL, "kcal_reference": kcal_reference,
            "days_moved": sum(1 for r in known if r["steps"] >= config.STEPS_GOAL), "days_known": len(known),
            "minutes": minutes, "minutes_goal": round(weekly), "minutes_met": minutes >= weekly,
            "daily_minutes": round(coach.MIN_MINUTES / 7),
            "max_steps": max([r["steps"] or 0 for r in rows] + [config.STEPS_GOAL]),
            "max_minutes": max([r["exercise_min"] or 0 for r in rows] + [round(coach.MIN_MINUTES / 7)]),
            "max_kcal": max([r["kcal"] or 0 for r in rows] + [kcal_reference or 0, 1])}


def goals(store, today: str | None = None) -> list[dict]:
    """Today, this calendar week (Mon-Sun) and this calendar month: steps days and exercise minutes against the goals,
    with where the person should be by today ("pace") so a Tuesday is not judged against a whole week."""
    end = date.fromisoformat(today) if today else date.today()
    days = store.get("days") or {}
    week_start = end - timedelta(days=end.weekday())
    month_days = calendar.monthrange(end.year, end.month)[1]
    out = []
    for name, start, length in (("Today", end, 1), ("This week", week_start, 7), ("This month", end.replace(day=1), month_days)):
        elapsed = (end - start).days + 1
        seen = [days.get((start + timedelta(days=i)).isoformat(), {}) for i in range(elapsed)]
        minutes_goal = round(coach.MIN_MINUTES * length / 7)
        if length == 1:
            out.append({"name": name, "steps": seen[0].get("steps"), "steps_goal": config.STEPS_GOAL, "steps_pace": None,
                        "steps_unit": "steps", "minutes": seen[0].get("exercise_min"), "minutes_goal": minutes_goal,
                        "minutes_pace": None})
            continue
        out.append({"name": name, "steps": sum(1 for d in seen if (d.get("steps") or 0) >= config.STEPS_GOAL),
                    "steps_goal": length, "steps_pace": elapsed, "steps_unit": f"days over {config.STEPS_GOAL:,} steps",
                    "minutes": sum(d.get("exercise_min") or 0 for d in seen), "minutes_goal": minutes_goal,
                    "minutes_pace": round(coach.MIN_MINUTES * elapsed / 7)})
    return out


OVER = 1.10        # more than 10% over the energy reference...
OVER_DAYS = 2      # ...on 2 of the last 3 full days (today is not over yet) proposes adapting the week
LOOK_BACK = 3


def over_reference(store, kcal_reference: int | None, today: str | None = None) -> dict | None:
    """The days that ate past the reference, when there are enough of them to offer the person an adapted week.
    None without a reference (no measures, no doctor's number): nothing to compare with. The diary is an estimate
    (a third either way), so this only offers; the person decides, and it never touches the reward."""
    if not kcal_reference:
        return None
    end = date.fromisoformat(today) if today else date.today()
    eaten = _eaten(store.get("diary", []))
    days = [(end - timedelta(days=back)).isoformat() for back in range(LOOK_BACK, 0, -1)]
    over = [{"on": on, "kcal": round(eaten[on])} for on in days if eaten.get(on, 0) > kcal_reference * OVER]
    if len(over) < OVER_DAYS:
        return None
    return {"days": over, "reference": kcal_reference, "of": LOOK_BACK}
