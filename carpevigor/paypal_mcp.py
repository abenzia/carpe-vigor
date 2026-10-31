"""The month's reward goes back through PayPal's own MCP server (`@paypal/mcp`, the PayPal Agent Toolkit).

Plain code still decides the money: week.settle_month picks the captures and the amounts. This module only carries
each refund to PayPal through the toolkit's `create_refund` tool, so the payout uses PayPal's agent interface,
the same one an assistant would be given, with the amount fixed before any model or tool sees it.

Why only the refund: the toolkit has no authorization, authorization capture or void, which the weekly budget needs.
Those stay on the REST API (paypal.py).

The server is PayPal's npm package, pinned, started with `npx` for each refund. It gets a short-lived access
token, never the client secret, and the sandbox environment. Needs Node.js.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil

PACKAGE = "@paypal/mcp@1.8.1"
TIMEOUT = 120  # seconds: the first run downloads the package


class McpError(RuntimeError):
    """The MCP call failed. `sent` says whether the request may have reached PayPal (then reconcile before retrying)."""

    def __init__(self, message: str, sent: bool):
        super().__init__(message)
        self.sent = sent


def available() -> bool:
    return shutil.which("npx") is not None


def refund(token: str, capture_id: str, amount: float, currency: str, note: str, invoice_id: str) -> dict:
    """One refund through the `create_refund` tool: {"refund_id", "status", "amount"}."""
    try:
        return asyncio.run(asyncio.wait_for(_refund(token, capture_id, amount, currency, note, invoice_id), TIMEOUT))
    except McpError:
        raise
    except Exception as error:  # a crash or timeout after the call was sent: PayPal may have refunded
        raise McpError(f"PayPal MCP server: {type(error).__name__}: {str(error)[:200]}", sent=True) from error


async def _refund(token, capture_id, amount, currency, note, invoice_id) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    npx = shutil.which("npx")
    if not npx:
        raise McpError("Node.js (npx) is not installed: the PayPal MCP server cannot start.", sent=False)
    env = {**os.environ, "PAYPAL_ACCESS_TOKEN": token, "PAYPAL_ENVIRONMENT": "SANDBOX"}
    for secret in ("PAYPAL_CLIENT_SECRET", "PAYPAL_CLIENT_ID"):  # the server needs the token only
        env.pop(secret, None)
    params = StdioServerParameters(command=npx, args=["-y", PACKAGE, "--tools=all"], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("create_refund", {
            "capture_id": capture_id, "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
            "invoice_id": invoice_id, "note_to_payer": note[:255]})
    text = "".join(getattr(c, "text", "") for c in result.content)
    if result.is_error:  # PayPal answered and said no: nothing was refunded
        raise McpError(f"PayPal refused the refund: {text[:300]}", sent=False)
    try:
        ref = json.loads(text)
    except ValueError as error:
        raise McpError(f"Unreadable answer from the PayPal MCP server: {text[:200]}", sent=True) from error
    if "id" not in ref:
        raise McpError(f"PayPal answered without a refund id: {text[:300]}", sent=True)
    return {"refund_id": ref["id"], "status": ref.get("status", ""), "amount": amount}
