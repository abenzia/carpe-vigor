"""A photo of each dish of the week, drawn once by the image model from the recipe's title and ingredients.

It is an illustration of the recipe, not a picture of the person's food, and the page says so. One image per title,
kept on disk (static/dishes, not published), so a week costs about fourteen images once and nothing when a title comes
back. With no image model (mock mode, tests) or when the model fails, there is no photo and the card keeps its tile.
"""
import hashlib
import threading
import time
from pathlib import Path

from . import config

FOLDER = Path(__file__).resolve().parent.parent / "static" / "dishes"
MODEL = "gemini-3.1-flash-image"
_lock = threading.Lock()
_drawing = False


def path(recipe: dict) -> Path:
    return FOLDER / hashlib.sha1(recipe["title"].strip().lower().encode()).hexdigest()[:16]  # PNG or JPEG, as it came


def media_type(file: Path) -> str:
    with file.open("rb") as f:
        return "image/png" if f.read(4)[1:] == b"PNG" else "image/jpeg"  # a PNG starts with byte 0x89, then "PNG"


def prompt(recipe: dict) -> str:
    shown = [i["name"] for i in recipe.get("ingredients", []) if i.get("grams") and i["name"].lower() != "water"][:8]
    return (f"Overhead food photograph of a home-cooked plate: {recipe['title']}. Ingredients that should be visible: "
            f"{', '.join(shown)}. One serving on a plain ceramic plate, on a light wooden table, natural daylight, "
            "realistic, appetizing but honest portion. No text, no logos, no hands, no people.")


def existing(recipe: dict) -> Path | None:
    out = path(recipe)
    return out if out.exists() else None


def draw_week(recipes: list[dict]) -> None:
    """Draws the missing photos one at a time in the background (the image model takes only a few a minute).
    One drawer at a time: a page asking again while it works changes nothing."""
    global _drawing
    if config.LLM_PROVIDER != "vertex":
        return
    with _lock:
        if _drawing:
            return
        _drawing = True
    threading.Thread(target=_draw_all, args=([r for r in recipes if not existing(r)],), daemon=True).start()


def _draw_all(todo: list[dict]) -> None:
    global _drawing
    try:
        for recipe in todo:
            for attempt in range(5):
                try:
                    _draw(recipe)
                    break
                except Exception as error:  # the card keeps its tile; the log says why
                    if "429" not in str(error) or attempt == 4:
                        print(f"dish photo for {recipe['title']!r} not drawn: {str(error)[:200]}")
                        break
                    time.sleep(20 * (attempt + 1))  # the per-minute quota: wait and try again
    finally:
        with _lock:
            _drawing = False


def _draw(recipe: dict) -> None:
    from google.genai import types
    from . import llm
    got = llm._client().models.generate_content(
        model=MODEL, contents=prompt(recipe), config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],  # a JPEG of about 300 KB: the default PNG is 1.8 MB
            image_config=types.ImageConfig(aspect_ratio="4:3", output_mime_type="image/jpeg",
                                           output_compression_quality=75)))
    for part in got.candidates[0].content.parts if got.candidates else []:
        if part.inline_data:
            out = path(recipe)
            FOLDER.mkdir(parents=True, exist_ok=True)
            out.with_suffix(".part").write_bytes(part.inline_data.data)
            out.with_suffix(".part").replace(out)
            return
    print(f"dish photo for {recipe['title']!r}: the model sent no image")
