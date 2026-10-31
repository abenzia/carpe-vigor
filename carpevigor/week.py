"""The week as money: budget authorized once, captured per order, remainder released, reward paid back.

This is the thin layer between the screens and PayPal: it keeps the authorization and the captures
in the store, exposes the three numbers the UI shows everywhere — budget / spent / released — and
turns the reward into a refund.
"""
from __future__ import annotations

from . import config, paypal, reward
from .store import Store


def status(store: Store) -> dict:
    auth = store.get("authorization")
    captures = store.get("captures", [])
    refunds = store.get("refunds", [])
    spent = round(sum(c["amount"] for c in captures), 2)
    budget = auth["amount"] if auth else 0.0
    return {
        "mode": paypal.client().mode,
        "currency": config.CURRENCY,
        "authorized": bool(auth) and not auth.get("voided"),
        "budget": budget,
        "spent": spent,
        "remaining": round(budget - spent, 2) if auth and not auth.get("voided") else 0.0,
        "released": auth.get("released", 0.0) if auth else 0.0,
        "cashback": round(sum(r["amount"] for r in refunds), 2),
        "authorization": auth,
        "captures": captures,
        "refunds": refunds,
    }


def start_authorization(store: Store, amount: float, return_url: str, cancel_url: str) -> dict:
    order = paypal.client().create_order(amount, config.CURRENCY, "Carpe Vigor — weekly grocery budget", return_url, cancel_url)
    store.put("pending_order", {"order_id": order["id"], "amount": amount})
    store.log("order_created", {"order_id": order["id"], "amount": amount})
    return order


def complete_authorization(store: Store, order_id: str) -> dict:
    pending = store.get("pending_order") or {}
    if pending.get("order_id") != order_id:
        raise paypal.PayPalError("This approval does not match the pending order.")
    auth = paypal.client().authorize_order(order_id)
    record = {"order_id": order_id, "authorization_id": auth["authorization_id"], "amount": auth["amount"],
              "currency": auth["currency"], "voided": False, "released": 0.0}
    store.put("authorization", record)
    store.put("captures", [])
    store.put("refunds", [])
    store.delete("pending_order")
    store.log("authorized", record)
    return record


def capture_order(store: Store, amount: float, note: str) -> dict:
    auth = store.get("authorization")
    if not auth or auth.get("voided"):
        raise paypal.PayPalError("No active budget authorization.")
    if round(sum(c["amount"] for c in store.get("captures", [])) + amount, 2) > auth["amount"] + 1e-9:
        raise paypal.PayPalError("This order would exceed the authorized budget.")
    cap = paypal.client().capture(auth["authorization_id"], amount, note)
    captures = store.get("captures", [])
    captures.append({"capture_id": cap["capture_id"], "amount": amount, "note": note, "refunded": 0.0})
    store.put("captures", captures)
    store.log("captured", {"capture_id": cap["capture_id"], "amount": amount, "note": note})
    return cap


def release_remainder(store: Store) -> dict:
    auth = store.get("authorization")
    if not auth or auth.get("voided"):
        raise paypal.PayPalError("No active budget authorization.")
    spent = round(sum(c["amount"] for c in store.get("captures", [])), 2)
    paypal.client().void(auth["authorization_id"])
    auth["voided"], auth["released"] = True, round(auth["amount"] - spent, 2)
    store.put("authorization", auth)
    store.log("released", {"released": auth["released"]})
    return auth


def pay_reward(store: Store, result: reward.Reward) -> list[dict]:
    """Refund the cashback across this week's captures, largest first, up to each capture's amount."""
    left = result.cashback
    captures = store.get("captures", [])
    refunds = store.get("refunds", [])
    for cap in sorted(captures, key=lambda c: -c["amount"]):
        if left <= 0:
            break
        room = round(cap["amount"] - cap.get("refunded", 0.0), 2)
        if room <= 0:
            continue
        amount = min(left, room)
        ref = paypal.client().refund(cap["capture_id"], amount, "Carpe Vigor reward: you did your part this week")
        cap["refunded"] = round(cap.get("refunded", 0.0) + amount, 2)
        refunds.append({"refund_id": ref["refund_id"], "capture_id": cap["capture_id"], "amount": amount, "reasons": result.reasons})
        left = round(left - amount, 2)
    store.put("captures", captures)
    store.put("refunds", refunds)
    store.log("reward_paid", {"cashback": result.cashback, "rate": result.cashback_rate, "score": result.score})
    return refunds
