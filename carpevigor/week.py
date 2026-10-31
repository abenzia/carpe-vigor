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
    store.log("released", {"released": auth["released"], "authorization_id": auth["authorization_id"]})
    return auth


def month(store: Store) -> dict:
    """The weeks closed since the last payment, each with its captures and what it earned, plus check-up bonuses."""
    m = store.get("month") or {"weeks": []}
    m.setdefault("bonuses", [])
    m["earned"] = round(sum(w["earned"] for w in m["weeks"]) + sum(b["earned"] for b in m["bonuses"]), 2)
    m["spent"] = round(sum(w["spent"] for w in m["weeks"]), 2)
    return m


def add_checkup_bonus(store: Store, verdict: str, spent_since_last: float, earned: float) -> dict:
    """The doctor's verdict at a check-up adds its bonus to the month: paid with the rest on its last day."""
    m = store.get("month") or {"weeks": []}
    entry = {"verdict": verdict, "spent": spent_since_last, "earned": earned}
    m.setdefault("bonuses", []).append(entry)
    store.put("month", m)
    store.log("checkup_bonus", entry)
    return entry


def close_week(store: Store, result: reward.Reward) -> dict:
    """At the end of the week (after the remainder is released) its reward goes into the month: nothing is paid yet."""
    auth = store.get("authorization") or {}
    m = store.get("month") or {"weeks": []}
    if any(w["authorization_id"] == auth.get("authorization_id") for w in m["weeks"]):
        raise paypal.PayPalError("This week is already closed.")
    spent = round(sum(c["amount"] for c in store.get("captures", [])), 2)
    entry = {"authorization_id": auth.get("authorization_id"), "spent": spent, "earned": result.cashback,
             "rate": result.cashback_rate, "score": result.score, "reasons": result.reasons,
             "captures": [{"capture_id": c["capture_id"], "amount": c["amount"], "refunded": c.get("refunded", 0.0)}
                          for c in store.get("captures", [])]}
    m["weeks"].append(entry)
    store.put("month", m)
    store.log("week_closed", {k: entry[k] for k in ("authorization_id", "spent", "earned", "rate", "score")})
    return entry


def settle_month(store: Store) -> list[dict]:
    """End of the month: what the closed weeks earned is refunded across the month's captures, largest first, up to
    each capture's amount (PayPal refunds a capture for 180 days, a month is well inside). Then a new month starts."""
    m = month(store)
    left = m["earned"]
    if left <= 0:
        raise paypal.PayPalError("Nothing earned this month yet: close a week first.")
    captures = [c for w in m["weeks"] for c in w["captures"]]
    paid_now = []
    for cap in sorted(captures, key=lambda c: -c["amount"]):
        if left <= 0:
            break
        room = round(cap["amount"] - cap.get("refunded", 0.0), 2)
        if room <= 0:
            continue
        amount = min(left, room)
        ref = paypal.client().refund(cap["capture_id"], amount, "Carpe Vigor reward: you did your part this month")
        cap["refunded"] = round(cap.get("refunded", 0.0) + amount, 2)
        paid_now.append({"refund_id": ref["refund_id"], "capture_id": cap["capture_id"], "amount": amount})
        left = round(left - amount, 2)
    store.put("refunds", store.get("refunds", []) + paid_now)
    # `unpaid` > 0 only if the month's captures had less room than it earned (e.g. a bonus with few orders): said, kept
    store.put("month", {"weeks": [], "bonuses": [], "last_paid": {"weeks": len(m["weeks"]), "spent": m["spent"],
                                                                  "paid": round(m["earned"] - left, 2), "unpaid": left}})
    store.log("reward_paid", {"cashback": round(m["earned"] - left, 2), "weeks": len(m["weeks"]), "refunds": paid_now})
    return paid_now


def ledger(store: Store) -> list[dict]:
    """Every money movement of the week, oldest first, one row each, with the PayPal id a judge can look up in the
    sandbox dashboard. Built from the week log, so it is what actually happened, in order."""
    rows = []
    for e in reversed(store.events()):
        if e["kind"] == "authorized":
            rows.append({"at": e["at"], "what": "Budget held", "paypal_id": e["authorization_id"], "amount": e["amount"],
                         "effect": "held", "note": f"held, not charged · order {e['order_id']}"})
        elif e["kind"] == "captured":
            rows.append({"at": e["at"], "what": "Order captured", "paypal_id": e["capture_id"], "amount": e["amount"],
                         "effect": "charged", "note": e.get("note", "")})
        elif e["kind"] == "released":
            rows.append({"at": e["at"], "what": "Remainder released", "paypal_id": e.get("authorization_id", ""),
                         "amount": e["released"], "effect": "back to you", "note": "authorization voided"})
        elif e["kind"] == "reward_paid":
            for r in e.get("refunds", []):
                rows.append({"at": e["at"], "what": "Reward paid back", "paypal_id": r["refund_id"], "amount": r["amount"],
                             "effect": "paid to you", "note": f"refund of {r['capture_id']} · the month's reward"
                                                              + (f" ({e['weeks']} week{'s' if e['weeks'] != 1 else ''})" if e.get("weeks") else "")})
        elif e["kind"] == "checkup_bonus":
            rows.append({"at": e["at"], "what": "Check-up bonus", "paypal_id": "", "amount": e["earned"], "effect": "earned",
                         "note": f"your doctor: goals {e['verdict']} · on {e['spent']:.2f} spent since the last check-up · "
                                 "paid at the end of the month"})
        elif e["kind"] == "week_closed":
            rows.append({"at": e["at"], "what": "Week closed", "paypal_id": e.get("authorization_id") or "", "amount": e["earned"],
                         "effect": "earned", "note": f"{round(e['rate'] * 100, 1)}% of {e['spent']:.2f} · score "
                                                     f"{round(e['score'] * 100)}/100 · paid at the end of the month"})
    return rows
