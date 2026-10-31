"""Settings, all from the environment (a `.env` next to `app.py` is read if present).

Nothing here is secret by default: with no PayPal credentials the app runs in *mock* mode, where
every PayPal call is simulated locally and clearly labelled as such. Set `LLM_PROVIDER=bedrock`
and an AWS profile to use the real reviewers; `mock` answers from the bundled demo plan.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
DB_PATH = Path(os.environ.get("CARPE_DB", ROOT / "carpe_vigor.sqlite"))

# PayPal — sandbox only. Live is refused on purpose (see paypal.py).
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")
PAYPAL_MODE = os.environ.get("PAYPAL_MODE", "mock" if not PAYPAL_CLIENT_ID else "sandbox")  # mock | sandbox
PAYPAL_BASE = "https://api-m.sandbox.paypal.com"
# How the reward refund reaches PayPal: rest (the Payments API) or mcp (PayPal's MCP server, needs Node.js)
PAYPAL_REWARD_VIA = os.environ.get("PAYPAL_REWARD_VIA", "rest")
CURRENCY = os.environ.get("CURRENCY", "USD")

# The agents. Provider `vertex` = Gemini on Google Vertex AI (the default when GOOGLE_CLOUD_PROJECT is set);
# `bedrock` = Amazon Nova via Strands Agents (how the engine ran in Carpe Class); `mock` = no model, for tests and
# the credential-less demo. Three tiers, so the fact jurors are three DIFFERENT models whatever the provider.
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "vertex" if GOOGLE_CLOUD_PROJECT else "mock")  # mock | vertex | bedrock
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODELS = {
    "vertex": {"strong": os.environ.get("GEMINI_STRONG", "gemini-4-argon"),
               "mid": os.environ.get("GEMINI_MID", "gemini-3.8-flash"),
               "light": os.environ.get("GEMINI_LIGHT", "gemini-3.5-flash-lite")},
    "bedrock": {"strong": "us.amazon.nova-pro-v1:0", "mid": "us.amazon.nova-2-lite-v1:0", "light": "us.amazon.nova-lite-v1:0"},
    "mock": {"strong": "mock", "mid": "mock", "light": "mock"},
}
# Retrieval over the sources (rag.py): the board's fact jurors read the passages closest to each claim.
EMBED_MODEL = os.environ.get("GEMINI_EMBED", "gemini-embedding-2")
EMBED_DIMENSIONS = int(os.environ.get("GEMINI_EMBED_DIMENSIONS", "768"))

# Reward rules (reward.py): what a week of good behaviour pays back, as a share of what was spent.
CASHBACK_MAX = float(os.environ.get("CASHBACK_MAX", "0.20"))  # up to 20% of the grocery spend, by basket and behaviour
# Check-up bonus (checkup.py): the doctor's verdict on their goals, as a share of the spend since the last check-up
CHECKUP_BONUS = {"met": float(os.environ.get("CHECKUP_BONUS_MET", "0.05")),
                 "improving": float(os.environ.get("CHECKUP_BONUS_IMPROVING", "0.025")), "not yet": 0.0}
STEPS_GOAL = int(os.environ.get("STEPS_GOAL", "7000"))  # daily steps that count as "moved today"
