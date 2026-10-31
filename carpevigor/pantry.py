"""Home: what is in the pantry and the fridge, what to finish and not rebuy, what to swap.

The pantry is a checklist the person keeps (the primary path). A fridge photo can pre-fill it
(vision.py, optional); whatever it recognizes is shown for the person to correct, never trusted
blindly. Items that do not fit the plan are not thrown away — that would be preaching and waste.
They go on a "finish, don't rebuy" list the agent respects when it shops, with a swap offered.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Catalog


@dataclass
class PantryItem:
    sku: str
    name: str
    have: bool = True            # ticked = at home
    dont_rebuy: bool = False     # on the "finish, don't rebuy" list
    swap_sku: str | None = None
    swap_why: str = ""


@dataclass
class Pantry:
    items: dict[str, PantryItem] = field(default_factory=dict)

    def tick(self, sku: str, name: str, have: bool = True):
        entry = self.items.setdefault(sku, PantryItem(sku, name))
        entry.have = have

    def at_home(self) -> set[str]:
        return {sku for sku, i in self.items.items() if i.have}

    def blacklist(self) -> set[str]:
        return {sku for sku, i in self.items.items() if i.dont_rebuy}

    def review(self, catalog: Catalog, constraints: list[str]) -> list[PantryItem]:
        """Mark what is at home but off the plan as "finish, don't rebuy", with its swap. Returns those items."""
        off = catalog.off_plan(constraints)
        flagged = []
        for sku, entry in self.items.items():
            if entry.have and sku in off:
                entry.dont_rebuy = True
                swap = catalog.swap_for(sku)
                if swap:
                    entry.swap_sku, entry.swap_why = swap[0].sku, swap[1]
                flagged.append(entry)
        return flagged

    def to_rows(self) -> list[dict]:
        return [vars(i) for i in self.items.values()]

    @classmethod
    def from_rows(cls, rows: list[dict]) -> "Pantry":
        return cls({r["sku"]: PantryItem(**r) for r in rows})
