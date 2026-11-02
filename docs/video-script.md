# Demo video script: DRAFT for Ale

Target 2:50 (Devpost limit to check: usually 3:00). Narration in English, about 330 words: Gemini TTS (voice
Algieba) reads them in about 2:05, leaving time for screens with no voice. `scripts/narrate.py` makes it. Screen recording of the real app
on the PC (sandbox PayPal, real Gemini), cut where the app waits. Times below are a guide: the audio sets them.
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
| 0:00 | Landing page, slogan "Care that pays you back" | After a check-up, most of us leave with a few sentences. Less salt. More vegetables. Walk more. Then nothing changes. |
| 0:08 | `/doctor` with the doctor's words typed in | Carpe Vigor turns what your doctor said into a week: meals to cook, movement to do, and a cart with only what's missing. |
| 0:18 | `/cart`, the PayPal button | You authorize the week's budget once with PayPal. It's held, not spent. |
| 0:24 | `/reward` | Do your part, and part of it comes back. For what you did. Never for what the scale says. |

## 0:30–1:10 · From the doctor's words to the week

| Time | Screen | Voice |
|---|---|---|
| 0:30 | `/doctor`, press the button; cut the wait (about 3 minutes in reality) | I type what my doctor said. Gemini turns it into guidance for food, movement and sleep. Medicines and diagnoses stay with the doctor. |
| 0:42 | `/team`, the review board | Before I see the plan, a board of AI reviewers checks it: three fact jurors, on three Gemini models, against public sources, and a safety reviewer that blocks anything clinical. |
| 0:55 | `/week` then one `/recipes/<n>` card | Fourteen meals as recipe cards for the machine I own (a Thermomix, an Instant Pot, an air fryer), each step checked against what it can really do, with USDA nutrition data. |

## 1:10–2:00 · Home, cart, PayPal

| Time | Screen | Voice |
|---|---|---|
| 1:10 | `/home`, tick a few items | I check off what I already have at home. |
| 1:16 | `/cart` | The agent buys only what the recipes need. Plain code picks the items and the prices. The AI writes the words. It never spends the money. |
| 1:28 | PayPal sandbox approval window | I authorize the budget once. PayPal holds it. |
| 1:36 | Order placed; header "budget · spent · released · paid back" | Each order is captured against that one authorization: in this run, 106 dollars and 39 cents. At the end of the week, the rest is released. |

## 2:00–2:35 · The reward and the daily life

| Time | Screen | Voice |
|---|---|---|
| 2:00 | `/reward` | At the end of the month, up to twenty percent of what I spent comes back: half for the basket PayPal verified, the rest for the days I moved and the meals I cooked. |
| 2:12 | Refund confirmed | Paid back through PayPal's MCP server: 16 dollars and 96 cents, in about eight seconds. |
| 2:20 | Phone page `/m`, say "an apple"; then `/diary` | During the week, I just tell my phone what I ate. |
| 2:28 | `/numbers`, a lab report being read (invented report, never Ale's) | And if I want, the app reads my lab report and shows each value next to my doctor's target. Judging it stays with the doctor. |

## 2:35–2:50 · Close

| Time | Screen | Voice |
|---|---|---|
| 2:35 | Landing, logo | Carpe Vigor. Your doctor's advice, turned into seven days you can live. Care that pays you back. |
| 2:45 | Repository link, AGPL-3.0 | Open source. Built on PayPal and Google Gemini. |

---

## Recording notes (for Ale)

- Record each section separately and join them: the plan takes about 3 minutes to build, so it must be cut.
- Start from a clean week (`/reset`) and prepare the doctor's words in advance: invented, never your own.
- The lab report in the video is the invented PDF used in the tests, never your real one.
- Hide the address bar if it shows the tunnel address or a token; the phone page shows the Siri header: do not film the "Siri & Apple Watch" box open.
- Voice: Gemini TTS (`gemini-3.8-flash-tts`) on Vertex AI, the same family Carpe Class used; male, deep (Ale, 2 Nov).
  Voice name: to choose among Algenib, Gacrux, Orus, Algieba, Charon. One file per row, so a line can be redone alone.
- Machines named as examples only (Ale, 2 Nov): Thermomix, Instant Pot, air fryer, the ones `kitchen.py` really models.
  In the US the Thermomix is sold as Thermomix (Bimby is the Italian name) and is far less common than the Instant Pot.
