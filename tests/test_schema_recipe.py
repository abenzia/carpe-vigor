import json
import re

from fastapi.testclient import TestClient

from carpevigor import kitchen


def test_a_recipe_reads_as_schema_org_with_its_machine_settings_in_the_steps():
    r = {"title": "Lentil soup", "servings": 2, "prep_minutes": 10, "total_minutes": 30, "why": "Beans, no added salt.",
         "ingredients": [{"amount": "200 g", "name": "lentils", "note": "rinsed"}, "1 onion"],
         "steps": [{"text": "Place the onion in the bowl, chop.", "setting": {"time": "3 sec", "speed": "5"}},
                   {"text": "Add the lentils and water, cook", "setting": {"time": "20 min", "temperature": "100°C",
                                                                         "reverse": True, "speed": "spoon"}}]}
    s = kitchen.schema_recipe(r)
    assert s["@type"] == "Recipe" and s["recipeYield"] == "2 servings" and s["totalTime"] == "PT30M"
    assert s["recipeIngredient"] == ["200 g lentils, rinsed", "1 onion"]
    steps = [x["text"] for x in s["recipeInstructions"]]
    assert steps[0].startswith("Place the onion in the bowl, chop: 3 sec") and "100°C" in steps[1]


def test_the_recipe_page_carries_it_in_a_json_ld_script(tmp_path, monkeypatch):
    import app
    plan = {"plan": {"recipes": [{"day": "Mon", "meal": "lunch", "title": "Soup </script><b>x", "servings": 1,
                                  "ingredients": [], "steps": ["Stir."]}], "movement": []}, "cooked": []}
    monkeypatch.setattr(app, "_plan_or_start", lambda: plan)
    html = TestClient(app.app).get("/recipes/0").text
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert block and json.loads(block[1])["name"] == "Soup </script><b>x"  # escaped: the title cannot close the script


def test_the_week_s_movement_lines_call_for_their_demonstration_clips_each_once():
    from carpevigor import coach
    week = ["Mon: 30-minute brisk walk", "Tue: walk, then 2 sets of 10 wall push-ups and 10 chair sit-to-stands",
            "Thu: 10 counter push-ups and 10 bodyweight squats", "Sun: gentle stretching"]
    names = [e["name"] for e in coach.exercises_in(week)]
    assert names == ["wall_pushup", "counter_pushup", "sit_to_stand", "squat", "walk", "stretch"]
    assert coach.exercises_in([]) == [] and coach.exercises_in(["Rest day"]) == []
