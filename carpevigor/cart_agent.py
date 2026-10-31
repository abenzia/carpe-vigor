"""The shopping agent: from the week's recipes and the pantry to a cart the person approves.

Plain code, on purpose. What goes in the cart is a matter of arithmetic and rules — what the
recipes need, what is already at home, what is on the "don't rebuy" list, what the budget allows —
and a person must be able to read why each line is there. The language models write the plan and
check its claims (planner.py, review_board.py); they do not decide what to buy with the money.

Budget: first the cart says what the whole week needs (`needed`) and by how much the budget would have to rise
(`raise_by`). If the person keeps the lower budget, the agent drops the least essential lines first (snacks, drinks,
seasonings, fats, fruit, grains) and says so — but never a protein, vegetable or legume a recipe needs: those are
the plan. If the cart is still over budget with only those left, it stays over budget, flagged, and cannot be
ordered (week.capture_order refuses any capture past the authorization anyway).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .catalog import Catalog, Item, not_bought
from .pantry import Pantry


@dataclass
class CartLine:
    item: Item
    quantity: int
    reason: str           # which recipes need it
    swapped_from: str = ""  # name of the blacklisted item this replaces, if any
    extra: bool = False     # added by the person, not by the agent: never cut by the agent, counted by the reward

    @property
    def total(self) -> float:
        return round(self.item.price * self.quantity, 2)


@dataclass
class Cart:
    lines: list[CartLine] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # what the agent left out and why
    budget: float = 0.0
    delivery_fee: float = 0.0
    needed: float = 0.0   # what the whole week would cost, before anything is left out

    @property
    def subtotal(self) -> float:
        return round(sum(l.total for l in self.lines), 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.delivery_fee, 2)

    @property
    def within_budget(self) -> bool:
        return self.total <= self.budget + 1e-9

    @property
    def raise_by(self) -> float:
        """How much more budget would buy the whole week (0 when it already fits)."""
        return max(0.0, round(self.needed - self.budget, 2))

    @property
    def over_budget(self) -> bool:
        """Still over budget after every non-protected line is gone: the order must wait for a higher budget."""
        return bool(self.lines) and not self.within_budget


ESSENTIAL_ORDER = ("protein", "vegetable", "legume", "grain", "fruit", "dairy", "fat", "seasoning", "drink", "snack")
PROTECTED = ("protein", "vegetable", "legume")  # the plan itself: never cut to fit the budget


@dataclass
class Need:
    used_in: list[str] = field(default_factory=list)            # recipe titles
    amounts: dict[str, float] = field(default_factory=dict)     # unit → total the week's recipes use


def needs(recipes: list[dict]) -> dict[str, Need]:
    """Ingredient name → which recipes use it and how much in all. A recipe is {"title", "ingredients": [...], "buy": [...]}:
    `buy` holds store names chosen by the planner, each {"name", "amount", "unit"} (older plans: a bare name), and is used
    when present; `ingredients` (as written for the cook) is the fallback."""
    wanted: dict[str, Need] = {}
    for recipe in recipes:
        for b in recipe.get("buy") or recipe.get("ingredients", []):
            name = b["name"] if isinstance(b, dict) else b
            need = wanted.setdefault(name.strip().lower(), Need())
            need.used_in.append(recipe["title"])
            if isinstance(b, dict) and b.get("unit") and b.get("amount"):  # a buy line; an ingredient's "150 g" is text
                need.amounts[b["unit"]] = need.amounts.get(b["unit"], 0) + float(b["amount"])
    return wanted


def packs(item: Item, need: Need) -> int:
    """Packs that cover what the recipes use: 1.2 kg of chicken in 600 g packs is 2. One pack when the recipes give no
    amount in a unit the pack is sold by (a pinch of pepper, a bare name from an older plan). Grams and millilitres are
    taken as equal: recipes write stock and milk either way, and for them the difference is a few percent."""
    counts = []
    for unit, total in need.amounts.items():
        size = item.pack(unit) or item.pack({"g": "ml", "ml": "g"}.get(unit, ""))
        if size:
            counts.append(math.ceil(total / size - 1e-9))
    return max(counts + [1])


def _reason(need: Need) -> str:
    """Which recipes need the line, and how much they use in all: '450 g for Mon dinner salmon, Fri salmon bowl'."""
    used = ", ".join(dict.fromkeys(need.used_in))
    amount = " + ".join(f"{n:g} {'pieces' if u == 'piece' else u}" for u, n in need.amounts.items())
    return f"{amount} for {used}" if amount else used


def build(recipes: list[dict], pantry: Pantry, catalog: Catalog, budget: float, avoid: set[str] = frozenset()) -> Cart:
    """`avoid`: skus the profile keeps off the cart (catalog.off_plan). Applied to every line, whoever named it — the
    planner's `buy` names come from a model and must not be able to put bacon in a low-sodium week."""
    cart = Cart(budget=budget)
    at_home, blacklist = pantry.at_home(), pantry.blacklist()
    seen: dict[str, CartLine] = {}
    per_sku: dict[str, Need] = {}
    for ingredient, need in needs(recipes).items():
        used_in = need.used_in
        item = catalog.find(ingredient)
        if not item:
            if not not_bought(ingredient):  # leftovers and water are not missing, just not bought
                cart.skipped.append(f"\"{ingredient}\": not in the store's catalog")
            continue
        if item.sku in at_home and item.sku not in blacklist:
            continue  # already at home
        swapped_from = ""
        if item.sku in blacklist or item.sku in avoid:
            swap = catalog.swap_for(item.sku)
            if not swap or swap[0].sku in avoid:
                cart.skipped.append(f"{item.name}: on your \"don't rebuy\" list, no swap available" if item.sku in blacklist
                                    else f"{item.name}: off your plan, not bought")
                continue
            swapped_from, item = item.name, swap[0]
            if item.sku in at_home:
                continue
        if item.sku in seen:  # two names for one product ("lemon", "lemons"): one line, their amounts added up
            total = per_sku[item.sku]
            total.used_in += used_in
            for unit, n in need.amounts.items():
                total.amounts[unit] = total.amounts.get(unit, 0) + n
            seen[item.sku].quantity = packs(item, total)
            seen[item.sku].reason = _reason(total)
            continue
        per_sku[item.sku] = Need(list(used_in), dict(need.amounts))
        line = CartLine(item=item, quantity=packs(item, need), reason=_reason(need), swapped_from=swapped_from)
        seen[item.sku] = line
        cart.lines.append(line)
    set_delivery(cart, catalog)
    cart.needed = cart.total
    trim_to_budget(cart, catalog)
    return cart


def add_extras(cart: Cart, skus: list[str], catalog: Catalog):
    """What the person adds on top of the agent's cart: their choice, junk included. The agent never cuts it to fit
    the budget (if it does not fit, the cart is over budget and says so); the reward's basket score counts it."""
    for sku in skus:
        if sku not in catalog.items:
            continue
        line = next((l for l in cart.lines if l.item.sku == sku), None)
        if line:
            line.quantity += 1
        else:
            cart.lines.append(CartLine(item=catalog.items[sku], quantity=1, reason="your choice", extra=True))
    set_delivery(cart, catalog)
    cart.needed = max(cart.needed, cart.total)


def basket(lines: list[tuple[str, float]], catalog: Catalog, dont_rebuy: set[str] = frozenset()) -> tuple[float, float]:
    """(healthy spend, unhealthy spend) of (sku, amount) lines: what the reward's basket score is made of. A "don't
    rebuy" item counts as unhealthy whatever it is: the person had decided to finish it, not buy it again."""
    healthy = sum(a for sku, a in lines if sku not in dont_rebuy and catalog.kind(sku) == "healthy")
    unhealthy = sum(a for sku, a in lines if sku in dont_rebuy or catalog.kind(sku) == "unhealthy")
    return round(healthy, 2), round(unhealthy, 2)


def set_delivery(cart: Cart, catalog: Catalog):
    cart.delivery_fee = 0.0 if cart.subtotal >= catalog.store.get("delivery_free_over", 0) else float(catalog.store.get("delivery_fee", 0))


def rank(item: Item) -> int:
    """Lower = more essential. Protein and vegetables first, snacks last."""
    for n, tag in enumerate(ESSENTIAL_ORDER):
        if tag in item.tags:
            return n
    return len(ESSENTIAL_ORDER)


def protected(item: Item) -> bool:
    return any(tag in item.tags for tag in PROTECTED)


def trim_to_budget(cart: Cart, catalog: Catalog):
    while not cart.within_budget:
        removable = [l for l in cart.lines if not protected(l.item) and not l.extra]
        if not removable:
            break  # only the plan's proteins and vegetables are left: over_budget, the screen asks for more budget
        worst = max(removable, key=lambda l: (rank(l.item), l.total))
        cart.lines.remove(worst)
        set_delivery(cart, catalog)  # dropping a line can take the cart under the free-delivery threshold
        cart.skipped.append(f"{worst.item.name} ({worst.total:.2f}): left out to stay within the {cart.budget:.2f} budget")
