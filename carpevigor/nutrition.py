"""What a dish brings, from USDA FoodData Central: calories, protein, fat, saturated fat, carbohydrate, fiber, sugars
and sodium, per serving.

FoodData Central is the US Department of Agriculture's food composition database, public domain (CC0 1.0); USDA asks
to be credited as the source. We use its SR Legacy release (about 7,800 generic foods, values per 100 g), kept on disk
so any recipe can be counted without a network or a key.

Models do not make up numbers here. A dish is a list of ingredients with their raw weight in grams; each ingredient is
matched to one FoodData Central food, picked by a model among the candidates the local index finds (or none: then it
is left out and the screen says so), and plain code scales that food's values per 100 g. Raw weights, raw values:
cooking changes a dish's weight, not what is in it.

    python -m carpevigor.nutrition fetch                 # once: download SR Legacy, build data/fdc/fdc.sqlite
    python -m carpevigor.nutrition "chicken breast"      # what the index finds for a name
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import sys
import threading
import zipfile
from pathlib import Path

import requests
from pydantic import BaseModel, Field

from . import config, llm

DIR = config.DATA / "fdc"
DB = DIR / "fdc.sqlite"
MATCHES = DIR / "matches.json"   # ingredient name -> fdc_id (0: nothing in the database fits), decided once
SOURCE = "USDA FoodData Central (SR Legacy)"
SR_LEGACY = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip"
# our key -> FoodData Central nutrient id
NUTRIENTS = {"kcal": 1008, "protein_g": 1003, "fat_g": 1004, "sat_fat_g": 1258, "carbs_g": 1005, "fiber_g": 1079,
             "sugars_g": 2000, "sodium_mg": 1093}
STOPWORDS = {"and", "or", "the", "with", "for", "fresh", "low", "free", "added", "no", "salt", "sodium", "plain",
             "extra", "large", "small", "medium", "whole", "chopped", "sliced", "diced", "cooked", "raw", "peeled"}


class Nutrition(BaseModel):
    """Per serving. Filled by code from FoodData Central, never by a model."""
    kcal: float = 0
    protein_g: float = 0
    fat_g: float = 0
    sat_fat_g: float = 0
    carbs_g: float = 0
    fiber_g: float = 0
    sugars_g: float = 0
    sodium_mg: float = 0
    counted: list[str] = Field(default_factory=list, description="'150 g chicken breast → Chicken, broilers..., raw'")
    left_out: list[str] = Field(default_factory=list, description="Ingredients no FoodData Central food fits")
    sodium_at_most: bool = False  # a low-sodium ingredient was counted as the regular version: sodium is an upper bound
    source: str = SOURCE


# -- the local database -------------------------------------------------------------------------------------------
def build(zip_path: Path, db_path: Path = DB) -> int:
    """SR Legacy's CSV zip -> one SQLite file: each food with its values per 100 g and a full-text index of names."""
    zf = zipfile.ZipFile(zip_path)
    def rows(name: str):
        member = next(n for n in zf.namelist() if n.endswith("/" + name) or n == name)
        return csv.DictReader(io.TextIOWrapper(zf.open(member), encoding="utf-8"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    cols = ", ".join(f"{k} REAL" for k in NUTRIENTS)
    con.execute(f"CREATE TABLE food (fdc_id INTEGER PRIMARY KEY, description TEXT, {cols})")
    con.execute("CREATE VIRTUAL TABLE food_fts USING fts5(description, content='food', content_rowid='fdc_id')")
    foods = {int(r["fdc_id"]): r["description"] for r in rows("food.csv")}
    by_id = {v: k for k, v in NUTRIENTS.items()}
    values: dict[int, dict[str, float]] = {}
    for r in rows("food_nutrient.csv"):
        key = by_id.get(int(r["nutrient_id"]))
        if key and r["amount"]:
            values.setdefault(int(r["fdc_id"]), {})[key] = float(r["amount"])
    con.executemany(f"INSERT INTO food VALUES (?, ?, {', '.join('?' for _ in NUTRIENTS)})",
                    [(i, d, *(values.get(i, {}).get(k, 0.0) for k in NUTRIENTS)) for i, d in foods.items()])
    con.execute("INSERT INTO food_fts(rowid, description) SELECT fdc_id, description FROM food")
    con.commit()
    con.close()
    return len(foods)


def fetch() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DIR / SR_LEGACY.rsplit("/", 1)[-1]
    if not zip_path.exists():
        r = requests.get(SR_LEGACY, timeout=120)
        r.raise_for_status()
        zip_path.write_bytes(r.content)
    return build(zip_path)


_local = threading.local()


def _db() -> sqlite3.Connection | None:
    if not DB.exists():
        return None
    con = getattr(_local, "con", None)
    if con is None or getattr(_local, "path", None) != DB:
        _local.con, _local.path = sqlite3.connect(DB), DB
    return _local.con


def available() -> bool:
    return DB.exists()


def candidates(name: str, k: int = 8) -> list[tuple[int, str]]:
    """The foods whose description shares the most words with the name; raw foods first among equals."""
    con = _db()
    words = [w for w in re.findall(r"[a-z]{3,}", name.lower()) if w not in STOPWORDS]
    if con is None or not words:
        return []
    query = " OR ".join(f"{w}*" for w in words)
    found = con.execute("SELECT f.fdc_id, f.description FROM food_fts JOIN food f ON f.fdc_id = food_fts.rowid "
                        "WHERE food_fts MATCH ? ORDER BY bm25(food_fts) LIMIT 40", (query,)).fetchall()
    def score(row):
        d = row[1].lower()
        return (-sum(w in d for w in words), "raw" not in d, len(d))
    return sorted(found, key=score)[:k]


def per100(fdc_id: int) -> dict[str, float]:
    con = _db()
    row = con.execute(f"SELECT description, {', '.join(NUTRIENTS)} FROM food WHERE fdc_id = ?", (fdc_id,)).fetchone()
    return {"description": row[0], **dict(zip(NUTRIENTS, row[1:]))}


# -- matching names to foods ------------------------------------------------------------------------------------
class Pick(BaseModel):
    name: str = Field(description="The ingredient name exactly as given")
    fdc_id: int = Field(description="The id of the candidate that IS this ingredient, raw; 0 if none of them is")
    search_instead: str = Field(default="", description="Only when fdc_id is 0: the generic words the database would "
                                                        "use for this food, e.g. 'pasta dry' for spaghetti")


class Picks(BaseModel):
    picks: list[Pick]


PICK = """You match recipe ingredients to entries of the USDA FoodData Central database (SR Legacy). For each \
ingredient you get candidate entries (id: description). Pick the entry that is the same food, raw or as bought (dry \
pasta, dry lentils, canned beans when canned). The database uses generic names: cannellini are 'Beans, white', a stock \
is 'Soup, ... broth', pecorino romano is 'Cheese, romano'. When the ingredient says 'low sodium' or 'no salt added' \
and only the regular version is listed, pick the regular one. If no candidate is the same food, answer 0 and give \
search_instead: the words the database would use, as 'beans white canned' or 'soup vegetable broth'. Never pick a \
different food because it is similar."""
# The ingredient asks for less salt than the entry counted: its sodium is shown as an upper bound
_LESS_SALT = re.compile(r"low[- ]sodium|no salt|unsalted|salt[- ]free|reduced sodium", re.I)
_ENTRY_LESS_SALT = re.compile(r"low sodium|no salt|without salt|unsalted|reduced sodium", re.I)

_matches_lock = threading.Lock()


def _load_matches() -> dict[str, int]:
    return json.loads(MATCHES.read_text(encoding="utf-8")) if MATCHES.exists() else {}


def match(names: list[str]) -> dict[str, int]:
    """Ingredient name -> fdc_id, 0 when nothing fits. Decided once per name and kept: the same name always counts
    the same. The model only chooses among the candidates found; an id it was not offered is refused."""
    with _matches_lock:
        known = _load_matches()
        wanted = [n for n in dict.fromkeys(n.strip().lower() for n in names) if n and n not in known]
        # a name with no entry found is asked too: the model may know the words the database uses for it
        to_ask = {n: candidates(n) for n in wanted}
        # two rounds: the names as written, then, for those nothing fitted, the generic words the model suggests
        # ('spaghetti' -> 'pasta dry'); in both the model can only choose among real entries
        for _ in range(2):
            if not to_ask:
                break
            task = "\n\n".join(f"INGREDIENT: {n}\n" + ("\n".join(f"{i}: {d}" for i, d in c) or "(no entries found)")
                               for n, c in to_ask.items())
            picks = {p.name.strip().lower(): p for p in llm.ask(PICK, task, Picks, tier="mid").picks}
            retry = {}
            for n, c in to_ask.items():
                p = picks.get(n)
                known[n] = p.fdc_id if p and p.fdc_id in {i for i, _ in c} else 0
                if not known[n] and p and p.search_instead.strip():
                    more = candidates(p.search_instead)
                    if more:
                        retry[n] = more
            to_ask = retry
        if wanted:
            MATCHES.parent.mkdir(parents=True, exist_ok=True)
            MATCHES.write_text(json.dumps(known, indent=1, sort_keys=True), encoding="utf-8")
        return {n.strip().lower(): known.get(n.strip().lower(), 0) for n in names}


def _mock_picks(task: str) -> Picks:
    """No model: the first candidate offered for each ingredient (the index's best guess)."""
    picks = []
    for block in task.split("\n\n"):
        lines = block.splitlines()
        if lines and lines[0].startswith("INGREDIENT: ") and len(lines) > 1 and lines[1][:1].isdigit():
            picks.append(Pick(name=lines[0][len("INGREDIENT: "):], fdc_id=int(lines[1].split(":", 1)[0])))
    return Picks(picks=picks)


llm.mock_answers.setdefault("Picks", _mock_picks)


# -- adding up ------------------------------------------------------------------------------------------------------
def count(items: list[tuple[str, float]], servings: float = 1) -> Nutrition | None:
    """(ingredient name, raw grams for the whole dish) -> values per serving. None without the local database."""
    if not available():
        return None
    ids = match([n for n, _ in items])
    total = {k: 0.0 for k in NUTRIENTS}
    counted, left_out = [], []
    sodium_upper = False
    for name, grams in items:
        fdc_id = ids.get(name.strip().lower(), 0)
        if not fdc_id or grams <= 0:
            if grams > 0 and "water" not in name.lower():
                left_out.append(name)
            continue
        food = per100(fdc_id)
        for k in NUTRIENTS:
            total[k] += food[k] * grams / 100
        saltier = bool(_LESS_SALT.search(name)) and not _ENTRY_LESS_SALT.search(food["description"])
        if saltier:
            sodium_upper = True
        counted.append(f"{grams:g} g {name} → {food['description']}" + (" (regular version: its sodium is counted)"
                                                                         if saltier else ""))
    each = max(servings, 1)
    return Nutrition(**{k: round(v / each, 1) for k, v in total.items()}, counted=counted, left_out=left_out,
                     sodium_at_most=sodium_upper)


def for_recipes(recipes: list) -> None:
    """Sets `nutrition` on each recipe (planner.Recipe), per serving. A dish made from another's leftovers gets the
    values of a serving of that dish. Ingredients without a weight are left out and named."""
    by_meal = {f"{r.day} {r.meal}".lower(): r for r in recipes}
    for r in recipes:
        if not r.from_leftovers:
            r.nutrition = count([(i.name, i.grams) for i in r.ingredients], r.servings)
    for r in recipes:
        if r.from_leftovers:
            source = by_meal.get(r.from_leftovers.strip().lower())
            r.nutrition = source.nutrition if source is not None else None


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        print(f"{fetch()} foods in {DB}")
    else:
        for name in sys.argv[1:]:
            print(name)
            for i, d in candidates(name):
                print(f"   {i}: {d}")
