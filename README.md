# Carpe Vigor

*Care that pays you back.*

Tell it what your doctor said. It plans your week, checks what you have at home, buys only what you need
within the grocery budget you authorized once with PayPal, and if you do your part it pays a share of what
you spent back to you.

Entry for the **PayPal AI Hackathon** (Devpost, November 2026). Work in progress until 12 November.

## The loop

1. **My doctor said** — in your own words: "high blood pressure, less salt, lose a few pounds, walk more". Food,
   movement, sleep and habits are what the app plans for. Medicines, diagnoses and test values stay with your
   doctor; if you mention them, the app hands them back.
2. **The week** — 14 meals written for the kitchen device you have, each with a *why* (tied to your goals) and an
   *evidence* line (what a named public source says on average). A **review board** of five language models reads
   every sentence against MedlinePlus, WHO, NHS and AHA before you see it: three fact jurors on three different
   models, a safety reviewer that blocks anything clinical, a clarity reviewer.
3. **Home** — tick what's in the pantry. What doesn't fit the plan is not thrown away: *finish it, don't rebuy it*,
   and a swap is proposed (butter → olive oil).
4. **The agent's cart** — the recipes minus what's at home, swaps applied, never over budget. You authorize the
   week's budget **once** with PayPal (the money is held, not charged); each order is captured against it; the
   remainder is released at the end of the week.
5. **The reward** — up to 10% of the week's grocery spend comes back, through PayPal, for what you **did**: meals
   cooked, days you moved (steps from a watch), the "don't rebuy" list kept out of the cart. Never for weight.

Budget · spent · released · paid back is shown on every screen.

## PayPal

- Orders API v2, intent `AUTHORIZE`, on the weekly budget; `POST /v2/payments/authorizations/{id}/capture` per order
  with `final_capture=false`; `void` releases the remainder; the reward is a partial `refund` of the week's captures.
- Known limit, by design: PayPal guarantees capture for 3 days (honor period) of the 29-day authorization. A weekly
  budget is authorized on shopping day; longer plans would use a saved payment method.
- Sandbox only. With no credentials the app runs in **mock** mode and says so on every screen.

## Run it

    python -m venv .venv && .venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\python -m pip …
    cp .env.example .env                                                 # optional: PayPal sandbox, Google Cloud project
    python -m pytest tests/ -q                                           # offline, no keys
    python -m carpevigor.sources fetch                                   # once: the public source texts
    python -m uvicorn app:app --port 8080                                # http://127.0.0.1:8080

Without `.env` everything is simulated (demo plan, simulated board, mock PayPal) and labelled as such. With
`GOOGLE_CLOUD_PROJECT` set, the plan is written by Gemini on Vertex AI and the board gives real verdicts.

## Models and services

Gemini 2.5 Pro / Flash / Flash-Lite on Google Vertex AI (plan writer and the three fact jurors on three different
models; safety and clarity reviewers on Pro). Optional: Amazon Nova via Strands Agents on Bedrock, the stack the
review board was first built on in *Carpe Class* (Amazon Developer Hackathon, October 2026). PayPal REST sandbox.
A mock grocery catalog (`data/catalog.json`); a real deployment plugs a retailer API or a Channel3 catalog.

## What it is not

Carpe Vigor is educational. Its reviewers are language models reading public sources: they are not health
professionals and the app does not replace your doctor. It never interprets lab values, never mentions
medicines, never predicts your own numbers, and never rewards weight loss.

## Who pays the reward

In this demo, the platform. In the product, whoever gains when people do their part: an employer inside its
welfare plan, an insurer, a retailer whose basket becomes weekly and loyal. B2C by subscription or per week, also
via app stores (groceries are physical goods, outside in-app purchase rules); B2B2C through corporate welfare and
insurers; retailers as cart partners.

## License

AGPL-3.0. © 2026 Alessandro Benzia.
