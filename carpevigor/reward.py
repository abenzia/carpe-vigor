"""The reward: a share of the week's grocery spend comes back for behaviour, never for weight.

Why behaviour and not results: an app that pays for kilos lost also pays for skipping meals. What
is rewarded here is doing your part, and most of it is measured, not declared:

- the basket (half the score): money PayPal really captured, split by what the agent bought in it (PayPal confirms
  the amounts, not the items: the split comes from our cart). The share of the money that went on vegetables, legumes,
  fruit, fish and whole grains, minus twice the share that went on sweets, snacks, cured meat, sugary drinks
  and saturated fat. Each dollar of junk costs twice what a dollar of vegetables earns;
- moving (30%): days over the step goal, from the phone's health platform (typed in the demo);
- cooking (20%): meals checked off as cooked, self-reported, so it weighs least.

The rate goes up to CASHBACK_MAX (20%) of what was actually spent, and a week under half the score pays nothing.
Whoever games the self-reported part still only gets back a share of money they really spent on groceries.

Who pays it in the product: the employer inside its welfare plan, the insurer, the retailer whose
basket becomes weekly and loyal. In the demo, the platform. It is paid once a month (week.settle_month).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config

WEIGHTS = {"basket": 0.5, "moved": 0.3, "cooked": 0.2}
JUNK_COUNTS = 2  # a dollar of junk weighs twice a dollar of healthy food
THRESHOLD = 0.5


@dataclass
class WeekBehaviour:
    planned_meals: int          # meals in the week's plan
    cooked_meals: int           # meals the person checked off as cooked
    days_with_steps: int        # days over STEPS_GOAL steps
    spent: float                # grocery spend captured this week
    healthy_spend: float = 0.0  # of which on healthy food (catalog.kind)
    unhealthy_spend: float = 0.0  # of which on junk, or on the "don't rebuy" list
    days_trained: int = 0       # days under STEPS_GOAL but with the training program's session done


@dataclass
class Reward:
    score: float            # 0..1
    cashback_rate: float    # 0..CASHBACK_MAX
    cashback: float         # money back
    reasons: list[str]
    parts: list[dict] = field(default_factory=list)  # key, label, share 0..1, weight, source

    @property
    def earned(self) -> bool:
        return self.cashback > 0


def basket_quality(healthy: float, unhealthy: float, spent: float) -> float:
    """Healthy share of the spend minus twice the junk share, between 0 and 1."""
    if spent <= 0:
        return 0.0
    return round(min(1.0, max(0.0, healthy / spent - JUNK_COUNTS * unhealthy / spent)), 3)


def score(behaviour: WeekBehaviour) -> Reward:
    b = behaviour
    basket = basket_quality(b.healthy_spend, b.unhealthy_spend, b.spent)
    days_moved = min(b.days_with_steps + b.days_trained, 7)
    moved = days_moved / 7
    cooked = b.cooked_meals / b.planned_meals if b.planned_meals else 0.0
    total = round(WEIGHTS["basket"] * basket + WEIGHTS["moved"] * moved + WEIGHTS["cooked"] * cooked, 3)
    healthy_pct = round(100 * b.healthy_spend / b.spent) if b.spent else 0
    junk_pct = round(100 * b.unhealthy_spend / b.spent) if b.spent else 0
    parts = [
        {"key": "basket", "label": f"Basket: {healthy_pct}% healthy food, {junk_pct}% sweets, snacks and cured meat",
         "share": basket, "weight": WEIGHTS["basket"], "source": "captured by PayPal"},
        {"key": "moved", "label": f"Moved on {days_moved} of 7 days: {b.days_with_steps} with {config.STEPS_GOAL:,} steps or more, "
                                  f"{b.days_trained} with your training session",
         "share": round(moved, 3), "weight": WEIGHTS["moved"], "source": "from your phone's health app and your training log"},
        {"key": "cooked", "label": f"Cooked {b.cooked_meals} of {b.planned_meals} planned meals",
         "share": round(cooked, 3), "weight": WEIGHTS["cooked"], "source": "self-reported"},
    ]
    rate = round(config.CASHBACK_MAX * total, 4) if total >= THRESHOLD else 0.0
    return Reward(score=total, cashback_rate=rate, cashback=round(b.spent * rate, 2),
                  reasons=[p["label"] for p in parts], parts=parts)
