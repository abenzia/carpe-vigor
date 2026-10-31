"""Retrieval over the public sources: the fact jurors read the passages closest to each claim, not every page.

The sources (sources.py) are cut into passages of about CHUNK characters along paragraph breaks, and each passage
gets a vector from Gemini (config.EMBED_MODEL, gemini-embedding-2). The index is a JSON file next to the texts,
local like them, rebuilt when a source changes. For a list of claims, each claim's K closest passages among the
sources of the plan's topics are put together, by source, headed by the source's name and URL as before.

If embedding fails, the jurors get the full texts, and the report says so: a slower check, never a blind one.
"""
from __future__ import annotations

import json
import math
import re

from . import config, llm, sources

CHUNK = 900
K = 3
INDEX = sources.DIR / "index.json"
_cache: tuple = (None, {})  # ((path, mtime), index) of the last index read or written


def chunks(text: str) -> list[str]:
    """Paragraphs merged up to about CHUNK characters; a paragraph longer than that is cut at sentence ends."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    out, current = [], ""
    for p in paragraphs:
        for piece in ([p] if len(p) <= CHUNK else re.split(r"(?<=[.!?])\s+", p)):
            if current and len(current) + len(piece) > CHUNK:
                out.append(current)
                current = ""
            current = f"{current}\n\n{piece}".strip()
    if current:
        out.append(current)
    return out


def _source_ids(topic_keys: list[str]) -> list[dict]:
    seen, out = set(), []
    for key in topic_keys:
        for src in sources.TOPICS[key]["sources"]:
            if src["id"] not in seen:
                seen.add(src["id"])
                out.append(src)
    return out


def _passages(src: dict) -> list[str]:
    text = sources.text_of(src["id"])
    if not text:
        return []
    body = text.split("\n\n", 1)[1] if "\n\n" in text else text  # drop the name/URL header: it is added back
    return chunks(body)


def index(srcs: list[dict]) -> dict:
    """The vectors of every passage of these sources, from the saved index where a source has not changed."""
    global _cache
    path = INDEX
    model = config.EMBED_MODEL if llm.provider() == "vertex" else "mock"
    stamp = (str(path), path.stat().st_mtime) if path.exists() else None
    if stamp and _cache[0] == stamp:
        saved = _cache[1]  # read once, kept in memory until the file changes
    else:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if saved.get("model") != model:
        saved = {"model": model, "sources": {}}
    changed = False
    for src in srcs:
        passages = _passages(src)
        entry = saved["sources"].get(src["id"])
        if not passages or (entry and entry["passages"] == passages):
            continue
        vectors = [[round(x, 5) for x in v] for v in llm.embed(passages, "RETRIEVAL_DOCUMENT")]
        saved["sources"][src["id"]] = {"passages": passages, "vectors": vectors}
        changed = True
    if changed:
        path.write_text(json.dumps(saved), encoding="utf-8")
    _cache = ((str(path), path.stat().st_mtime) if path.exists() else None, saved)
    return saved


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def everything() -> list[dict]:
    """Every source of every topic, plus the MedlinePlus library: what a free question is searched against."""
    topical = _source_ids(list(sources.TOPICS))
    urls = {s["url"].rstrip("/").lower() for s in topical}
    extra = [s for s in sources.library() if s["url"].rstrip("/").lower() not in urls]  # a page already a topic source
    return [s for s in topical + extra if sources.text_of(s["id"])]


def quotes(question: str, topic_keys: list[str] | None = None, k: int = 2, srcs: list[dict] | None = None) -> list[dict]:
    """The k passages closest to a question, among the topics' sources (or `srcs`), to quote word for word with the
    source's name. Empty if retrieval is not possible: the screen says so, nothing is made up."""
    srcs = srcs if srcs is not None else [s for s in _source_ids(topic_keys or []) if sources.text_of(s["id"])]
    try:
        idx = index(srcs)
        q = llm.embed([question], "RETRIEVAL_QUERY")[0]
    except Exception:
        return []
    scored = sorted(((_cosine(q, vec), src, i) for src in srcs
                     for i, vec in enumerate(idx["sources"].get(src["id"], {}).get("vectors", []))),
                    key=lambda t: t[0], reverse=True)
    out, seen = [], set()
    for _, src, i in scored:
        text = idx["sources"][src["id"]]["passages"][i]
        if text in seen:  # the same MedlinePlus page can be both a topic source and a library topic
            continue
        seen.add(text)
        out.append({"name": src["name"], "url": src["url"], "text": text})
        if len(out) == k:
            break
    return out


def reference(claims: list[str], topic_keys: list[str], k: int = K) -> tuple[str, dict]:
    """The reference text the fact jurors read for these claims, and how it was made (for the board's report)."""
    srcs = [s for s in _source_ids(topic_keys) if sources.text_of(s["id"])]
    try:
        idx = index(srcs)
        queries = llm.embed(claims, "RETRIEVAL_QUERY") if claims else []
    except Exception as error:  # the board still checks, against everything: slower, never blind
        full, _ = sources.reference_for(topic_keys)
        return full, {"mode": "full texts", "chars": len(full),
                      "note": f"Retrieval failed ({type(error).__name__}: {str(error)[:120]}); the jurors read the full sources."}
    picked: dict[tuple[str, int], float] = {}
    for q in queries:
        scored = [(_cosine(q, vec), src["id"], i) for src in srcs
                  for i, vec in enumerate(idx["sources"].get(src["id"], {}).get("vectors", []))]
        for score, sid, i in sorted(scored, reverse=True)[:k]:
            picked[(sid, i)] = max(score, picked.get((sid, i), 0.0))
    parts = []
    for src in srcs:
        mine = sorted(i for sid, i in picked if sid == src["id"])
        if mine:
            body = "\n\n[…]\n\n".join(idx["sources"][src["id"]]["passages"][i] for i in mine)
            parts.append(f"SOURCE: {src['name']}\nURL: {src['url']}\n\n{body}")
    text = "\n\n".join(parts)
    return text, {"mode": "retrieved", "model": idx["model"], "passages": len(picked), "chars": len(text), "per_claim": k}
