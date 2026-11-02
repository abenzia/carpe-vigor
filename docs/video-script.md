# Demo video script: DRAFT for Ale

Target 2:50 (Devpost limit to check: usually 3:00). Narration in English, about 400 words at a calm pace.
Screen recording of the real app on the PC (sandbox PayPal, real Gemini), cut where the app waits.
Only "Carpe Vigor" on screen and in the voice: no other brand of ours.

The first 30 seconds carry the three things nobody else does together:
1. the doctor's words become a week of meals and a cart that buys only what is missing;
2. PayPal holds the week's budget once, and every order is captured against that hold;
3. part of the money comes back for what you did, never for your weight.

Numbers said aloud are the ones read back from the sandbox (devpost-draft.md). Re-check them the day before recording.

---

## 0:00–0:30 · The promise

| Time | Screen | Voice |
|---|---|---|
| 0:00 | Landing page, slogan "Care that pays you back" | After a check-up, most of us leave with a few sentences. Less salt. More vegetables. Walk more. And then nothing changes. |
| 0:08 | `/doctor` with the doctor's words typed in | Carpe Vigor takes what your doctor said and turns it into a week: meals you can cook, movement you can do, and a shopping cart with only what you don't already have. |
| 0:18 | `/cart`, the PayPal button | You authorize the week's grocery budget once with PayPal. The money is held, not spent. |
| 0:24 | `/reward` | And if you do your part, part of it comes back. For what you did. Never for your weight. |

## 0:30–1:10 · From the doctor's words to the week

| Time | Screen | Voice |
|---|---|---|
| 0:30 | `/doctor`, press the button; cut the wait (about 3 minutes in reality) | I type what my doctor told me. Gemini turns it into guidance for food, movement and sleep. Anything about medicines or a diagnosis is set aside for the doctor. The app never acts on it. |
| 0:42 | `/team`, the review board | Before I see the plan, a board of AI reviewers checks it. Three fact jurors, on three different Gemini models, check every claim against public sources. A safety reviewer blocks anything clinical. |
| 0:55 | `/week` then one `/recipes/<n>` card | Fourteen meals, written as recipe cards for my own kitchen machine, each with real nutrition data from the USDA. And a movement plan that reaches the 150 minutes a week public guidelines ask for. |

## 1:10–2:00 · Home, cart, PayPal

| Time | Screen | Voice |
|---|---|---|
| 1:10 | `/home`, tick a few items | I tick what I already have at home. |
| 1:16 | `/cart` | The agent buys only the packs the recipes need. Which items go in and what they cost is plain code a person can read. The models write text. They never spend. |
| 1:28 | PayPal sandbox approval window | I authorize the budget once. PayPal holds it. |
| 1:36 | Order placed; header "budget · spent · released · paid back" | Each order is captured against that one authorization. In this run, 106 dollars and 39 cents were captured, and at the end of the week the rest of the hold is released. Nothing is charged twice, nothing is charged beyond what I agreed. |

## 2:00–2:35 · The reward and the daily life

| Time | Screen | Voice |
|---|---|---|
| 2:00 | `/reward` | At the end of the month, the reward: up to twenty percent of what I really spent on groceries. Half of it comes from the basket PayPal verified, the rest from the days I moved and the meals I cooked. |
| 2:12 | Refund confirmed | It is paid back through PayPal's MCP server: 16 dollars and 96 cents, in about eight seconds. |
| 2:20 | Phone page `/m`, say "an apple"; then `/diary` | During the week I just tell my phone what I ate, and the diary counts it with USDA data. |
| 2:28 | `/numbers`, a lab report being read (invented report, never Ale's) | If I want, I add my test results, even from a photo of the lab report. The app shows them next to the targets my doctor set. Judging them stays with the doctor. |

## 2:35–2:50 · Close

| Time | Screen | Voice |
|---|---|---|
| 2:35 | Landing, logo | Carpe Vigor. Your doctor's advice, turned into a week you can live, and care that pays you back. |
| 2:45 | Repository link, AGPL-3.0 | Open source, built on PayPal and Google Gemini. |

---

## Recording notes (for Ale)

- Record each section separately and join them: the plan takes about 3 minutes to build, so it must be cut.
- Start from a clean week (`/reset`) and prepare the doctor's words in advance: invented, never your own.
- The lab report in the video is the invented PDF used in the tests, never your real one.
- Hide the address bar if it shows the tunnel address or a token; the phone page shows the Siri header: do not film the "Siri & Apple Watch" box open.
- Voice: yours, or a synthetic one. Decide before recording.
