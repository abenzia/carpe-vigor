"""The reward: a share of the week's grocery spend comes back for behaviour, never for weight.

Why behaviour and not results: an app that pays for kilos lost also pays for skipping meals. What
is rewarded here is doing your part — cooking the plan, moving, keeping the "finish, don't rebuy"
list out of the cart. Each is measured from data the app already has: cooked check-offs, steps
(from a watch, simulated in the demo), and the orders the agent placed.

Who pays it in the product: the employer inside its welfare plan, the insurer, the retailer whose
basket becomes weekly and loyal. In the demo, the platform.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass
class WeekBehaviour:
    planned_meals: int          # meals in the week's plan
    cooked_meals: int           # meals the person checked off as cooked
    days_with_steps: int        # days over STEPS_GOAL steps
    blacklist_respected: bool   # no "don't rebuy" item ended up in any order this week
    spent: float                # grocery spend captured this week


@dataclass
class Reward:
    score: float            # 0..1
    cashback_rate: float    # 0..CASHBACK_MAX
    cashback: float         # money back
    reasons: list[str]

    @property
    def earned(self) -> bool:
        return self.cashback > 0


def score(behaviour: WeekBehaviour) -> Reward:
    """Three parts, equal weight: meals cooked (share), active days (share of 7), blacklist kept (all or nothing).

    Cashback = max rate × score, rounded to the cent, only when the score is at least 0.5: a half-hearted
    week pays nothing, so the reward means something."""
    meals = behaviour.cooked_meals / behaviour.planned_meals if behaviour.planned_meals else 0.0
    moved = min(behaviour.days_with_steps, 7) / 7
    kept = 1.0 if behaviour.blacklist_respected else 0.0
    total = round((meals + moved + kept) / 3, 3)
    reasons = [
        f"Cooked {behaviour.cooked_meals} of {behaviour.planned_meals} planned meals",
        f"Moved on {behaviour.days_with_steps} of 7 days ({config.STEPS_GOAL:,} steps or more)",
        "Kept the \"finish, don't rebuy\" list out of the cart" if kept else "A \"don't rebuy\" item was bought this week",
    ]
    rate = round(config.CASHBACK_MAX * total, 4) if total >= 0.5 else 0.0
    return Reward(score=total, cashback_rate=rate, cashback=round(behaviour.spent * rate, 2), reasons=reasons)
