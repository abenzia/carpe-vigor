"""The shopping agent: from the week's recipes and the pantry to a cart the person approves.

Plain code, on purpose. What goes in the cart is a matter of arithmetic and rules — what the
recipes need, what is already at home, what is on the "don't rebuy" list, what the budget allows —
and a person must be able to read why each line is there. The language models write the plan and
check its claims (planner.py, review_board.py); they do not decide what to buy with the money.

Budget: the cart never exceeds the amount authorized with PayPal. When it would, the agent drops the
least essential lines first (snacks, then extras over the recipe quantities) and says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Catalog, Item
from .pantry import Pantry


@dataclass
class CartLine:
    item: Item
    quantity: int
    reason: str           # which recipes need it
    swapped_from: str = ""  # name of the blacklisted item this replaces, if any

    @property
    def total(self) -> float:
        return round(self.item.price * self.quantity, 2)


@dataclass
class Cart:
    lines: list[CartLine] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # what the agent left out and why
    budget: float = 0.0
    delivery_fee: float = 0.0

    @property
    def subtotal(self) -> float:
        return round(sum(l.total for l in self.lines), 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.delivery_fee, 2)

    @property
    def within_budget(self) -> bool:
        return self.total <= self.budget + 1e-9


ESSENTIAL_ORDER = ("protein", "vegetable", "legume", "grain", "fruit", "dairy", "fat", "seasoning", "drink", "snack")


def needs(recipes: list[dict]) -> dict[str, list[str]]:
    """Ingredient name → recipes that use it. A recipe is {"title", "ingredients": ["spinach", "olive oil", …]}."""
    wanted: dict[str, list[str]] = {}
    for recipe in recipes:
        for ingredient in recipe.get("ingredients", []):
            wanted.setdefault(ingredient.strip().lower(), []).append(recipe["title"])
    return wanted


def build(recipes: list[dict], pantry: Pantry, catalog: Catalog, budget: float) -> Cart:
    cart = Cart(budget=budget)
    at_home, blacklist = pantry.at_home(), pantry.blacklist()
    seen: dict[str, CartLine] = {}
    for ingredient, used_in in needs(recipes).items():
        item = catalog.find(ingredient)
        if not item:
            cart.skipped.append(f"\"{ingredient}\": not in the store's catalog")
            continue
        if item.sku in at_home and item.sku not in blacklist:
            continue  # already at home
        swapped_from = ""
        if item.sku in blacklist:
            swap = catalog.swap_for(item.sku)
            if not swap:
                cart.skipped.append(f"{item.name}: on your \"don't rebuy\" list, no swap available")
                continue
            swapped_from, item = item.name, swap[0]
            if item.sku in at_home:
                continue
        if item.sku in seen:
            seen[item.sku].reason += f", {', '.join(used_in)}"
            continue
        line = CartLine(item=item, quantity=1, reason=", ".join(dict.fromkeys(used_in)), swapped_from=swapped_from)
        seen[item.sku] = line
        cart.lines.append(line)
    cart.delivery_fee = 0.0 if cart.subtotal >= catalog.store.get("delivery_free_over", 0) else float(catalog.store.get("delivery_fee", 0))
    trim_to_budget(cart)
    return cart


def rank(item: Item) -> int:
    """Lower = more essential. Protein and vegetables first, snacks last."""
    for n, tag in enumerate(ESSENTIAL_ORDER):
        if tag in item.tags:
            return n
    return len(ESSENTIAL_ORDER)


def trim_to_budget(cart: Cart):
    while cart.lines and not cart.within_budget:
        worst = max(cart.lines, key=lambda l: (rank(l.item), l.total))
        cart.lines.remove(worst)
        cart.skipped.append(f"{worst.item.name} ({worst.total:.2f}): left out to stay within the {cart.budget:.2f} budget")
