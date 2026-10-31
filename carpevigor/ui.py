"""The interface's own words, in American English and Italian.

The app speaks English to the hackathon's judges by default; the IT button translates the interface (menus, headings,
buttons). What the models write (recipes, the board's verdicts, the sources) stays in English until the Italian version
(after 12 Nov 2026), whose sources are already prepared (sources.TOPICS_IT).
"""
from __future__ import annotations

LANGS = ("en", "it")

# key: (English, Italian)
TEXT = {
    # the journey, as the rail lists it: (path, icon, key)
    "journey": ("My journey", "Il mio percorso"),
    "doctor": ("What my doctor said", "Il mio medico ha detto"),
    "week": ("My week", "La mia settimana"),
    "recipes": ("Diet & recipes", "Dieta e ricette"),
    "pantry": ("Fridge & pantry", "Frigo e dispensa"),
    "shop": ("Groceries", "La spesa"),
    "move": ("Movement", "Movimento"),
    "body": ("My body · 3D", "Il mio corpo · 3D"),
    "diary": ("What I ate", "Cosa ho mangiato"),
    "progress": ("Measures & progress", "Misure e progressi"),
    "team": ("The team", "Il team"),
    "reward": ("My reward", "Il mio premio"),
    "ledger": ("Ledger", "Registro"),
    "ask": ("Ask the sources", "Chiedi alle fonti"),
    # the frame
    "tagline": ("Your health, one step at a time", "Dalla tua salute, un passo alla volta"),
    "landing": ("Main website", "Pagina iniziale"),
    "your_journey": ("Your journey", "Il tuo percorso"),
    "more": ("More", "Altro"),
    "rail_title": ("One team. One plan.", "Una squadra, un solo piano."),
    "rail_text": ("Your clinician sets health goals. Carpe Vigor organizes everyday habits around you.",
                  "Il tuo medico definisce gli obiettivi clinici. Carpe Vigor organizza le abitudini intorno a te."),
    "budget": ("budget", "budget"), "spent": ("spent", "speso"), "released": ("released", "rilasciato"),
    "paid_back": ("paid back", "restituito"),
    "disclaimer": ("Carpe Vigor talks about food, movement and habits in general terms and quotes public sources. Its "
                   "reviewers are language models reading those sources: they are not health professionals, and this "
                   "app does not replace your doctor. Anything about medicines, diagnoses or your own test results "
                   "belongs to your doctor.",
                   "Carpe Vigor parla di cibo, movimento e abitudini in termini generali e cita fonti pubbliche. I suoi "
                   "revisori sono modelli linguistici che leggono quelle fonti: non sono professionisti della salute e "
                   "questa app non sostituisce il medico. Farmaci, diagnosi e i tuoi esami restano al tuo medico."),
    "start_over": ("start over", "ricomincia"),
    "interface_only": ("Interface in Italian; recipes and sources in English until the Italian version.",
                       "Interfaccia in italiano; ricette e fonti in inglese fino alla versione italiana."),
}

NAV = [("/journey", "⌂", "journey"), ("/doctor", "✎", "doctor"), ("/week", "▦", "week"), ("/recipes", "✳", "recipes"),
       ("/home", "⌑", "pantry"), ("/cart", "⌗", "shop"), ("/move", "↗", "move"), ("/body", "◌", "body"),
       ("/diary", "☰", "diary"), ("/numbers", "⌁", "progress"), ("/team", "◉", "team"), ("/reward", "☆", "reward")]
MORE = [("/ledger", "≡", "ledger"), ("/ask", "?", "ask")]


def lang_of(value: str | None) -> str:
    return value if value in LANGS else "en"


def t(key: str, lang: str = "en") -> str:
    en, it = TEXT.get(key, (key, key))
    return it if lang == "it" else en
