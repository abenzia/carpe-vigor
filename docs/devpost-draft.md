# Devpost texts: DRAFT for Ale to read and change

Written by the terminal Claude on 1 Nov 2026, night. Every number here was read back from a real run (sandbox PayPal,
real Gemini); anything not yet verified is marked. Not submitted anywhere.

## Name

Carpe Vigor: care that pays you back

## Elevator pitch (200 characters max)

Tell it what your doctor said. It plans a week of meals and movement, buys only what's missing within a budget you
authorize once with PayPal, and pays part of it back when you do your part.

## About the project

### Inspiration

After a check-up most people leave with a few sentences: less salt, more vegetables, walk more, lose a few kilos.
Then nothing happens, because turning those sentences into a week of meals, a shopping list and a habit is work.
Carpe Vigor does that work, and spends your grocery money only within a limit you set.

The question underneath is one every payment company now faces: how do you let an agent spend for a person without
letting it spend too much? Our answer is a limit the person sets once, held by PayPal, that the agent can only capture
against, and a rule a person can read for what goes in the cart.

### Who it's for, and who pays

- Nearly half of US adults have high blood pressure (48.1%, 119.9 million), and about 1 in 4 of them has it under
  control (CDC, NHANES 2017–March 2020). 115.2 million US adults have prediabetes (CDC). For both, what a doctor asks
  first is the same few sentences about food and movement.
- The person pays for their own groceries, as they do today; the agent only stops them buying what the week does not
  need. The reward is meant to be paid by whoever gains when people stay well: an employer's wellness plan, a health
  insurer, or the grocer that keeps the customer. That is our plan, not something we have tested with a payer yet.

### What it does

1. **What my doctor said.** You type the doctor's words. The app turns them into guidance for food, movement and
   sleep. Anything about medicines or a diagnosis is set apart for the doctor, never acted on.
2. **Your measures, if you want.** Height, weight, age, test results, even a lab report read from a photo. The app
   computes BMI and daily energy with named public formulas and quotes what public sources say. It never judges the
   numbers: the doctor does.
3. **The week.** 14 meals written as recipe cards for the way the person cooks (a multicooker, a pressure cooker, an
   air fryer, the oven), every machine step checked by code against that machine's real limits, each with
   USDA FoodData Central nutrition, plus a movement plan that counts 150–300 minutes and two strength days from its own
   words. A board of AI reviewers checks the evidence lines against the sources before you see them.
4. **Home and cart.** You tick what you already have; the agent buys only the packs the recipes need.
5. **PayPal, once.** You authorize the week's grocery budget once. The money is held, not charged. Each order is
   captured against that hold, and the rest is released at the end of the week.
6. **The reward.** Up to 20% of the month's groceries comes back through PayPal for what you did: a healthy basket,
   days you moved, meals you cooked. Never for your weight.
7. **What I ate.** Pair your phone once with a QR code, say "a plate of cacio e pepe" and the diary counts it with
   USDA data.

### How we built it

- **Plain code decides the money.** Which items go in the cart and how much comes back are arithmetic and rules a
  person can read (`cart_agent.py`, `reward.py`). Language models write and check text; they never spend.
- **PayPal Orders v2, sandbox:** authorize once, then capture several times against one authorization, then void the
  rest. The reward is paid back as a refund, sent through PayPal's MCP server (`create_refund`).
- **Google Gemini on Vertex AI:** Gemini 3.8 Flash writes the week and reads the lab report; Gemini 4 Argon checks it.
  Three model tiers, retries on 429 and 503, every call logged.
- **USDA FoodData Central** (SR Legacy, public domain) in a local SQLite full-text index: a model can only pick among
  real foods the index returns, and code scales the values.
- **FastAPI + Jinja**, SQLite, three.js for the body view (MakeHuman CC0 models), Cloudflare Tunnel for the phone.

### A full run, read back from PayPal sandbox

- budget authorized once; USD 106.39 captured against it in orders; the rest voided (status VOIDED);
- reward of USD 16.96 refunded through the PayPal MCP server in about 8 seconds.

### Challenges

- Making recipes that a real machine can cook: code checks every step against the model's limits (a TM7 does not
  heat above speed 6) and sends a wrong recipe back once.
- Keeping the app helpful without playing doctor: no diagnosis, no medicines, no predictions about your values,
  public limits on weight goals (no faster than about 1 kg a week, calorie floors) enforced in code.
- PayPal's agent toolkit has no authorize/capture/void, so the budget hold stays on the REST API and MCP is used
  where it fits honestly: the refund.

### What's next, and the limits we know

- One merchant per budget: a PayPal authorization belongs to the payee that captures it, so the hold works when one
  grocer (or Carpe Vigor as merchant of record) fills the whole week. Several stores would need one hold each.
- PayPal guarantees an authorized amount for its 3-day honor period. Past day 3 the app reauthorizes the uncaptured
  rest before the next capture; past day 29 it asks for a new week. Tested on the simulated PayPal: the sandbox only
  allows a reauthorization from day 4.
- The basket score splits money PayPal really captured by the items the agent put in each order: PayPal confirms the
  amounts, not the items.
- A doctor's portal so the check-up verdict comes from the doctor, not the user.
- Real grocery stores instead of the demo catalog.
- Italian everywhere (today the interface is bilingual, the long texts are English).

## Built with

python, fastapi, jinja, sqlite, paypal-orders-v2, paypal-mcp, google-gemini, vertex-ai, usda-fooddata-central,
three.js, ag-grid, render, cloudflare-tunnel, pydantic, pytest

## To check before submitting (Ale)

- [x] Rules and judging criteria read (10 Nov): five equal criteria; video under 3 min, public on YouTube, no third-
      party marks; public repo with a license in the About section; a way for judges to run it (README or hosted URL).
- [ ] Testing instructions on the form: the hosted address, and a PayPal SANDBOX buyer login for the approval step.
- [ ] The repo link once it is public (11 Nov), and the video link.
- [ ] Brands: the official rules ban third-party marks in the VIDEO; the text names a machine model once, as an example
      of a limit the code checks (nominative use). Remove it if in doubt.
- [ ] Re-run the sandbox week the day before and update the two numbers above if they change.
