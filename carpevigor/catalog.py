"""The store the agent shops at.

A catalog is a list of items with a sku, a name, a unit, a price and tags, plus a table of swaps
("butter → olive oil, why"). The demo ships a mock catalog (`data/catalog.json`), clearly labelled
as such in the UI. `Channel3Catalog` is the hook for a real product catalog built for AI agents;
it is wired only when `CHANNEL3_API_KEY` is set and is not needed for the demo.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Item:
    sku: str
    name: str
    unit: str
    price: float
    tags: tuple[str, ...]

    def has(self, *tags: str) -> bool:
        return all(t in self.tags for t in tags)


class Catalog:
    def __init__(self, data: dict):
        self.store = data["store"]
        self.items = {i["sku"]: Item(i["sku"], i["name"], i["unit"], float(i["price"]), tuple(i.get("tags", ()))) for i in data["items"]}
        self.swaps = data.get("swaps", {})

    @classmethod
    def load(cls, path=None) -> "Catalog":
        with open(path or config.DATA / "catalog.json", encoding="utf-8") as f:
            return cls(json.load(f))

    def find(self, query: str) -> Item | None:
        """The item whose name best matches a plain-words ingredient ("spinach", "olive oil", "greek yogurt")."""
        q = query.lower().strip()
        words = [w for w in q.replace(",", " ").split() if len(w) > 2]
        best, best_score = None, 0
        for item in self.items.values():
            name = item.name.lower()
            score = (3 if q and q in name else 0) + sum(1 for w in words if w in name)
            if score > best_score:
                best, best_score = item, score
        return best

    def swap_for(self, sku: str) -> tuple[Item, str] | None:
        swap = self.swaps.get(sku)
        if not swap or swap["to"] not in self.items:
            return None
        return self.items[swap["to"]], swap["why"]

    def off_plan(self, constraints: list[str]) -> set[str]:
        """Skus that a plan with these constraints keeps off the cart: high-sodium and processed items for
        "low sodium", saturated-fat items for "less saturated fat", sugary drinks for "less sugar". A constraint is
        plain words from the profile ("low sodium", "saturated", "sugar")."""
        text = " ".join(constraints).lower()
        bad: set[str] = set()
        for item in self.items.values():
            if "sodium" in text and (item.has("high-sodium") or item.has("processed")):
                bad.add(item.sku)
            if "saturated" in text and item.has("saturated"):
                bad.add(item.sku)
            if "sugar" in text and item.has("sugar"):
                bad.add(item.sku)
            if "weight" in text and (item.has("snack") or item.has("sugar") or item.has("saturated")):
                bad.add(item.sku)
        return bad


class Channel3Catalog(Catalog):
    """Placeholder for the Channel3 product catalog (an AI-agent-oriented catalog, a hackathon sponsor).
    Wire `search` to their API when `CHANNEL3_API_KEY` is set; until then the mock catalog is used."""

    @classmethod
    def available(cls) -> bool:
        return bool(os.environ.get("CHANNEL3_API_KEY"))
