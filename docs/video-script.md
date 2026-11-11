# Demo video script: v2, health at the center (Ale, 10 Nov)

About 2:30. Narration in English, read by Gemini TTS (voice Algieba): `scripts/narrate.py` makes one file per row.
Screen recordings of the real app on a separate copy with invented data (sandbox PayPal, real Gemini), cut by
`video/rec/assemble.py` to the length of each line, with captions, motion cards and a music bed.

Ale's brief for v2 (10 Nov): the person's health is the center. Say and show the lab results, the phone and the watch
(a daily check by voice, no forms), the movement, the recipes written for the machine the person owns, and the
economic reward for healthy behavior (a discount on the shopping). PayPal is how the budget and the reward move.
Numbers said aloud are the ones read back from this run on the video copy (10 Nov): 140 authorized, 105.92 captured,
34.08 released, 17.99 paid back through the MCP server.

Opening card, no voice: "Your doctor gave you advice. Who helps you follow it, every day?"

| Time | Screen | Voice |
|---|---|---|
| 0:05 | Landing page | After a check-up you leave with a few sentences: less salt, more vegetables, walk more. Carpe Vigor turns them into your daily health plan: food, movement, and a check on how you are doing. And it pays you back when you follow it. |
| 0:20 | `/doctor`, the doctor's words typed in | Start with what your doctor said. Gemini turns it into goals for food, movement and sleep. Medicines and diagnoses stay with the doctor. |
| 0:30 | `/numbers`, an invented lab report read | Add your lab results if you want. The app reads the report, puts every value next to the target your doctor set, and the plan focuses on what is above it. Judging the numbers stays with your doctor. |
| 0:44 | `/team` | Before you see it, a board of AI reviewers checks the plan against public health sources. |
| 0:51 | `/week`, then one recipe card | Fourteen meals, written for the kitchen you have: a kitchen robot, a pressure cooker, an air fryer. Every step comes with the machine's own settings, checked by code, with USDA nutrition data. |
| 1:04 | `/move`, then `/body` | And movement made for you: a weekly plan with strength days, shown on your own body, with the steps from your watch counted every day. |
| 1:14 | Phone page `/m`: "an apple" by voice, then a photo of the plate | No forms to fill in. Tell your phone or your watch what you ate, or just snap a photo of the plate. Gemini sees the food, and USDA data counts it. A daily check that takes five seconds. |
| 1:22 | `/report`: today, this week, 30 days | And the day adds itself up. Steps and exercise minutes come from Apple Health, on your iPhone and your Apple Watch. Today, this week, this month: you see how you are doing against your goals. Keep them, and PayPal pays you back. |
| 1:26 | `/home`, then `/cart` | Then the shopping. The agent buys only what the recipes need, minus what you have at home, inside a budget you authorize once with PayPal. Plain code picks the cart: the AI writes the words, never spends the money. |
| 1:40 | PayPal sandbox approval | PayPal holds the budget. Nothing is charged yet. |
| 1:44 | Money card | Each order is captured against that one authorization: 105 dollars and 92 cents this week. The other 34 are released. The agent cannot spend a cent more. |
| 1:56 | `/reward` | And healthy habits pay. Eat well, move, cook the plan, and up to twenty percent of your groceries comes back: a discount on your shopping. |
| 2:06 | Refund card, then the ledger | Paid back through PayPal's MCP server: 17 dollars and 99 cents this month. Never for your weight. |
| 2:16 | Landing | Carpe Vigor. Your doctor's advice, lived every day, and rewarded. |
| 2:22 | End card, repository | Open source. Built on PayPal and Google Gemini. |

---

## Recording notes

- The video copy runs on its own database (`video/video.sqlite`), never Ale's: invented doctor's words, invented lab
  report (`video/rec/make_report.py`), a sandbox buyer approving in Ale's own browser.
- No third-party trademarks in the video (official rules, read 10 Nov): no machine, phone, watch or assistant brand in
  the voice or on screen. The week is recorded for the "Air fryer".
- The video copy must run WITHOUT `CARPE_HOSTED`: in hosted mode every page shows the "Public demo" notice.
- Voice: Gemini TTS (`gemini-3.8-flash-tts`) on Vertex AI, voice Algieba (Ale, 2 Nov). Music: Lyria on Vertex
  (`video/rec/music.py`).
