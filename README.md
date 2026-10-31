# Carpe Vigor

*Care that pays you back.*

Tell it what your doctor said. It plans your week, checks what you have at home, buys only what you need
within the grocery budget you authorized once with PayPal, and if you do your part it pays a share of what
you spent back to you.

Entry for the **PayPal AI Hackathon** (Devpost, November 2026).

## The loop

1. **My doctor said**: in your own words, for example "high blood pressure, less salt, lose a few pounds, walk
   more". The app plans food, movement, sleep and habits. A question about medicines or a diagnosis is set
   apart for your doctor.
2. **The week**: 14 meals for the number of people you cook for, written for the kitchen device you have, plus a
   movement line for each day. Each meal has a *why* line (what is in the dish) and an *evidence* line (what a named
   public source says, on average).
   - **Laid out like a Thermomix recipe card**: prep and total time, difficulty, accessories, ingredients with how
     they go in, numbered steps whose machine setting (time / temperature or Varoma / reverse / speed) is data, not
     prose, and tips. The content is the planner's, written for this person's week.
   - **What each dish brings**, per serving: calories, protein, fiber, saturated fat and sodium, from **USDA
     FoodData Central** (SR Legacy, public domain), kept on disk (`python -m carpevigor.nutrition fetch`). Each
     ingredient has its raw weight; a model picks the matching FoodData Central food among real candidates the local
     index finds (it cannot offer one of its own), and plain code scales the values per 100 g. A low-sodium product the
     database lists only in its regular version is counted as the regular one and the sodium is shown as "≤". A table
     adds up each day's lunch and dinner. Calories are shown, never set as a target: that is the doctor's.
   - **Recipes that work on your machine.** For a Thermomix (TM7, TM6, TM5, TM31) the planner gets that model's
     limits from Vorwerk's published specs: a TM31 stops at 100 °C, a TM7 does not heat above speed 6. Plain code
     then reads every step: a setting the machine cannot do, a step that says "as in Monday's recipe", a dinner
     that is meant to feed tomorrow's lunch but cooks only tonight's servings. Those recipes go back to the model
     once, and whatever is still wrong is shown on the recipe, never hidden.
   - The week is planned around **ten public numbers**, each quoting its source word for word, for example
     sodium under 2,000 mg a day (WHO) and 150 to 300 minutes of moderate activity a week (US HHS).
   - A **review board** of five language-model reviewers reads the meal lines before you see them: three fact
     jurors on three different models check the evidence lines against the sources, a safety reviewer blocks
     anything clinical, and a clarity reviewer checks the wording.
3. **Home**: tick what's in the pantry. What doesn't fit the plan is not thrown away: *finish it, don't rebuy
   it*, and a swap is proposed (butter → olive oil).
4. **The agent's cart**: the recipes minus what's at home, swaps applied. Each recipe says how many grams it uses,
   so the cart buys the packs the week needs (1.2 kg of chicken in 600 g packs is two packs). You authorize the week's budget
   **once** with PayPal: the money is held, not charged. Each order is captured against that hold, and the
   remainder is released at the end of the week.
   - If the plan doesn't fit the budget, plain code trims the cart. It never cuts proteins, vegetables or
     legumes; if those alone exceed the budget, it says "raise by USD X" instead of cutting them.
5. **The reward**: up to 20% of the month's grocery spend comes back through PayPal, for what you did.

The header of every screen shows budget · spent · released · paid back. Three more pages:

- **My numbers** (optional): test results you choose to enter, shown next to the target your doctor set. A
  measure above the doctor's target makes it a focus of the next week's plan. The page also quotes what the
  public sources say about each measure. The app never judges your numbers: your doctor does.
- **What I ate**: nobody weighs what they eat, so the diary takes a sentence ("a plate of cacio e pepe"), typed or
  dictated, or sent from an iPhone or Apple Watch shortcut to `POST /api/meal` (with a secret token). A model turns it
  into the raw ingredients of a typical portion; USDA FoodData Central gives the values; the answer comes back as a
  line Siri can read ("cacio e pepe: about 572 calories, 29 grams of protein, 723 milligrams of sodium"). Meals of the
  plan marked as cooked join the day with their recipe's values. Estimates are labelled as such, there is no calorie
  target, and the diary never touches the reward.
- **Ask the sources**: a free question, answered only from passages of the public sources, each sentence citing
  its passage. The safety reviewer reads the answer before you do. If the reviewer still blocks it after one
  rewrite, you see the passages and the reason, never the answer.
- **Ledger**: every PayPal movement and every reward decision, in a sortable table (AG Grid).

## The reward: what is checked, and who checks it

| Part | Weight | Comes from | Checked by |
|---|---|---|---|
| The basket | 50% | what PayPal actually captured, item by item | **verified**: PayPal |
| Moving | 30% | days over the step goal (7,000 by default) | from your watch or phone (typed in the demo) |
| Cooking | 20% | meals ticked as cooked | **self-reported**, so it weighs least |
| Check-up bonus | +5% / +2.5% / 0 | your doctor's verdict on the goals they set: met / improving / not yet | your doctor |

- **The basket score** is the healthy share of the spend minus *twice* the junk share. Healthy means vegetables,
  legumes, fruit, fish, whole grains, white meat, eggs, olive oil and unsalted nuts; junk means sweets, snacks, cured meat, sugary drinks, saturated fat and
  anything on the "don't rebuy" list. Each dollar of junk costs twice what a dollar of vegetables earns.
- **The rate** is 20% times the week's score. A week scoring under half pays nothing.
- **Payment**: the weeks are added up and paid once a month, as partial refunds of that month's captures.
- **The check-up bonus** is a share of the grocery spend since the previous check-up, based on the doctor's
  verdict. It is the only outcome that pays, and never on a single number or on weight.
- **Gaming the self-reported parts** still only returns a share of money really spent on groceries.

The money is decided by plain code (`cart_agent.py`, `reward.py`), readable by a person. The models write and
check text; they never decide what is bought or what is paid.

**Who pays the reward.** In this demo, the platform. In the product, whoever gains when people do their part:
an employer inside its welfare plan, an insurer, or a retailer whose basket becomes weekly and loyal.

## PayPal

- **The weekly budget** uses the Orders API v2 with intent `AUTHORIZE`. Each order is a
  `POST /v2/payments/authorizations/{id}/capture` with `final_capture=false`. `void` releases the remainder, and
  the reward is a partial `refund` of the month's captures.
- **The reward goes back through PayPal's own MCP server** (`@paypal/mcp`, the PayPal Agent Toolkit), with its
  `create_refund` tool: the same interface an AI assistant would be given. Plain code fixes the capture and the
  amount before the tool is called; the server gets a short-lived access token, never the client secret.
  `PAYPAL_REWARD_VIA=rest` uses the Payments API instead. The toolkit has no authorization, capture or void, so
  the weekly budget stays on the REST API.
- **A refund is never paid twice.** Each refund is saved the moment PayPal confirms it and carries our own
  `invoice_id`. If an answer is lost, the app reads the order back and records the refund PayPal made under that
  id; a second try pays only what is still owed.
- **Verified end to end on the sandbox**: authorize USD 120, two captures (110.00 and 5.00), void, partial refund
  of 9.58. A capture after the void is refused with 422. A reward refund through the MCP server (0.50, in about
  7 seconds), found again on the order by its `invoice_id`.
- **The whole loop through the app, on the sandbox and Gemini** (31 Oct 2026): a TM7 week for one, budget USD 140
  authorized by a sandbox buyer, the agent's order of 27 items captured (106.39), the 33.61 left released, the
  week's reward (16.96, 15.9% at score 80/100) paid back with "Close the month" through PayPal's MCP server in about
  8 seconds. Read back from PayPal: authorization VOIDED, capture PARTIALLY_REFUNDED, refund COMPLETED under our
  `invoice_id`.
- **Known limit**: PayPal guarantees a capture for 3 days (the honor period) of the 29-day authorization. So the
  weekly budget is authorized on shopping day; longer plans would use a saved payment method.
- **Sandbox only**: `paypal.py` refuses live. With no credentials the app runs in mock mode and says so on
  every screen.

## The sources, and how the app uses them

**Where the texts come from.**
- *Topic sources* (`carpevigor/sources.py`): MedlinePlus, WHO, NHS, the US HHS Physical Activity Guidelines,
  and the American Heart Association, including *Life's Essential 8* (from PubMed Central).
- *The MedlinePlus library*: 284 English health topics from the official XML file (public domain), in nine
  groups: nutrition, wellness, fitness, heart, metabolism, diabetes, mental health, substances and lab tests.

**For the Italian version** (after the hackathon), `fetch` also downloads the same topics from Italian public
sources: Ministero della Salute, Istituto Superiore di Sanità (EpiCentro, ISSalute) and CREA's 2018
healthy-eating guidelines (PDF), plus seven Italian guideline numbers quoted from them. They are kept out of the
English app: an English sentence is never checked against Italian text. ISSalute does not send its full
certificate chain, so the app does not download its pages (verification stays on); those pages can be saved by
hand like the AHA ones.

**How the app finds the right passages.** The texts are cut into passages of about 900 characters and indexed
with `gemini-embedding-2` (768 dimensions) in a local JSON file. The fact jurors read the passages closest to
each claim, not whole pages. If the index fails, they read the full texts and the report says so.

**The ten numbers** (`carpevigor/guidelines.py`). Each one quotes its source's exact sentence, and
`python -m carpevigor.guidelines` checks that each sentence is still in the fetched text. A number whose source
no longer says it disappears from the page and from the planner. Where the sources disagree, both numbers are
shown: saturated fat is under 10% of calories for WHO and under 7% for MedlinePlus.

**American Heart Association pages.** heart.org refuses scripts, and the app does not work around that. A
person can save those pages from the browser as `data/sources/<id>.html`, in English: `fetch` then reads the
saved page and labels it as saved by hand. Without them, those sources are skipped and the run says so.

## Run it

    python -m venv .venv && .venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\python -m pip …
    cp .env.example .env                    # optional: PayPal sandbox, Google Cloud project
    python -m pytest tests/ -q              # offline, no keys, no network
    python -m carpevigor.sources fetch      # once, with internet: the topic sources
    python -m carpevigor.sources library    # once: the MedlinePlus library (Ask the sources, the sleep number)
    python -m carpevigor.guidelines         # each public number found in its source?
    python -m carpevigor.nutrition fetch    # once: USDA FoodData Central (SR Legacy, 6 MB) for what each dish brings
    python -m uvicorn app:app --port 8080   # http://127.0.0.1:8080

**Without `.env`** everything is simulated and labelled as such: a demo plan, a simulated board and mock
PayPal.

**With `GOOGLE_CLOUD_PROJECT` set:**
- Gemini on Vertex AI writes the plan and the board gives real verdicts. This needs
  `gcloud auth application-default login`.
- A week takes about three minutes (183 seconds measured on 31 Oct 2026): an outline, then the days written four
  at a time, one round of recipe fixes, the board and one correction round. A question to Ask the sources took 15
  to 20 seconds on the earlier Gemini 2.5 Flash.
- The first run indexes all the sources once, in about a minute and a half.

## Models and services

- **Google Vertex AI**, region `global`:
  - Gemini 4 Argon (`gemini-4-argon`) writes the plan and runs the safety and clarity reviewers;
  - the three fact jurors run on three different models: Gemini 4 Argon, Gemini 3.8 Flash and Gemini 3.5
    Flash-Lite;
  - Ask the sources answers on Gemini 3.8 Flash;
  - on Gemini 2.5 Pro, 2.5 Flash and 3.1 Flash-Lite the same week took about six minutes and the board removed
    more evidence lines; the models are set in `.env` (`GEMINI_STRONG`, `GEMINI_MID`, `GEMINI_LIGHT`);
  - retrieval uses `gemini-embedding-2`.
- **Optional**: Amazon Nova through Strands Agents on Bedrock (`LLM_PROVIDER=bedrock`). The review board was
  first built on that stack for *Carpe Class* (Amazon Developer Hackathon, October 2026).
- **PayPal** REST, sandbox, and PayPal's MCP server (`@paypal/mcp` 1.8.1, through `npx`: needs Node.js) for the
  reward.
- **Store**: a mock grocery catalog (`data/catalog.json`). A real deployment would plug in a retailer API.
- **Ledger table**: AG Grid Community, loaded from jsDelivr with integrity hashes.

## What it is not

Carpe Vigor helps people stay healthy or get back to health between visits; it does not replace the doctor.

- **Its reviewers are language models** reading public sources. They are not health professionals.
- **It never** diagnoses, mentions or adjusts medicines, or predicts a person's own values.
- **Test results are optional.** If someone enters them, the app shows them next to their doctor's target and
  quotes the sources, and judging them stays with the doctor.
- **The reward is for what people do**, plus the doctor's verdict at the check-up, never weight alone.
- **No personal data is in this repository.** The demo store is a local SQLite file, ignored by git.

## License

AGPL-3.0, full text in `LICENSE`. © 2026 Alessandro Benzia.
