"""The public sources every health sentence is checked against.

Only named, public, authoritative pages: MedlinePlus (US National Library of Medicine), the World
Health Organization, the NHS, the American Heart Association, the Dietary Guidelines for Americans.
The pages are fetched once (`python -m carpevigor.sources fetch`) and kept as plain text in
`data/sources/`, so the board checks against the same words every time and the repo carries no
copyrighted PDF. Each topic lists its sources; a plan's "why" and "evidence" lines cite one of them.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

import requests

from . import config

DIR = config.DATA / "sources"

# AHA's 2022 presidential advisory on the eight cardiovascular health metrics, open access in PubMed Central: the
# definitions of the metrics (diet, activity, sleep, weight...) and the sleep section, not the whole 53,000 characters.
AHA_LE8 = {"id": "aha-le8", "name": "American Heart Association — Life's Essential 8 (Circulation, 2022)",
           "url": "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001078",
           "fetch": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=10503546&tool=carpevigor",
           "keep": ["UPDATED DEFINITIONS", "SLEEP HEALTH"]}

TOPICS: dict[str, dict] = {
    "blood_pressure": {
        "label": "Blood pressure and sodium",
        "match": ["pressure", "hypertens", "sodium", "salt"],
        "sources": [
            {"id": "who-sodium", "name": "WHO — Sodium reduction (fact sheet)", "url": "https://www.who.int/news-room/fact-sheets/detail/sodium-reduction"},
            {"id": "medlineplus-hbp", "name": "MedlinePlus — High blood pressure: lifestyle changes", "url": "https://medlineplus.gov/ency/article/007484.htm"},
            {"id": "nhs-hbp", "name": "NHS — High blood pressure: prevention", "url": "https://www.nhs.uk/conditions/high-blood-pressure-hypertension/prevention/"},
            {"id": "aha-sodium", "name": "American Heart Association — How much sodium should I eat per day?", "url": "https://www.heart.org/en/healthy-living/healthy-eating/eat-smart/sodium/how-much-sodium-should-i-eat-per-day"},
        ],
    },
    "cholesterol": {
        "label": "Cholesterol and fats",
        "match": ["cholesterol", "ldl", "lipid", "saturated"],
        "sources": [
            {"id": "medlineplus-chol", "name": "MedlinePlus — How to lower cholesterol with diet", "url": "https://medlineplus.gov/howtolowercholesterolwithdiet.html"},
            {"id": "aha-fats", "name": "American Heart Association — Saturated fat", "url": "https://www.heart.org/en/healthy-living/healthy-eating/eat-smart/fats/saturated-fats"},
            AHA_LE8,
        ],
    },
    "weight": {
        "label": "Weight and healthy eating",
        "match": ["weight", "obes", "kilo", "pound", "bmi", "waist"],
        "sources": [
            {"id": "who-diet", "name": "WHO — Healthy diet (fact sheet)", "url": "https://www.who.int/news-room/fact-sheets/detail/healthy-diet"},
            {"id": "medlineplus-weight", "name": "MedlinePlus — Weight control", "url": "https://medlineplus.gov/weightcontrol.html"},
            {"id": "aha-diet", "name": "American Heart Association — Diet and lifestyle recommendations", "url": "https://www.heart.org/en/healthy-living/healthy-eating/eat-smart/nutrition-basics/aha-diet-and-lifestyle-recommendations"},
        ],
    },
    "activity": {
        "label": "Physical activity",
        "match": ["exercise", "activity", "walk", "steps", "sedentary", "move"],
        "sources": [
            {"id": "who-activity", "name": "WHO — Physical activity (fact sheet)", "url": "https://www.who.int/news-room/fact-sheets/detail/physical-activity"},
            AHA_LE8,
        ],
    },
    "fiber": {
        "label": "Fiber, whole grains and legumes",
        "match": ["fiber", "fibre", "whole grain", "legume", "constipation"],
        "sources": [
            {"id": "medlineplus-fiber", "name": "MedlinePlus — Dietary fiber", "url": "https://medlineplus.gov/dietaryfiber.html"},
        ],
    },
    "sugar": {
        "label": "Sugar and sweet drinks",
        "match": ["sugar", "glucose", "diabet", "soda", "sweet"],
        "sources": [
            {"id": "who-sugar", "name": "WHO — Healthy diet (fact sheet), free sugars", "url": "https://www.who.int/news-room/fact-sheets/detail/healthy-diet"},
        ],
    },
}

CLINICAL = ["medicat", "medicine", "drug", "dose", "prescri", "stop taking", "insulin", "statin", "diagnos", "mg/dl", "mmol"]


def topics_for(text: str) -> list[str]:
    """The topics a free-text 'what my doctor said' touches. Order = order in TOPICS."""
    low = text.lower()
    return [key for key, topic in TOPICS.items() if any(m in low for m in topic["match"])] or ["weight", "activity"]


def mentions_clinical(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in CLINICAL)


def path_for(source_id: str) -> Path:
    return DIR / f"{source_id}.txt"


def text_of(source_id: str) -> str | None:
    p = path_for(source_id)
    return p.read_text(encoding="utf-8") if p.exists() else None


def reference_for(topic_keys: list[str]) -> tuple[str, list[dict]]:
    """The reference text the board reads for these topics (every fetched source, headed by name and URL), and the
    list of sources it is made of, with `fetched` saying whether the text is on disk."""
    parts, used = [], []
    for key in topic_keys:
        for src in TOPICS[key]["sources"]:
            body = text_of(src["id"])
            used.append({**src, "topic": key, "fetched": body is not None})
            if body:
                parts.append(f"SOURCE: {src['name']}\nURL: {src['url']}\n\n{body}")
    return "\n\n".join(parts), used


def fetch(source_id: str | None = None, timeout: int = 30) -> list[str]:
    """Download the sources as plain text. Run on a machine with internet; the texts stay local (gitignored).

    A source may name a `fetch` address for machines (a paper's open-access copy in PubMed Central, read through
    NCBI's official API) and the `keep` sections worth citing. A site that blocks scripts (heart.org answers 403)
    is not worked around: a person saves the page as `<id>.html` in data/sources and it is read from there."""
    seen: set[str] = set()
    DIR.mkdir(parents=True, exist_ok=True)
    done = []
    for topic in TOPICS.values():
        for src in topic["sources"]:
            if (source_id and src["id"] != source_id) or src["id"] in seen:
                continue
            seen.add(src["id"])
            saved = DIR / f"{src['id']}.html"
            try:
                r = requests.get(src.get("fetch", src["url"]), timeout=timeout, headers={"User-Agent": "CarpeVigor/0.1 (PayPal AI Hackathon entry)"})
                r.raise_for_status()
                body, how = (sections(r.text, src["keep"]) if "keep" in src else plain(r.text)), ""
            except requests.RequestException as e:
                if not saved.exists():
                    print(f"FAILED {src['id']}: {e} — save the page by hand as {saved} and run fetch again", file=sys.stderr)
                    continue
                body, how = plain(saved.read_text(encoding="utf-8", errors="replace")), " (page saved by hand: the site blocks scripts)"
            path_for(src["id"]).write_text(f"{src['name']}\n{src['url']}{how}\n\n{body}", encoding="utf-8")
            done.append(src["id"])
    return done


def sections(xml: str, keep: list[str]) -> str:
    """From a paper in JATS XML (PubMed Central), the sections whose title starts with one of `keep`, as plain text."""
    out = []
    for m in re.finditer(r"<sec[^>]*>\s*<title>(.*?)</title>(.*?)(?=<sec[^>]*>\s*<title>|</body>)", xml, re.S):
        title = plain(m.group(1))
        if any(title.upper().startswith(k.upper()) for k in keep):
            out.append(f"{title}\n\n{plain(m.group(2))}")
    return "\n\n".join(out)


def plain(page: str) -> str:
    """The readable text of an HTML page: scripts, styles and tags gone, entities decoded, whitespace folded."""
    page = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html.unescape(page)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", page)).strip()


def status() -> list[dict]:
    return [{**src, "topic": key, "fetched": path_for(src["id"]).exists()} for key, t in TOPICS.items() for src in t["sources"]]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        print("\n".join(fetch(sys.argv[2] if len(sys.argv) > 2 else None)))
    else:
        print(json.dumps(status(), indent=2))
