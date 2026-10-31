# CLAUDE.md — Carpe Vigor

Entry for the PayPal AI Hackathon (Devpost, deadline 12 Nov 2026, 12:00 PST = 21:00 Italy). One person
(Alessandro "Ale" Benzia), two Claudes: the cloud session writes code and the plan; the terminal
session on Ale's PC runs it with his keys and fixes what breaks. `PIANO.md` is the shared to-do: read it
first, update it when you finish or discover something, commit it.

## What this is

"Tell it what your doctor said; it plans your week, checks what you have at home, buys only what you
need within the budget you authorized once with PayPal, and if you do your part it pays a share back."
Five screens, one loop: `/doctor` → `/week` → `/home` → `/cart` → `/reward`. Educational, never medical.

## Rules that are not negotiable

- **Not a doctor, but a real help** (Ale, 31 Oct 2026). The app does not diagnose, does not mention or adjust
  medicines, and does not predict the person's own values ("your pressure will…" is wrong, whoever asked for it).
  If the person CHOOSES to enter their test results (`checkup.py`), the app keeps them, shows them back next to the
  target THEIR DOCTOR set, quotes what the public sources say about each measure (retrieved, with the source's
  name), and lets "above the doctor's target" steer what the week's plan focuses on. Judging the numbers stays
  with the doctor. Entering results is optional: without them the app works on the doctor's words and the cart.
- **Reward what people do; outcomes only as the doctor judges them.** `reward.py` scores the basket (verified by
  PayPal), days moved and meals cooked. The only outcome that pays is the check-up bonus: the doctor's verdict on
  the goals they set (met / improving / not yet), never a single number read by the app, never weight alone.
- **PayPal sandbox only.** `paypal.py` refuses live. Credentials in `.env`, never in code or commits.
- **No personal data in the repo.** No real lab values, no real names, no files from Segnavia. The repo goes
  public under AGPL-3.0 on 11 Nov.
- **Plain code decides the money.** Which items go in the cart and what the cashback is are arithmetic and rules
  (`cart_agent.py`, `reward.py`), readable by a person. Models write and check text; they do not spend.
- **Surgical changes.** Touch what the task needs. Keep the style. Do not refactor what is not broken; if
  something else looks wrong, write it in `PIANO.md` under "Trovato", do not fix it in passing.

## Layout

- `app.py` — FastAPI, the five screens, `/api/state` for debugging
- `carpevigor/` — `config` `llm` (vertex | bedrock | mock) `profile` `planner` `review_board` `sources` `catalog`
  `pantry` `cart_agent` `paypal` `week` `reward` `store`
- `data/catalog.json` mock store · `data/demo_plan.json` the plan the mock serves · `data/sources/` fetched source texts
- `templates/` Jinja, `static/style.css` (Segnavia look: CAI blaze, Barlow Condensed, carta/nebbia)
- `tests/` — `pytest tests/` must stay green; it runs with no network and no keys

## Run

    py -3.12 -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt
    copy .env.example .env          # fill PayPal sandbox + GOOGLE_CLOUD_PROJECT
    .venv\Scripts\python -m pytest tests/ -q
    .venv\Scripts\python -m carpevigor.sources fetch      # once, with internet
    .venv\Scripts\python -m uvicorn app:app --reload --port 8080

Providers: `LLM_PROVIDER=mock` runs with no model (demo plan + simulated board, said so in the UI).
`vertex` needs `gcloud auth application-default login` and a project with Vertex AI enabled.
