"""The coach: the week's movement, its own member of the team.

`areas_worked` reads a day's movement line and names the body areas it works, for the 3D body page: plain words to
plain areas ("squats" -> legs and glutes), no model. The coach's plan itself is written by planner.py for now; it
moves here as its own role, with the activity guidelines and the person's steps.
"""
from __future__ import annotations

import re

AREAS = ("legs", "glutes", "core", "chest", "arms", "back", "shoulders")
# words of a movement line -> the areas they work
_WORDS = [
    (r"walk|stroll|hike|stairs|steps|march|jog|run|cycl|bike|swim|danc", ("legs", "glutes")),
    (r"squat|lunge|step-?up|calf|bridge|deadlift|leg", ("legs", "glutes")),
    (r"push-?up|press|plank|dip|chest", ("chest", "arms", "shoulders")),
    (r"plank|crunch|core|abs|sit-?up|bird-?dog|dead-?bug|twist", ("core",)),
    (r"row|pull|superman|back|band", ("back", "arms")),
    (r"swim|yoga|stretch|pilates|tai ?chi|mobility", ("back", "shoulders", "core")),
]


def areas_worked(line: str) -> list[str]:
    found: list[str] = []
    for pattern, areas in _WORDS:
        if re.search(pattern, line or "", re.I):
            found += [a for a in areas if a not in found]
    return [a for a in AREAS if a in found]
