"""PayPal, in two roles: the agent's grocery budget and the reward.

Budget — the person authorizes the week's grocery budget ONCE (Orders API, intent AUTHORIZE: the
money is held, nothing is charged). When the agent places an order, that order's amount is captured
against the authorization (`final_capture=false`: more orders may follow). At the end of the week
the remainder is voided and goes back to the person. Known limit, stated in the README: PayPal
guarantees capture for 3 days (the honor period) of the 29-day authorization, so a weekly budget
is authorized on shopping day; a longer plan needs a saved payment method instead.

Reward — the share of the week's spend that good behaviour earned (reward.py) is returned as a
partial refund of the month's captures. Sandbox refunds are instant. With PAYPAL_REWARD_VIA=mcp the refund
goes through PayPal's MCP server (paypal_mcp.py) instead of the REST call; the amount is decided here either way.
Each refund carries our own invoice_id, so a refund whose answer was lost can be found again on the order.

Modes: `sandbox` (real PayPal sandbox API, credentials from .env) or `mock` (no network: a local
ledger behaves like the API, every id prefixed `MOCK-`). Live PayPal is refused on purpose: this
is a hackathon entry, not a payment product.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import requests

from . import config, paypal_mcp


class PayPalError(RuntimeError):
    """`sent`: the request may have reached PayPal although no answer came back, so the money may have moved."""

    def __init__(self, message: str, sent: bool = False):
        super().__init__(message)
        self.sent = sent


@dataclass
class Authorization:
    order_id: str
    authorization_id: str
    amount: float
    currency: str
    captured: float = 0.0
    voided: bool = False
    captures: list[dict] = field(default_factory=list)
    approve_url: str = ""

    @property
    def remaining(self) -> float:
        return round(self.amount - self.captured, 2)


class MockPayPal:
    """Behaves like the sandbox for the calls we use, without the network. For tests and credential-less demos."""

    mode = "mock"

    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.authorizations: dict[str, dict] = {}
        self.captures: dict[str, dict] = {}
        self.refunds: list[dict] = []

    def create_order(self, amount: float, currency: str, description: str, return_url: str, cancel_url: str) -> dict:
        oid = f"MOCK-ORD-{uuid.uuid4().hex[:10].upper()}"
        self.orders[oid] = {"id": oid, "status": "CREATED", "amount": round(amount, 2), "currency": currency, "description": description}
        return {"id": oid, "status": "CREATED", "approve_url": f"{return_url}?token={oid}&mock=1"}

    def authorize_order(self, order_id: str) -> dict:
        order = self.orders.get(order_id)
        if not order:
            raise PayPalError(f"unknown order {order_id}")
        aid = f"MOCK-AUTH-{uuid.uuid4().hex[:10].upper()}"
        self.authorizations[aid] = {"id": aid, "order": order_id, "amount": order["amount"], "currency": order["currency"],
                                    "captured": 0.0, "status": "CREATED"}
        order["status"] = "COMPLETED"
        return {"authorization_id": aid, "amount": order["amount"], "currency": order["currency"]}

    def capture(self, authorization_id: str, amount: float, note: str, final: bool = False) -> dict:
        auth = self.authorizations.get(authorization_id)
        if not auth:
            raise PayPalError(f"unknown authorization {authorization_id}")
        if auth["status"] == "VOIDED":
            raise PayPalError("AUTHORIZATION_VOIDED")
        if round(auth["captured"] + amount, 2) > round(auth["amount"] * 1.15, 2):
            raise PayPalError("MAX_CAPTURE_AMOUNT_EXCEEDED")
        cid = f"MOCK-CAP-{uuid.uuid4().hex[:10].upper()}"
        auth["captured"] = round(auth["captured"] + amount, 2)
        auth["status"] = "CAPTURED" if final else "PARTIALLY_CAPTURED"
        self.captures[cid] = {"id": cid, "authorization": authorization_id, "amount": round(amount, 2), "note": note, "refunded": 0.0}
        return {"capture_id": cid, "status": "COMPLETED", "amount": round(amount, 2)}

    def reauthorize(self, authorization_id: str, amount: float) -> dict:
        auth = self.authorizations.get(authorization_id)
        if not auth or auth["status"] == "VOIDED":
            raise PayPalError(f"no live authorization {authorization_id}")
        aid = f"MOCK-AUTH-{uuid.uuid4().hex[:10].upper()}"
        self.authorizations[aid] = {**auth, "id": aid, "amount": round(amount, 2), "captured": 0.0, "status": "CREATED"}
        return {"authorization_id": aid, "status": "CREATED"}

    def void(self, authorization_id: str) -> dict:
        auth = self.authorizations.get(authorization_id)
        if not auth:
            raise PayPalError(f"unknown authorization {authorization_id}")
        auth["status"] = "VOIDED"
        return {"status": "VOIDED", "released": round(auth["amount"] - auth["captured"], 2)}

    def refund(self, capture_id: str, amount: float, note: str, invoice_id: str = "") -> dict:
        cap = self.captures.get(capture_id)
        if not cap:
            raise PayPalError(f"unknown capture {capture_id}")
        if round(cap["refunded"] + amount, 2) > cap["amount"]:
            raise PayPalError("REFUND_EXCEEDS_CAPTURE")
        rid = f"MOCK-REF-{uuid.uuid4().hex[:10].upper()}"
        cap["refunded"] = round(cap["refunded"] + amount, 2)
        self.refunds.append({"id": rid, "capture": capture_id, "amount": round(amount, 2), "note": note, "invoice_id": invoice_id})
        return {"refund_id": rid, "status": "COMPLETED", "amount": round(amount, 2), "via": "mock"}

    def find_refund(self, order_id: str, invoice_id: str) -> dict | None:
        r = next((r for r in self.refunds if invoice_id and r["invoice_id"] == invoice_id), None)
        return {"refund_id": r["id"], "status": "COMPLETED", "amount": r["amount"], "via": "mock"} if r else None


class SandboxPayPal:
    """The real PayPal sandbox through the REST API (Orders v2 and Payments v2)."""

    mode = "sandbox"

    def __init__(self, client_id: str, secret: str, base: str = config.PAYPAL_BASE):
        if "sandbox" not in base:
            raise PayPalError("Carpe Vigor talks to the PayPal sandbox only.")
        self.base, self.auth = base, (client_id, secret)
        self._token = None

    def _headers(self) -> dict:
        if not self._token:
            r = requests.post(f"{self.base}/v1/oauth2/token", auth=self.auth, data={"grant_type": "client_credentials"}, timeout=30)
            if r.status_code >= 400:
                raise PayPalError(f"token: {r.status_code} {r.text[:200]}")
            self._token = r.json()["access_token"]
        # Prefer: without it captures and refunds come back minimal (id, status), with no amount.
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json", "PayPal-Request-Id": str(uuid.uuid4()),
                "Prefer": "return=representation"}

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            r = requests.request(method, f"{self.base}{path}", headers=self._headers(), json=body, timeout=30)
        except requests.RequestException as error:  # sent, no answer: a POST may have moved money
            raise PayPalError(f"{method} {path}: no answer ({type(error).__name__})", sent=method != "GET") from error
        if r.status_code == 401:  # token expired: once more with a fresh one
            self._token = None
            r = requests.request(method, f"{self.base}{path}", headers=self._headers(), json=body, timeout=30)
        if r.status_code >= 400:
            raise PayPalError(f"{method} {path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.text else {}

    def create_order(self, amount: float, currency: str, description: str, return_url: str, cancel_url: str) -> dict:
        order = self._call("POST", "/v2/checkout/orders", {
            "intent": "AUTHORIZE",
            "purchase_units": [{"description": description[:127], "amount": {"currency_code": currency, "value": f"{amount:.2f}"}}],
            "application_context": {"return_url": return_url, "cancel_url": cancel_url, "user_action": "CONTINUE",
                                    "brand_name": "Carpe Vigor", "shipping_preference": "NO_SHIPPING"},
        })
        approve = next((l["href"] for l in order.get("links", []) if l["rel"] == "approve"), "")
        return {"id": order["id"], "status": order["status"], "approve_url": approve}

    def authorize_order(self, order_id: str) -> dict:
        done = self._call("POST", f"/v2/checkout/orders/{order_id}/authorize")
        auth = done["purchase_units"][0]["payments"]["authorizations"][0]
        return {"authorization_id": auth["id"], "amount": float(auth["amount"]["value"]), "currency": auth["amount"]["currency_code"]}

    def capture(self, authorization_id: str, amount: float, note: str, final: bool = False) -> dict:
        cap = self._call("POST", f"/v2/payments/authorizations/{authorization_id}/capture", {
            "amount": {"currency_code": config.CURRENCY, "value": f"{amount:.2f}"},
            "final_capture": final, "note_to_payer": note[:255]})
        # The money has moved once PayPal answers: never fail here for a missing field, or the capture goes unrecorded.
        return {"capture_id": cap["id"], "status": cap["status"], "amount": float((cap.get("amount") or {}).get("value", amount))}

    def reauthorize(self, authorization_id: str, amount: float) -> dict:
        """After the 3-day honor period (days 4 to 29) the hold is renewed for what is still uncaptured; the answer's id
        is the authorization later captures and the void go to (PayPal Payments v2, read 10 Nov 2026)."""
        auth = self._call("POST", f"/v2/payments/authorizations/{authorization_id}/reauthorize",
                          {"amount": {"currency_code": config.CURRENCY, "value": f"{amount:.2f}"}})
        return {"authorization_id": auth["id"], "status": auth.get("status", "")}

    def void(self, authorization_id: str) -> dict:
        self._call("POST", f"/v2/payments/authorizations/{authorization_id}/void")
        state = self._call("GET", f"/v2/payments/authorizations/{authorization_id}")
        return {"status": state.get("status", "VOIDED"), "released": None}

    def refund(self, capture_id: str, amount: float, note: str, invoice_id: str = "") -> dict:
        if config.PAYPAL_REWARD_VIA == "mcp":
            self._headers()  # a valid token for the MCP server; the secret stays in this process
            try:
                return {**paypal_mcp.refund(self._token, capture_id, amount, config.CURRENCY, note, invoice_id), "via": "mcp"}
            except paypal_mcp.McpError as error:
                raise PayPalError(str(error), sent=error.sent) from error
        body = {"amount": {"currency_code": config.CURRENCY, "value": f"{amount:.2f}"}, "note_to_payer": note[:255]}
        if invoice_id:
            body["invoice_id"] = invoice_id
        ref = self._call("POST", f"/v2/payments/captures/{capture_id}/refund", body)
        return {"refund_id": ref["id"], "status": ref["status"], "amount": amount, "via": "rest"}

    def find_refund(self, order_id: str, invoice_id: str) -> dict | None:
        """The refund with our invoice_id on this order, if PayPal made it: for a refund whose answer was lost."""
        order = self._call("GET", f"/v2/checkout/orders/{order_id}")
        for unit in order.get("purchase_units", []):
            for r in (unit.get("payments") or {}).get("refunds", []):
                if r.get("invoice_id") == invoice_id:
                    return {"refund_id": r["id"], "status": r.get("status", ""),
                            "amount": float((r.get("amount") or {}).get("value", 0)), "via": "found on the order"}
        return None


_client = None


def client():
    """The one PayPal client of the process: sandbox when credentials are set, mock otherwise."""
    global _client
    if _client is None:
        if config.PAYPAL_MODE == "sandbox" and config.PAYPAL_CLIENT_ID:
            _client = SandboxPayPal(config.PAYPAL_CLIENT_ID, config.PAYPAL_CLIENT_SECRET)
        else:
            _client = MockPayPal()
    return _client


def use(new_client):
    """Tests swap the client in."""
    global _client
    _client = new_client
