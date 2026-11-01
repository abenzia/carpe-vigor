"""The whole loop, offline: doctor said → week → home → cart → PayPal (mock) → reward. No model, no network."""
import os

os.environ["LLM_PROVIDER"] = "mock"
os.environ["PAYPAL_MODE"] = "mock"

import pytest
from fastapi.testclient import TestClient

from carpevigor import cart_agent, paypal, reward, review_board, sources
from carpevigor.catalog import Catalog
from carpevigor.pantry import Pantry
from carpevigor.store import Store


@pytest.fixture(autouse=True)
def _no_index_in_the_repo(tmp_path, monkeypatch):
    """The retrieval index is a cache next to the real sources: tests keep theirs in a temporary folder."""
    from carpevigor import config, rag
    monkeypatch.setattr(rag, "INDEX", tmp_path / "index.json")
    # the machine's .env may send the reward through PayPal's MCP server: tests never start it (the MCP test fakes it)
    monkeypatch.setattr(config, "PAYPAL_REWARD_VIA", "rest")
    # nor the USDA database downloaded on this machine: a test that counts builds its own
    from carpevigor import nutrition
    monkeypatch.setattr(nutrition, "DB", tmp_path / "fdc.sqlite")
    monkeypatch.setattr(nutrition, "MATCHES", tmp_path / "matches.json")


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app as webapp
    webapp.store = Store(tmp_path / "t.sqlite")
    paypal.use(paypal.MockPayPal())
    return TestClient(webapp.app, headers={"Origin": "http://testserver"})  # a browser on the app's own pages


def test_paypal_mock_authorize_capture_void_refund():
    pp = paypal.MockPayPal()
    order = pp.create_order(70.0, "USD", "budget", "http://x/ok", "http://x/ko")
    auth = pp.authorize_order(order["id"])
    cap = pp.capture(auth["authorization_id"], 41.50, "order 1")
    assert cap["status"] == "COMPLETED"
    void = pp.void(auth["authorization_id"])
    assert void["released"] == 28.5
    with pytest.raises(paypal.PayPalError):
        pp.capture(auth["authorization_id"], 1.0, "after void")
    ref = pp.refund(cap["capture_id"], 4.15, "reward")
    assert ref["amount"] == 4.15
    with pytest.raises(paypal.PayPalError):
        pp.refund(cap["capture_id"], 100.0, "too much")


def test_sandbox_capture_and_refund_survive_paypals_minimal_answer(monkeypatch):
    # 31 Oct, real sandbox: the capture went through (110.00) but PayPal answered without "amount", the code raised
    # KeyError and the app never recorded money that had moved.
    pp = paypal.SandboxPayPal("id", "secret")
    monkeypatch.setattr(pp, "_call", lambda method, path, body=None: {"id": "CAP-1", "status": "COMPLETED"})
    assert pp.capture("AUTH-1", 110.0, "order")["amount"] == 110.0
    assert pp.refund("CAP-1", 8.5, "reward")["amount"] == 8.5
    monkeypatch.setattr(pp, "_token", "t")
    assert pp._headers()["Prefer"] == "return=representation"


def week(cooked=12, days=6, spent=100.0, healthy=70.0, junk=0.0):
    return reward.WeekBehaviour(planned_meals=14, cooked_meals=cooked, days_with_steps=days, spent=spent,
                                healthy_spend=healthy, unhealthy_spend=junk)


def test_reward_rewards_behaviour_not_weight():
    good = reward.score(week())
    assert good.earned and 0 < good.cashback_rate <= reward.config.CASHBACK_MAX == 0.20
    assert good.cashback == round(100 * good.cashback_rate, 2)
    assert not reward.score(week(cooked=2, days=1, healthy=20.0)).earned          # a half-hearted week pays nothing
    assert not any("weight" in p["label"].lower() or "kg" in p["label"].lower() for p in good.parts)


def test_the_basket_moves_the_rate_vegetables_up_sweets_and_bacon_down():
    plain = reward.score(week(healthy=50.0))
    greener = reward.score(week(healthy=80.0))
    with_junk = reward.score(week(healthy=50.0, junk=10.0))
    assert greener.cashback_rate > plain.cashback_rate > with_junk.cashback_rate
    # each dollar of junk costs twice what a dollar of vegetables earns
    assert round(plain.score - with_junk.score, 3) == round(2 * (reward.score(week(healthy=60.0)).score - plain.score), 3)
    perfect = reward.score(week(cooked=14, days=7, healthy=100.0))
    assert perfect.cashback_rate == 0.20                                         # the ceiling
    assert reward.basket_quality(30.0, 40.0, 100.0) == 0.0                       # never below zero


def test_each_part_of_the_reward_says_how_it_is_known():
    parts = {p["key"]: p for p in reward.score(week()).parts}
    assert parts["basket"]["source"] == "verified by PayPal" and parts["basket"]["weight"] == 0.5
    assert parts["moved"]["weight"] == 0.3 and parts["cooked"]["weight"] == 0.2
    assert parts["cooked"]["source"] == "self-reported"


def test_two_weeks_one_payment_at_the_end_of_the_month(tmp_path):
    from carpevigor import week as w
    paypal.use(paypal.MockPayPal())
    s = Store(tmp_path / "m.sqlite")
    for spent, earned in ((80.0, 9.0), (60.0, 12.0)):
        order = w.start_authorization(s, 100.0, "http://x/ok", "http://x/ko")
        w.complete_authorization(s, order["id"])
        w.capture_order(s, spent, "groceries")
        w.release_remainder(s)
        w.close_week(s, reward.Reward(score=0.7, cashback_rate=earned / spent, cashback=earned, reasons=[]))
    assert w.month(s)["earned"] == 21.0 and len(w.month(s)["weeks"]) == 2
    paid = w.settle_month(s)
    assert round(sum(p["amount"] for p in paid), 2) == 21.0
    assert len({p["capture_id"] for p in paid}) == 1           # 21 fits in the largest capture (80): one refund
    assert w.month(s)["weeks"] == [] and w.month(s)["last_paid"]["paid"] == 21.0
    with pytest.raises(paypal.PayPalError):
        w.settle_month(s)                                       # nothing left to pay


def test_catalog_says_what_is_healthy_and_what_is_junk():
    catalog = Catalog.load()
    kind = lambda name: catalog.kind(next(i for i in catalog.items.values() if i.name == name).sku)
    assert kind("Baby spinach") == kind("Salmon fillets") == kind("Dried lentils") == kind("Rolled oats") == "healthy"
    assert kind("Bacon") == kind("Potato chips") == kind("Cola, 6 cans") == kind("Butter") == "unhealthy"
    assert kind("Chicken breast") == kind("Turkey breast slices, low sodium") == kind("Eggs") == "healthy"
    assert kind("Extra-virgin olive oil") == kind("Walnuts, unsalted") == "healthy"
    assert any(i.has("sugar") and i.has("snack") for i in catalog.items.values())  # there are sweets to tempt you


def test_cart_respects_pantry_blacklist_and_budget():
    catalog = Catalog.load()
    pantry = Pantry()
    pantry.tick("DAI-BUTTER-250", "Butter")
    pantry.tick("GRA-BROWN-1K", "Brown rice")
    pantry.review(catalog, ["less saturated fat"])
    assert "DAI-BUTTER-250" in pantry.blacklist()
    recipes = [{"title": "Rice bowl", "ingredients": ["brown rice", "butter", "salmon fillets", "broccoli"]}]
    cart = cart_agent.build(recipes, pantry, catalog, budget=100.0)
    names = [l.item.name for l in cart.lines]
    assert "Brown rice" not in names                      # at home
    assert "Butter" not in names                          # don't rebuy
    assert "Extra-virgin olive oil" in names              # the swap
    assert any(l.swapped_from == "Butter" for l in cart.lines)
    tight = cart_agent.build(recipes, pantry, catalog, budget=15.0)
    # Proteins and vegetables are never cut: the extra (olive oil) goes, and what is left still costs more than 15,
    # so the cart says so and asks for a higher budget instead of dropping the salmon.
    assert "Extra-virgin olive oil" not in [l.item.name for l in tight.lines]
    assert {"Salmon fillets", "Broccoli"} <= {l.item.name for l in tight.lines}
    assert tight.over_budget and not tight.within_budget and tight.raise_by > 0


def test_cart_says_what_the_week_needs_before_cutting_and_never_cuts_protein_or_vegetables():
    catalog = Catalog.load()
    recipes = [{"title": "Bowl", "ingredients": ["salmon fillets", "baby spinach", "chickpeas", "quinoa", "black pepper",
                                                 "walnuts", "blueberries", "apple cider vinegar"]}]
    full = cart_agent.build(recipes, Pantry(), catalog, budget=500.0)
    assert not full.skipped and full.needed == full.total and full.raise_by == 0
    cart = cart_agent.build(recipes, Pantry(), catalog, budget=30.0)
    assert cart.needed == full.total and cart.raise_by == round(full.total - 30.0, 2)
    kept = {l.item.name for l in cart.lines}
    assert {"Salmon fillets", "Baby spinach", "Chickpeas, no salt added"} <= kept
    assert cart.within_budget and not cart.over_budget


def _tiny_usda(tmp_path):
    """A four-food SR Legacy zip, built into the same SQLite file as the real one."""
    import zipfile
    from carpevigor import nutrition
    foods = {1: ("Pasta, dry, enriched", {1008: 371, 1003: 13, 1093: 6}),
             2: ("Cheese, romano", {1008: 387, 1003: 32, 1258: 17, 1093: 1433}),
             3: ("Soup, vegetable broth, ready to serve", {1008: 5, 1093: 300}),
             4: ("Beans, white, mature seeds, canned", {1008: 114, 1079: 6.3, 1093: 5})}
    path = tmp_path / "sr.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("sr/food.csv", "fdc_id,data_type,description,food_category_id,publication_date\n" +
                   "".join(f'{i},sr_legacy_food,"{d}",1,2019-04-01\n' for i, (d, _) in foods.items()))
        z.writestr("sr/food_nutrient.csv", "id,fdc_id,nutrient_id,amount\n" +
                   "".join(f"{i}{n},{i},{n},{a}\n" for i, (_, v) in foods.items() for n, a in v.items()))
    assert nutrition.build(path, nutrition.DB) == 4


def test_a_dish_is_counted_from_usda_foods_and_the_model_only_picks_among_them(tmp_path, monkeypatch):
    from carpevigor import nutrition
    _tiny_usda(tmp_path)
    rounds = []

    def picker(system, task, shape, **k):
        asked = [l[len("INGREDIENT: "):] for l in task.splitlines() if l.startswith("INGREDIENT: ")]
        rounds.append(asked)
        if len(rounds) == 1:
            return nutrition.Picks(picks=[
                nutrition.Pick(name="spaghetti", fdc_id=0, search_instead="pasta dry"),   # not found as written
                nutrition.Pick(name="pecorino romano", fdc_id=2),
                nutrition.Pick(name="vegetable broth, low sodium", fdc_id=3),
                nutrition.Pick(name="mystery powder", fdc_id=1)])                          # an id it was not offered
        return nutrition.Picks(picks=[nutrition.Pick(name="spaghetti", fdc_id=1)])
    monkeypatch.setattr(nutrition.llm, "ask", picker)
    dish = [("spaghetti", 100), ("pecorino romano", 40), ("vegetable broth, low sodium", 200), ("mystery powder", 5),
            ("water", 300)]
    n = nutrition.count(dish, servings=2)
    assert rounds[1] == ["spaghetti"]                       # the second round, with the database's own words
    assert n.left_out == ["mystery powder"]                 # refused: never offered, so never counted
    assert n.kcal == round((371 + 387 * 0.4 + 5 * 2) / 2, 1) and n.sodium_mg == round((6 + 1433 * 0.4 + 300 * 2) / 2, 1)
    assert n.sodium_at_most and "regular version" in n.counted[2]   # a low-sodium broth counted as the regular one
    assert nutrition.count(dish, servings=2) == n and len(rounds) == 2  # decided once: no model the second time


def test_the_coach_is_held_to_the_activity_guidelines_by_code(monkeypatch):
    from carpevigor import coach
    lazy = coach.MovementPlan(days=[coach.Day(day=d, text="rest", moderate_minutes=10, strength=False)
                                    for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")])
    good = coach.MovementPlan(days=[coach.Day(day=d, text="25-minute brisk walk" + (", 10 squats" if d in "MonThu" else ""),
                                              moderate_minutes=25, strength=d in ("Mon", "Thu"))
                                    for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")])
    asked = []
    monkeypatch.setattr(coach.llm, "ask", lambda system, task, shape, **k: asked.append(task) or (lazy if len(asked) == 1 else good))
    lines, report = coach.plan_week(["Walk more"], "light", [4000, 5000])
    assert "0 moderate minutes" in asked[1] and "0 strength days" in asked[1]   # "rest" claims 10: the words say 0
    overclaim = coach.Day(day="Mon", text="20-minute walk", moderate_minutes=60, strength=True)
    assert coach.written(overclaim) == (20, False)                    # counted as written: 20 minutes, no strength
    assert report == {"minutes": 175, "strength_days": 2, "problems": [], "within": True, "fixed": True}
    assert lines[0] == "Mon: 25-minute brisk walk, 10 squats" and "RECENT STEPS A DAY: 4500" in asked[0]
    assert coach.areas_worked(lines[0]) == ["legs", "glutes"]


def test_the_persons_measures_give_bmi_energy_and_a_goal_estimate_inside_public_limits():
    from carpevigor import health
    man = {"height_cm": 178, "weight_kg": 92, "age": 50, "sex": "male", "activity": "light"}
    r = health.read(man)
    assert r["bmi"] == 29.0 and r["bmi_category"] == "Overweight"                      # NHLBI: 25.0-29.9
    assert r["energy"] == round((10 * 92 + 6.25 * 178 - 5 * 50 + 5) * 1.375)            # Mifflin-St Jeor x light
    goal = health.read({**man, "goal_kg": 86})
    assert goal["weeks"] == 12 and goal["pace"] == 0.5 and goal["target_kcal"] == round(r["energy"] - 550)
    fast = health.read({**man, "goal_kg": 86, "pace": 3})              # asked for 3 kg a week: held at 1 kg, and
    assert fast["target_kcal"] == 1500 and fast["pace"] == 0.87 and fast["weeks"] == 7   # then the 1,500 floor holds
    assert any("1500 kcal" in n for n in fast["notes"])
    # a small person: the 1,200 kcal floor (Harvard Health) holds, the pace slows down and the page says why
    small = health.read({"height_cm": 155, "weight_kg": 60, "age": 60, "sex": "female", "activity": "sedentary",
                         "goal_kg": 55, "pace": 1.0})
    assert small["target_kcal"] == 1200 and small["pace"] < 0.5 and any("1200 kcal" in n for n in small["notes"])
    assert "weeks" not in health.read({**man, "goal_kg": 55})                           # BMI 17.4: underweight goal
    assert "weeks" not in health.read({**man, "goal_kg": 86, "pregnant": True})
    assert "weeks" not in health.read({**man, "goal_kg": 86, "age": 16})
    doctor = health.read({**man, "goal_kg": 86, "doctor_kcal": 1900})
    assert doctor["target_kcal"] == 1900                                               # the doctor's number wins
    assert "about 1900 kcal a day" in health.for_planner({**man, "doctor_kcal": 1900})
    low = health.read({**man, "doctor_kcal": 900})                     # typed as the doctor's: under the floor
    assert low["target_kcal"] == 1500 and any("confirm" in n for n in low["notes"])
    assert "weeks" not in health.read({k: v for k, v in man.items() if k != "age"} | {"goal_kg": 86})   # age unknown
    assert health.for_planner({**man, "pregnant": True}) == ""        # no calorie number at all in pregnancy


def test_apple_health_arrives_as_an_italian_iphone_writes_it_and_only_with_consent(client, monkeypatch):
    from carpevigor import apple_health, config
    assert apple_health.integers("8.234 passi\n6,100 steps\n11 200") == [8234, 6100, 11200]
    assert apple_health.decimal("92,5 kg") == 92.5 and apple_health.decimal(["91,8", "92,1"]) == 92.1
    class Bare:
        def __init__(self): self.kv = {"health": {"consent": True}}
        def get(self, k, d=None): return self.kv.get(k, d)
        def put(self, k, v): self.kv[k] = v
    for sent_sleep in ("7,5", "450", "27000"):                         # hours, minutes or seconds: 7.5 hours
        assert apple_health.apply({"sleep_hours": sent_sleep}, Bare())["kept"]["sleep_hours"] == 7.5
    monkeypatch.setattr(config, "API_TOKEN", "s3cret-token")
    auth = {"Authorization": "Bearer s3cret-token"}
    sent = {"steps": "8.234\n6.100\n9.400\n7.300\n4.800\n11.200\n7.600", "weight_kg": "92,5 kg", "sleep_hours": "7,2",
            "resting_hr": "61 bpm", "systolic": "138", "diastolic": "500"}       # 500: no diastolic is that high
    assert client.post("/api/health", json=sent).status_code == 403                    # no token
    no_consent = client.post("/api/health", json=sent, headers=auth)
    assert no_consent.status_code == 403 and "consent" in no_consent.json()["spoken"]  # no consent: nothing kept
    client.post("/numbers/measures", data={"consent": "1", "height_cm": "178", "weight_kg": "95"})
    r = client.post("/api/health", json=sent, headers={**auth, "cf-connecting-ip": "203.0.113.9"})   # via the tunnel
    assert r.status_code == 200 and r.json()["dropped"] == ["diastolic"]
    assert r.json()["spoken"].startswith("Carpe Vigor updated: 7 days of steps, 7,600 today, weight 92.5 kilograms")
    state = client.get("/api/state").json()
    assert state["steps"] == [8234, 6100, 9400, 7300, 4800, 11200, 7600]               # the reward's steps, measured
    page = client.get("/numbers").text
    assert "BMI 29.2" in page and "Resting heart rate" in page                         # 92.5 kg at 178 cm
    client.post("/api/health", json={"resting_hr": "59"}, headers=auth)                # the evening sync, again today
    rows = [r for r in client.get("/api/state").json().get("numbers") or [] if r["key"] == "resting_hr"]
    assert len(rows) <= 1                                                               # one reading a day, replaced


def test_a_phone_pairs_once_from_the_qr_code_and_then_adds_meals(client, monkeypatch, tmp_path):
    _tiny_usda(tmp_path)
    import re
    from fastapi.testclient import TestClient
    import app as webapp
    from carpevigor import config, phone
    monkeypatch.setattr(config, "API_TOKEN", "s3cret-token")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://tunnel.example")
    here = TestClient(webapp.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    page = here.get("/diary").text
    assert "<svg" in page and "Point your iPhone camera here" in page
    assert "<svg" not in client.get("/diary").text                               # the QR only at this computer
    code = phone.new_code()
    tunnel = {"cf-connecting-ip": "203.0.113.9"}
    pal = TestClient(webapp.app, base_url="https://tunnel.example")
    assert "Pair" in pal.get("/m", headers=tunnel).text                          # not paired yet: no diary shown
    assert pal.post("/m", data={"text": "a pear"}, headers=tunnel, follow_redirects=False).headers["location"] == "/m"
    r = pal.get(f"/m/pair/{code}", headers=tunnel, follow_redirects=False)
    assert r.status_code == 303 and "httponly" in r.headers["set-cookie"].lower() and "s3cret-token" not in r.headers["location"]
    assert "expired" in TestClient(webapp.app).get(f"/m/pair/{code}").text       # one use only
    r = pal.post("/m", data={"text": "cacio e pepe", "portion": "normal"}, headers=tunnel)
    assert "What are you" in r.text and "cacio e pepe: about" in r.text
    assert client.get("/api/state").json()["diary"][-1]["dish"] == "cacio e pepe"
    for path in ("/diary", "/numbers", "/static/app/app.css", "/api/state"):       # the tunnel opens nothing else
        assert pal.get(path, headers=tunnel).status_code == 404, path
    monkeypatch.setattr(phone, "VALID_SECONDS", -1)
    assert "expired" in pal.get(f"/m/pair/{phone.new_code()}").text                # ten minutes, then gone


def test_a_lab_report_is_read_then_checked_by_the_person_and_never_stored(client, monkeypatch):
    from carpevigor import report
    seen = []

    def reader(system, task, shape, tier="strong", temperature=0.1, attachment=None):
        seen.append(attachment)
        return report.Extracted(test_date="2026-10-20", readings=[
            report.Reading(measure="ldl", printed_name="Colesterolo LDL", value=4.1, unit="mmol/L"),
            report.Reading(measure="glucose", printed_name="Glicemia", value=96, unit="mg/dL"),
            report.Reading(measure="hdl", printed_name="Colesterolo HDL", value=4800, unit="mg/dL"),   # misread
            report.Reading(measure="other", printed_name="Ferritina", value=80, unit="ng/mL")])
    monkeypatch.setattr(report.llm, "ask", reader)
    pdf = ("referto.pdf", b"%PDF-1.4 a test report", "application/pdf")
    r = client.post("/numbers/report", files={"file": pdf}, follow_redirects=False)
    assert "error=" in r.headers["location"] and not seen                       # not sent without the box ticked
    client.post("/numbers/report", files={"file": pdf}, data={"send_ok": "1"})
    assert seen[0] == (b"%PDF-1.4 a test report", "application/pdf")
    page = client.get("/numbers/report").text
    assert "Check every value" in page and "converted from 4.1 mmol/L" in page and "looks unlikely" in page
    import app as webapp
    d = webapp.store.get("report_draft")
    assert [r["ok"] for r in d["rows"]] == [True, True, False, False]           # the unlikely HDL is left unticked
    assert d["rows"][0]["value"] == round(4.1 * 38.67, 1)                         # 158.5 mg/dL
    assert not any(isinstance(v, (bytes, bytearray)) for v in webapp.store.get("report_draft").values())
    client.post("/numbers/report/confirm", data={"keep_0": "1", "value_0": "158,5", "date_0": "2026-10-20",
                                                  "target_0": "130", "value_1": "96", "date_1": "2026-10-20"})
    numbers = webapp.store.get("numbers")
    assert [(n["key"], n["value"], n["target"]) for n in numbers] == [("ldl", 158.5, 130.0)]   # only what was ticked
    assert webapp.store.get("report_draft") is None
    bad = client.post("/numbers/report", files={"file": ("x.txt", b"hello", "text/plain")}, data={"send_ok": "1"},
                      follow_redirects=False)
    assert "error=" in bad.headers["location"]                                   # only PDFs and photos


def test_measures_are_kept_only_with_consent_and_can_be_deleted(client):
    measures = {"height_cm": "178", "weight_kg": "92", "age": "50", "sex": "male", "activity": "light", "goal_kg": "86"}
    r = client.post("/numbers/measures", data=measures, follow_redirects=False)
    assert "error=" in r.headers["location"] and "BMI 29.0" not in client.get("/numbers").text   # nothing kept
    client.post("/numbers/measures", data={**measures, "consent": "1"})
    page = client.get("/numbers").text
    assert "BMI 29.0 · Overweight" in page and "about 12 weeks" in page and "not a forecast" in page
    client.post("/numbers/measures/delete")
    assert "BMI 29.0" not in client.get("/numbers").text


def test_what_i_ate_is_counted_from_a_sentence_and_the_watch_needs_the_token(client, tmp_path, monkeypatch):
    from carpevigor import config, diary, nutrition
    _tiny_usda(tmp_path)
    monkeypatch.setitem(nutrition.llm.mock_answers, "Breakdown", lambda task: diary.Breakdown(
        dish="cacio e pepe", parts=[diary.Part(name="pasta dry", grams=100), diary.Part(name="cheese romano", grams=40)]
        if "cacio" in task else [], assumed="100 g of dry pasta"))
    r = client.post("/diary", data={"text": "a plate of cacio e pepe", "portion": "large"}, follow_redirects=False)
    assert r.headers["location"] == "/diary"
    page = client.get("/diary").text
    assert "cacio e pepe" in page and "estimated" in page
    entry = client.get("/api/state").json()["diary"][0]
    assert entry["nutrition"]["kcal"] == round((371 * 1.0 + 387 * 0.4) * 1.4, 1)   # a large portion: 1.4 typical
    # the watch's door: shut without a token, refused with a wrong one, open with the right one
    meal = {"text": "cacio e pepe"}
    assert client.post("/api/meal", json=meal).status_code == 403
    assert "set Method to POST" in client.get("/api/meal").json()["spoken"]     # a shortcut left on GET is told why
    monkeypatch.setattr(config, "API_TOKEN", "s3cret-token")
    assert client.post("/api/meal", json=meal, headers={"Authorization": "Bearer wrong"}).status_code == 403
    r = client.post("/api/meal", json=meal, headers={"Authorization": "Bearer s3cret-token"})
    assert r.status_code == 200 and r.json()["spoken"].startswith("cacio e pepe: about ")
    # the token is shown to copy into the shortcut only at this computer, never through the tunnel: decided by the
    # connection's own address, not by the Host header a client writes
    from fastapi.testclient import TestClient
    import app as webapp
    at_this_computer = TestClient(webapp.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    assert "Bearer s3cret-token" in at_this_computer.get("/diary").text
    assert "s3cret-token" not in at_this_computer.get("http://evil.example/diary").text   # DNS rebinding: refused
    assert "s3cret-token" not in at_this_computer.get("/diary", headers={"cf-connecting-ip": "203.0.113.9"}).text
    assert "s3cret-token" not in at_this_computer.get("/diary", headers={"x-forwarded-for": "203.0.113.9"}).text
    assert "s3cret-token" not in client.get("http://127.0.0.1/diary").text      # Host says local, connection is not
    # through the tunnel only the watch's door answers: no measures, no diary page, no PayPal buttons
    tunnel = {"cf-connecting-ip": "203.0.113.9"}
    assert client.get("/numbers", headers=tunnel).status_code == 404
    assert client.get("/api/state", headers=tunnel).status_code == 404
    assert client.post("/api/meal", json=meal, headers={**tunnel, "Authorization": "Bearer s3cret-token"}).status_code == 200
    assert "Today so far:" in r.json()["spoken"]
    not_food = client.post("/api/meal", json={"text": "I walked the dog"}, headers={"Authorization": "Bearer s3cret-token"})
    assert not_food.status_code == 422 and "nothing was added" in not_food.json()["spoken"]
    auth = {"Authorization": "Bearer s3cret-token"}
    assert client.post("/api/meal", json={"text": "pasta " * 200}, headers=auth).status_code == 422   # not a sentence
    assert client.post("/api/meal", content=b"x" * 5000, headers=auth).status_code == 413            # not a meal
    # a form on another site cannot post into the diary (or press a PayPal button)
    cross = client.post("/diary", data={"text": "cacio e pepe"}, headers={"Origin": "https://evil.example"})
    from fastapi.testclient import TestClient as Bare
    import app as webapp
    assert Bare(webapp.app).post("/numbers/measures/delete").status_code == 403   # no origin evidence: refused
    assert cross.status_code == 403
    assert len(client.get("/api/state").json()["diary"]) == 3   # the watch twice (once through the tunnel), the form once


def test_a_cooked_meal_of_the_plan_goes_in_and_out_of_the_diary(client):
    client.post("/doctor", data={"doctor_said": "Eat less salt, walk more", "device": "Thermomix / Bimby TM7", "budget": "140"},
                follow_redirects=False)
    _built_week(client)
    first = client.get("/api/state").json()["plan"]["plan"]["recipes"][0]
    client.post("/week/cooked", data={"title": first["title"]})
    entries = client.get("/api/state").json()["diary"]
    assert [e["dish"] for e in entries] == [first["title"]] and not entries[0]["estimate"]
    assert entries[0]["nutrition"] == first["nutrition"]          # its own recipe, not an estimate
    client.post("/week/cooked", data={"title": first["title"]})   # unticked
    assert client.get("/api/state").json()["diary"] == []


def test_the_cart_buys_the_packs_the_recipes_use():
    catalog = Catalog.load()
    recipes = [{"title": "Chicken and peppers", "buy": [{"name": "Chicken breast", "amount": 300, "unit": "g"},
                                                         {"name": "Lemons", "amount": 3, "unit": "piece"},
                                                         {"name": "Black pepper", "amount": 2, "unit": "g"}]},
               {"title": "Chicken soup", "buy": [{"name": "Chicken breast", "amount": 450, "unit": "g"},
                                                 {"name": "Lemon", "amount": 2, "unit": "piece"},
                                                 {"name": "Eggs", "amount": 4, "unit": "piece"}]},
               {"title": "An older plan", "buy": ["Baby spinach"]}]
    cart = cart_agent.build(recipes, Pantry(), catalog, budget=500.0)
    line = {l.item.name: l for l in cart.lines}
    assert line["Chicken breast"].quantity == 2                 # 750 g in 600 g packs
    assert line["Chicken breast"].reason.startswith("750 g for Chicken and peppers, Chicken soup")
    assert line["Lemons"].quantity == 2                         # "Lemons" and "Lemon" are one line: 5 lemons, packs of 4
    assert line["Eggs"].quantity == 1 and line["Black pepper"].quantity == 1  # 2 g of pepper: the pack is sold by the piece
    assert line["Baby spinach"].quantity == 1                   # no amount given: one pack, as before
    stock = cart_agent.build([{"title": "Soup", "buy": [{"name": "Vegetable stock, low sodium", "amount": 1800, "unit": "g"}]}],
                             Pantry(), catalog, budget=500.0)
    assert stock.lines[0].quantity == 2                         # 1,800 g of stock in 1 l cartons: grams taken as millilitres


def test_the_kitchen_check_holds_recipes_to_the_device_and_their_portions():
    from carpevigor import kitchen
    week = [
        {"day": "Mon", "meal": "dinner", "servings": 2, "leftovers_for": "Tue lunch",
         "steps": ["Sauté 3 min/120°C/speed 1.", "Steam 20 min/Varoma/speed 1."]},
        {"day": "Tue", "meal": "lunch", "servings": 1, "from_leftovers": "Mon dinner", "ingredients": ["leftover salmon"]},
        {"day": "Wed", "meal": "dinner", "servings": 1, "steps": ["Cook the rice as per Monday's quinoa."]},
        {"day": "Thu", "meal": "lunch", "servings": 1, "ingredients": ["leftover chicken"]},
        {"day": "Fri", "meal": "dinner", "servings": 1, "leftovers_for": "Sat lunch"},
        {"day": "Sat", "meal": "dinner", "servings": 1, "steps": ["Bake the frittata 20 min at 180°C.",
                                                                 "Brown the onion in Browning mode 4 min/160°C."]},
    ]
    found = lambda name, people=1: kitchen.check(week, kitchen.device(name), people)
    tm6 = found("Thermomix / Bimby TM6")
    assert set(tm6) == {2, 3, 4}           # 120°C, Varoma, the oven's 180°C and Browning mode are all fine on a TM6
    assert "refers to another recipe" in tm6[2][0] and "which meal" in tm6[3][0]
    assert len(tm6[4]) == 2                # Sat lunch is not cooked from it, and 1 serving cannot feed two meals
    assert any("120°C" in p for p in found("Thermomix / Bimby TM31")[0])  # a TM31 stops at 100°C
    assert 0 not in found("Thermomix / Bimby TM7")   # "Varoma" in a TM7 step is fine: Cookidoo prints it for the TM7 too
    hot_blend = [{"day": "Sun", "meal": "lunch", "servings": 1, "steps": ["Blend the soup 1 min/90°C/speed 8."]}]
    assert "does not heat" in kitchen.check(hot_blend, kitchen.device("Thermomix / Bimby TM7"), 1)[0][0]
    steps = lambda *s: [{"day": "Sun", "meal": "dinner", "servings": 1, "steps": list(s)}]
    tm7 = kitchen.device("Thermomix / Bimby TM7")
    assert kitchen.check(steps("Steam 20 min/Varoma/speed 8."), tm7, 1)[0] == [
        "Step 1 heats above speed 6: the Thermomix / Bimby TM7 does not heat there",
        "Step 1 steams above speed 5: the Thermomix / Bimby TM7's Steaming mode goes up to speed 5"]
    assert "steams above" in kitchen.check(steps("Steaming mode (Varoma) 20 min/speed 8."), tm7, 1)[0][0]
    assert not kitchen.check(steps("Steaming mode (Varoma) 20 min/speed 1.", "Steam 20 min/Varoma/speed 2."), tm7, 1)
    assert any("160°C" in p for p in found("Thermomix / Bimby TM5")[5])   # no Browning mode on a TM5
    two = found("Thermomix / Bimby TM6", people=2)
    assert any("feeds 2 now" in p for p in two[0]) and any("1 serving for 2" in p for p in two[1])
    assert kitchen.device("Thermomix / Bimby").name == "Thermomix / Bimby TM6"   # plans saved before the models
    assert kitchen.NAMES[0] == "Thermomix / Bimby TM7"                         # the default, and the demo week's


def test_the_week_is_written_day_by_day_and_keeps_the_outlines_portions(monkeypatch):
    from carpevigor import planner
    demo = planner._mock_plan("")
    week = planner.write_week("task")              # an outline, then one call per day, all days at once
    assert [(r.day, r.meal, r.title) for r in week.recipes] == [(r.day, r.meal, r.title) for r in demo.recipes]
    # a day's call that says otherwise about portions or leftovers does not win: the outline decides
    wrong = lambda task: planner.RecipeBatch(recipes=[r.model_copy(update={"servings": 9, "leftovers_for": ""})
                                                      for r in planner._mock_day(task).recipes])
    monkeypatch.setitem(planner.llm.mock_answers, "RecipeBatch", wrong)
    rewritten = planner.write_week("task").recipes
    assert [(r.servings, r.leftovers_for) for r in rewritten] == [(r.servings, r.leftovers_for) for r in demo.recipes]


def test_a_recipe_still_wrong_after_the_fix_is_flagged_on_screen_not_hidden():
    from carpevigor import kitchen, planner
    sauté = planner.Step(text="Add the oil and the chicken, sauté",
                         setting=planner.Setting(time="3 min", temperature="120°C", reverse=True, speed="spoon"),
                         then="Scrape down the sides with the spatula.")
    bad = planner.Recipe(day="Mon", meal="dinner", title="Sautéed chicken", servings=1, prep_minutes=5, total_minutes=15,
                         difficulty="easy", ingredients=[planner.Ingredient(amount="150 g", name="chicken breast", grams=150,
                                                                            note="in pieces (2 cm)")],
                         steps=[sauté], why="w", evidence="e")
    # the step as the week page prints it, and as the check reads it: one wording for both
    assert kitchen.step_parts(sauté.model_dump()) == ("Add the oil and the chicken, sauté", "3 min/120°C/Reverse/speed spoon",
                                                      "Scrape down the sides with the spatula.")
    plan = planner.WeekPlan(title="t", summary="s", recipes=[bad], movement=[])
    report = planner.fix_recipes(plan, kitchen.device("Thermomix / Bimby TM31"), 1)  # the mock fixes nothing
    assert report["found"] == 1 and report["still"] == 1
    assert "100°C" in plan.recipes[0].kitchen_flags[0]
    steam = {"text": "Place the Varoma in position, steam", "setting": {"time": "20 min", "temperature": "Varoma",
                                                                        "speed": "8", "mode": "Steaming"}}
    assert kitchen.step_text(steam) == "Place the Varoma in position, steam: Steaming mode 20 min/Varoma/speed 8."
    assert len(kitchen.check([{"steps": [steam]}], kitchen.device("Thermomix / Bimby TM7"), 1)[0]) == 2  # heat and steam


def test_cart_charges_delivery_again_when_cutting_drops_it_below_the_free_threshold():
    catalog = Catalog.load()
    free_over = catalog.store["delivery_free_over"]
    recipes = [{"title": "Big", "ingredients": ["salmon fillets", "cod fillets", "chicken breast", "olive oil", "walnuts",
                                                "almonds", "blueberries", "apples", "rolled oats", "quinoa", "black pepper"]}]
    full = cart_agent.build(recipes, Pantry(), catalog, budget=500.0)
    assert full.subtotal >= free_over and full.delivery_fee == 0
    cart = cart_agent.build(recipes, Pantry(), catalog, budget=full.subtotal - 10)
    assert cart.subtotal < free_over and cart.delivery_fee == catalog.store["delivery_fee"]
    assert cart.within_budget


def test_catalog_find_does_not_turn_real_gemini_ingredients_into_the_wrong_product():
    # Strings as Gemini wrote them on 31 Oct, and what the old matcher bought for them.
    catalog = Catalog.load()
    name = lambda q: (catalog.find(q).name if catalog.find(q) else None)
    assert name("1 potato, cubed") != "Potato chips"                              # was: chips in a low-salt plan
    assert name("500g water") is None                                             # was: sparkling water, 6 bottles
    assert name("1 tsp dried oregano") != "Dried lentils"                         # was: matched on "dried"
    assert name("400g can chopped tomatoes (no salt added)") == "Cherry tomatoes"  # was: cannellini, on "no salt added"
    assert name("1 portion leftover chicken and vegetable soup") is None          # leftovers are cooked, not bought
    assert name("200g can chickpeas, rinsed (no salt added)") == "Chickpeas, no salt added"
    assert name("1 cod fillet (approx. 150g)") == "Cod fillets"
    assert name("2 tbsp olive oil") == "Extra-virgin olive oil"
    assert name("Baby spinach") == "Baby spinach"                                 # exact store name wins
    assert name("potato chips") == "Potato chips"                                 # a snack only when asked by name


def test_a_model_chosen_name_cannot_put_an_off_plan_product_in_the_cart():
    catalog = Catalog.load()
    recipes = [{"title": "Bad", "ingredients": [], "buy": ["Bacon", "Cola, 6 cans", "Broccoli"]}]
    cart = cart_agent.build(recipes, Pantry(), catalog, budget=100.0, avoid=catalog.off_plan(["low sodium", "less sugar"]))
    names = {l.item.name for l in cart.lines}
    assert "Broccoli" in names and not names & {"Bacon", "Cola, 6 cans"}   # swapped (bacon → low-sodium turkey) or skipped
    for gone in ("Bacon", "Cola"):
        assert any(l.swapped_from.startswith(gone) for l in cart.lines) or any(gone in s for s in cart.skipped)
    butter = cart_agent.build([{"title": "y", "ingredients": [], "buy": ["Butter"]}], Pantry(), catalog, 100.0,
                              avoid=catalog.off_plan(["less saturated fat"]))
    assert [(l.item.name, l.swapped_from) for l in butter.lines] == [("Extra-virgin olive oil", "Butter")]  # swapped, not lost
    assert catalog.find("1 watermelon") is None or catalog.find("1 watermelon").name != "Sparkling water, 6 bottles"
    assert cart_agent.build([{"title": "x", "ingredients": ["2 cups watercress"]}], Pantry(), catalog, 100.0).skipped  # said, not dropped


def test_cart_buys_from_the_recipes_store_list_when_there_is_one():
    catalog = Catalog.load()
    recipes = [{"title": "Soup", "ingredients": ["1 potato, cubed", "500g water", "1 carrot"], "buy": ["Carrots", "Yellow onions"]}]
    names = {l.item.name for l in cart_agent.build(recipes, Pantry(), catalog, budget=100.0).lines}
    assert names == {"Carrots", "Yellow onions"}


def test_a_blocked_site_is_read_from_the_page_saved_by_hand(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(sources, "DIR", tmp_path)
    (tmp_path / "aha-fats.html").write_text("<html><nav>menu</nav><p>Limit saturated fat to less than 6% of calories.</p></html>",
                                            encoding="utf-8")

    def blocked(url, **kw):
        raise requests.HTTPError("403 Client Error: Forbidden")
    monkeypatch.setattr(sources.requests, "get", blocked)
    assert sources.fetch("aha-fats") == ["aha-fats"]
    text = sources.text_of("aha-fats")
    assert "less than 6% of calories" in text and "menu" not in text and "saved by hand" in text
    assert sources.fetch("who-diet") == []                    # blocked and nothing saved: said, not invented


def test_a_long_paper_keeps_only_the_sections_we_cite():
    xml = ("<article><front>title</front><body><sec><title>Prevalence of CVH</title><p>not needed</p></sec>"
           "<sec><title>SLEEP HEALTH AS A NEW COMPONENT OF CVH</title><p>7 to 9 hours of sleep.</p></sec></body></article>")
    assert sources.sections(xml, ["SLEEP HEALTH"]) == "SLEEP HEALTH AS A NEW COMPONENT OF CVH\n\n7 to 9 hours of sleep."


def _two_sources(tmp_path, monkeypatch):
    from carpevigor import rag
    monkeypatch.setattr(sources, "DIR", tmp_path)
    monkeypatch.setattr(rag, "INDEX", tmp_path / "index.json")
    monkeypatch.setattr(rag, "CHUNK", 120)  # small passages, so the salt facts and the filler are apart
    (tmp_path / "who-sodium.txt").write_text("WHO — Sodium\nhttps://who.int\n\nMost people eat too much salt.\n\n"
                                             "Adults should eat less than 5 g of salt a day.\n\n" + "Unrelated filler about trade. " * 60,
                                             encoding="utf-8")
    (tmp_path / "who-activity.txt").write_text("WHO — Activity\nhttps://who.int/a\n\nAdults should do 150 minutes of "
                                               "moderate physical activity a week.", encoding="utf-8")
    return rag


def test_rag_gives_the_jurors_the_passages_closest_to_each_claim(tmp_path, monkeypatch):
    rag = _two_sources(tmp_path, monkeypatch)
    text, info = rag.reference(["Adults should eat less than 5 g of salt a day [WHO]."], ["blood_pressure", "activity"], k=1)
    assert "less than 5 g of salt" in text and "SOURCE: WHO — Sodium" in text and text.count("trade") <= 1  # not 60
    assert info["mode"] == "retrieved" and info["passages"] == 1 and info["chars"] < 400
    text, _ = rag.reference(["150 minutes of moderate activity a week"], ["activity"], k=1)
    assert "150 minutes" in text and "salt" not in text                       # only the topics' sources are searched


def test_rag_quotes_the_sources_word_for_word_about_a_measure(tmp_path, monkeypatch):
    rag = _two_sources(tmp_path, monkeypatch)
    found = rag.quotes("How much salt should adults eat a day?", ["blood_pressure", "activity"], k=1)
    assert len(found) == 1 and "less than 5 g of salt" in found[0]["text"] and found[0]["name"].startswith("WHO — Sodium")
    monkeypatch.setattr(rag.llm, "embed", lambda texts, task: (_ for _ in ()).throw(RuntimeError("down")))
    assert rag.quotes("salt?", ["blood_pressure"]) == []                       # nothing invented when retrieval fails


def test_rag_falls_back_to_the_full_texts_and_says_so(tmp_path, monkeypatch):
    rag = _two_sources(tmp_path, monkeypatch)

    def broken(texts, task):
        raise RuntimeError("quota exceeded")
    monkeypatch.setattr(rag.llm, "embed", broken)
    text, info = rag.reference(["less salt"], ["blood_pressure"])
    assert "Most people eat too much salt" in text and "trade" in text       # the whole source, not nothing
    assert info["mode"] == "full texts" and "quota exceeded" in info["note"]


def test_vertex_embedding_sends_one_text_per_call(monkeypatch):
    # gemini-embedding-2 answers a list of 5 texts with ONE vector (they are read as one content): batching would
    # give every passage the same vector and retrieval would return noise, silently.
    from carpevigor import llm
    calls = []

    class Models:
        def embed_content(self, model, contents, config=None):
            calls.append(contents)
            return type("R", (), {"embeddings": [type("E", (), {"values": [float(len(calls))] * 4})()]})()
    monkeypatch.setattr(llm, "_vertex_client", type("C", (), {"models": Models()})())
    monkeypatch.setattr(llm, "provider", lambda: "vertex")
    vectors = llm.embed(["a", "b", "c"], "RETRIEVAL_DOCUMENT")
    assert len(calls) == 3 and all(isinstance(c, str) for c in calls) and len({v[0] for v in vectors}) == 3


def test_parallel_first_calls_share_one_vertex_client(monkeypatch):
    import sys
    import threading
    import types as pytypes
    from carpevigor import llm
    made = []

    class SlowClient:
        def __init__(self, **kw):
            threading.Event().wait(0.05)  # widen the race window
            made.append(self)
    import google
    fake = pytypes.ModuleType("google.genai")
    fake.Client = SlowClient
    monkeypatch.setitem(sys.modules, "google.genai", fake)
    monkeypatch.setattr(google, "genai", fake, raising=False)
    monkeypatch.setattr(llm, "_vertex_client", None)
    threads = [threading.Thread(target=llm._client) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(made) == 1


def test_vertex_retries_a_429_or_a_503_and_nothing_else(monkeypatch):
    from pydantic import BaseModel as Shape
    from carpevigor import llm

    class A(Shape):
        answer: str

    class Busy(Exception):
        code = 429

    class Down(Exception):
        code = 503
    calls = []

    class Models:
        def generate_content(self, model, contents, config=None):
            calls.append(1)
            if len(calls) == 1:
                raise Busy("RESOURCE_EXHAUSTED")
            if len(calls) == 2:
                raise Down("UNAVAILABLE")    # 31 Oct night: Vertex itself, for a while
            return type("R", (), {"parsed": A(answer="ok"), "text": ""})()
    monkeypatch.setattr(llm, "_vertex_client", type("C", (), {"models": Models()})())
    monkeypatch.setattr(llm, "RETRY_WAITS", (0, 0))
    assert llm._vertex("s", "t", A, "m", 0.1).answer == "ok" and len(calls) == 3

    class Broken(Exception):
        code = 400
    monkeypatch.setattr(Models, "generate_content", lambda self, **k: (_ for _ in ()).throw(Broken("bad request")))
    with pytest.raises(Broken):
        llm._vertex("s", "t", A, "m", 0.1)


def test_my_numbers_are_shown_against_my_doctors_target_never_judged_by_the_app():
    from carpevigor import checkup
    rows = []
    rows = checkup.add(rows, "ldl", 172, "2026-06-01", target=130)
    rows = checkup.add(rows, "ldl", 158, "2026-09-01")                # the doctor's target is carried over
    rows = checkup.add(rows, "hdl", 52, "2026-09-01", target=40)
    rows = checkup.add(rows, "systolic", 128, "2026-09-01")           # no target given: nothing compared
    view = {v["key"]: v for v in checkup.view(rows)}
    assert view["ldl"]["latest"]["value"] == 158 and view["ldl"]["target"] == 130
    assert view["ldl"]["status"] == "above your doctor's target" and view["ldl"]["trend"] == "toward the target"
    assert view["hdl"]["status"] == "at your doctor's target"         # HDL: higher is the right side
    assert view["systolic"]["status"] == "no target from your doctor yet"
    assert checkup.topics(rows) == ["cholesterol"]                    # only what is off the doctor's target steers the plan
    with pytest.raises(ValueError):
        checkup.add(rows, "psa", 3.1, "2026-09-01")                   # only the measures the app knows
    with pytest.raises(ValueError):
        checkup.add(rows, "ldl", -5, "2026-09-01")


def test_the_check_up_bonus_pays_the_doctors_verdict_on_the_spend_since_the_last_one():
    from carpevigor import checkup
    assert checkup.bonus("met", 400.0) == round(400 * checkup.config.CHECKUP_BONUS["met"], 2) > 0
    assert 0 < checkup.bonus("improving", 400.0) < checkup.bonus("met", 400.0)
    assert checkup.bonus("not yet", 400.0) == 0
    with pytest.raises(ValueError):
        checkup.bonus("cured", 400.0)


MLP_XML = """<?xml version="1.0" encoding="UTF-8"?><health-topics total="3">
<health-topic title="Sodium" url="https://medlineplus.gov/sodium.html" id="1" language="English">
<full-summary>&lt;p&gt;Most of the sodium we eat comes from packaged foods.&lt;/p&gt;</full-summary><group url="x" id="9">Food and Nutrition</group></health-topic>
<health-topic title="Sodio" url="https://medlineplus.gov/spanish/sodium.html" id="2" language="Spanish">
<full-summary>&lt;p&gt;La mayor parte del sodio...&lt;/p&gt;</full-summary><group url="x" id="9">Alimentos y nutrición</group></health-topic>
<health-topic title="Measles" url="https://medlineplus.gov/measles.html" id="3" language="English">
<full-summary>&lt;p&gt;Measles is an infectious disease.&lt;/p&gt;</full-summary><group url="x" id="5">Infections</group></health-topic>
</health-topics>"""


def test_the_medlineplus_library_keeps_english_lifestyle_topics_only(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "DIR", tmp_path)
    kept = sources.library_from_xml(MLP_XML)
    assert [k["name"] for k in kept] == ["MedlinePlus — Sodium"]                       # not Spanish, not infections
    assert "packaged foods" in sources.text_of(kept[0]["id"]) and "<p>" not in sources.text_of(kept[0]["id"])
    assert [s["id"] for s in sources.library()] == [kept[0]["id"]]


def _library(tmp_path, monkeypatch):
    rag = _two_sources(tmp_path, monkeypatch)
    sources.library_from_xml(MLP_XML)
    return rag


def test_ask_the_sources_answers_from_retrieved_passages_with_citations(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch)
    from carpevigor import ask
    out = ask.answer("Where does most of the sodium I eat come from?", [])
    assert out["answer"] and out["safety"]["approved"] and out["passages"]
    assert any("packaged foods" in p["text"] for p in out["passages"])            # the library is searched too
    assert all(p["name"] and p["url"] for p in out["passages"])


def test_an_answer_the_safety_reviewer_holds_back_is_never_shown(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch)
    from carpevigor import ask
    monkeypatch.setattr(ask.review_board, "expert", lambda reviewer, text: {
        "approved": False, "absent": False, "checks": [], "corrections": [{"says": "x", "should_be": "Remove it",
                                                                            "why": "It predicts the person's values."}]})
    out = ask.answer("Will my pressure go down if I eat less salt?", [])
    assert out["answer"] is None and "predicts the person's values" in out["held_back"] and out["passages"]
    assert out.get("rewritten")                                     # it was given one chance to be fixed first


def test_a_held_back_answer_is_rewritten_once_and_shown_if_it_then_passes(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch)
    from carpevigor import ask
    verdicts = iter([False, True])
    monkeypatch.setattr(ask.review_board, "expert", lambda reviewer, text: {
        "approved": (ok := next(verdicts)), "absent": False, "checks": [],
        "corrections": [] if ok else [{"says": "your LDL", "should_be": "LDL", "why": "Personal claim."}]})
    out = ask.answer("What should I eat this week?", [])
    assert out["answer"] and out["rewritten"] and not out["held_back"]


def test_ask_the_sources_through_the_web_app(client, tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch)
    assert "Ask <i>the sources.</i>" in client.get("/ask").text
    client.post("/ask", data={"question": "Where does most of the sodium I eat come from?"})
    page = client.get("/ask").text
    assert "packaged foods" in page and "read by the safety reviewer" in page and "MedlinePlus — Sodium" in page
    assert not any("sodium I eat" in str(e) for e in client.get("/api/state").json()["log"])  # the question is not logged


def test_my_numbers_steer_what_the_question_is_searched_with(tmp_path, monkeypatch):
    _library(tmp_path, monkeypatch)
    from carpevigor import ask, checkup
    rows = checkup.add([], "systolic", 142, "2026-10-20", target=130)
    assert "Blood pressure" in ask.context(rows) and "above your doctor" in ask.context(rows)
    assert ask.context([]) == ""


def test_sources_pick_topics_and_flag_clinical():
    assert sources.topics_for("my doctor says I have high blood pressure, eat less salt") == ["blood_pressure"]
    assert "activity" in sources.topics_for("walk more")
    assert sources.mentions_clinical("should I stop my statin?")
    assert not sources.mentions_clinical("eat less salt")


def _board_that(verdicts):
    """A fake board: each call pops the next list of corrections (texts to flag); empty list = approved."""
    calls = []

    def convene(text, reference, strict=True, facts=None):
        flags = verdicts.pop(0)
        calls.append(text)
        return {"approved": not flags, "provider": "test", "reviewers": [], "set_aside": [], "seconds": 1.0,
                "statements": review_board.statements_of(text),
                "corrections": [{"n": 1, "says": f, "should_be": "Remove it", "why": "The source does not say this.",
                                 "votes": "2 of 3 fact jurors"} for f in flags]}
    return convene, calls


def test_a_sent_back_plan_is_rewritten_once_and_what_stays_wrong_never_reaches_the_screen(monkeypatch):
    from carpevigor import planner
    from carpevigor.profile import Guidance
    plan = planner._mock_plan("")
    bad_why, bad_evidence = plan.recipes[0].why, plan.recipes[1].evidence
    plan.recipes[3].evidence = bad_evidence  # one sentence used by two dishes, whatever the demo week says
    # a fresh clone has no fetched sources: give the planner one, so the board path runs everywhere
    monkeypatch.setattr(planner.sources, "reference_for", lambda topics: ("SOURCE: test\n\nsome text", []))
    monkeypatch.setattr(planner, "write_week", lambda task, **k: plan.model_copy(deep=True))  # the week as written
    import re
    mock = planner.llm.mock_answers
    monkeypatch.setattr(planner.llm, "ask", lambda system, task, shape, tier="strong", temperature=0.1:
                        planner.Rewrites(rewrites=[planner.Rewrite(id=i, text="No added salt: herbs and lemon instead.")
                                                   for i in re.findall(r"^(r\d+\.(?:why|evidence)):", task, re.M)])
                        if shape is planner.Rewrites else mock[shape.__name__](task))   # the coach: its usual mock
    # the same evidence sentence is used by several dishes: every copy is flagged, not just the first
    expected = sum(1 for r in plan.recipes for t in (r.why, r.evidence) if t in (bad_why, bad_evidence))
    guidance = Guidance.model_validate({"goals": ["Eat less salt"], "topics": ["blood_pressure"], "constraints": [],
                                        "to_the_doctor": []})
    # 1) sent back, then the rewrite is approved: shown, approved after corrections
    convene, calls = _board_that([[bad_why, bad_evidence], []])
    monkeypatch.setattr(planner.review_board, "convene", convene)
    made, report, _ = planner.make(guidance, "Oven and stovetop")
    assert expected > 2 and report["approved"] and report["revision"]["rewritten"] == expected and report["revision"]["removed"] == 0
    assert made.recipes[0].why == "No added salt: herbs and lemon instead." and not made.recipes[0].removed
    assert "No added salt" in calls[1] and bad_why not in calls[1]          # round 2 reads only the rewritten lines
    # 2) the rewrite of one line is sent back again: that line is removed, never shown
    convene, _ = _board_that([[bad_why, bad_evidence], ["No added salt: herbs and lemon instead."]])
    monkeypatch.setattr(planner.review_board, "convene", convene)
    made, report, _ = planner.make(guidance, "Oven and stovetop")
    assert made.recipes[0].why == "" and "why" in made.recipes[0].removed
    assert made.recipes[1].evidence == "" and "evidence" in made.recipes[1].removed
    assert report["approved"] and report["revision"]["removed"] == expected  # nothing the board rejected is on screen
    shown = " ".join(f"{r.why} {r.evidence}" for r in made.recipes)
    assert bad_why not in shown and bad_evidence not in shown and "No added salt: herbs and lemon instead." not in shown


def test_statements_keep_their_citation_and_do_not_break_on_abbreviations():
    # As Gemini wrote them on 31 Oct: the citation after the full stop became a "statement" of its own that every juror
    # rejected, and "e.g." / "i.e." cut sentences in half.
    text = ("Salt intake can be reduced by limiting high-sodium condiments (e.g. soy sauce and bouillon) when cooking. "
            "[WHO — Healthy diet] A diet must also be safe, i.e. free from contaminants [WHO]. Walk more.")
    assert review_board.statements_of(text) == [
        "Salt intake can be reduced by limiting high-sodium condiments (e.g. soy sauce and bouillon) when cooking. [WHO — Healthy diet]",
        "A diet must also be safe, i.e. free from contaminants [WHO].",
        "Walk more."]


def test_fact_jurors_rule_only_on_the_health_claims_the_others_read_everything():
    text = "No added salt: herbs instead. Salt raises blood pressure on average [WHO]. Lentils and carrots. Walking helps [WHO]."
    report = review_board.convene(text, "SOURCE: test\n\nsome text", facts="Salt raises blood pressure on average [WHO]. Walking helps [WHO].")
    jurors = [r for r in report["reviewers"] if r["id"].startswith("facts")]
    assert all(j["checks"][0] == "Ruled on 2 of 2 statements" for j in jurors)
    assert len(report["statements"]) == 4  # safety and clarity read all four


def test_the_second_reading_approves_only_when_every_rejection_is_found_and_removed(monkeypatch):
    from carpevigor import planner
    import re
    plan = planner._mock_plan("")
    repeated = plan.recipes[1].evidence  # used by several dishes: after the rewrite, one quote matches several sentences
    report = {"approved": False, "corrections": [{"says": repeated, "should_be": "x", "why": "y"}]}
    monkeypatch.setattr(planner.llm, "ask", lambda system, task, shape, **k: planner.Rewrites(rewrites=[
        planner.Rewrite(id=i, text="Fixed.") for i in re.findall(r"^(r\d+\.(?:why|evidence)):", task, re.M)]))
    # a second-round rejection that cannot be traced to a sentence must keep the plan unapproved,
    # even when another rejection matches several sentences
    monkeypatch.setattr(planner.review_board, "convene", lambda *a, **k: {
        "approved": False, "reviewers": [], "corrections": [{"says": "Fixed."}, {"says": "something nobody wrote"}]})
    assert not planner.revise(plan.model_copy(deep=True), report, "ref")["approved"]
    # a reviewer missing from the second reading: not approved, whatever else
    monkeypatch.setattr(planner.review_board, "convene", lambda *a, **k: {
        "approved": False, "corrections": [], "reviewers": [{"absent": True}]})
    assert not planner.revise(plan.model_copy(deep=True), report, "ref")["approved"]


def test_review_board_mock_is_honest_about_itself():
    report = review_board.convene("Salt raises blood pressure. Walking helps.", "SOURCE: test\n\nsome text")
    assert report["provider"] == "mock" and report["approved"]
    assert all("Simulated" in r["checks"][0] or "Ruled on" in r["checks"][0] for r in report["reviewers"])


def _built_week(client):
    """The week is built in the background while the screen shows its steps: start it, wait for it, open it."""
    import time
    assert "Planning your week" in client.get("/week?build=1").text
    for _ in range(400):
        status = client.get("/api/building").json()
        if status["done"] or status["error"]:
            break
        time.sleep(0.05)
    assert status["done"] and status["percent"] == 100, status
    return client.get("/week")


def test_the_waiting_screen_shows_each_step_and_says_when_it_fails(client, monkeypatch):
    import app as webapp
    from carpevigor import planner
    steps = []
    real = planner.make
    monkeypatch.setattr(planner, "make", lambda g, device, people, progress, **k:
                        real(g, device, people, lambda s, p: (steps.append((s, p)), progress(s, p)), **k))
    client.post("/doctor", data={"doctor_said": "Eat less salt, walk more", "device": "Thermomix / Bimby TM7", "budget": "140"},
                follow_redirects=False)  # one build: the one _built_week starts
    _built_week(client)
    percents = [p for _, p in steps]
    assert percents == sorted(percents) and percents[0] < 10 and steps[-1][1] >= 62
    assert any("Writing the recipes: 7 of 7 days" == s for s, _ in steps)
    def broken(*a, **k):
        raise RuntimeError("Vertex said 429 five times")
    monkeypatch.setattr(planner, "make", broken)
    client.get("/week?build=1")
    for _ in range(100):
        if webapp.building["error"]:
            break
        __import__("time").sleep(0.02)
    assert "Vertex said 429" in client.get("/api/building").json()["error"] and not webapp.building["running"]


def test_full_loop_through_the_web_app(client):
    r = client.post("/doctor", data={"doctor_said": "High blood pressure: eat less salt, lose weight, walk more",
                                     "device": "Thermomix / Bimby", "constraints": "", "budget": "70"}, follow_redirects=False)
    assert r.status_code == 303
    r = _built_week(client)
    assert r.status_code == 200 and "Review board" in r.text and "simulated" in r.text
    r = client.post("/week/cooked", data={"title": "Lentil and vegetable soup"}, follow_redirects=False)
    r = client.post("/home", data={"have": ["DAI-BUTTER-250", "FAT-EVOO-500", "GRA-BROWN-1K"]}, follow_redirects=False)
    r = client.get("/cart")
    assert "Authorize this week's budget" in r.text
    assert "raise it by" in r.text  # 70 does not buy the demo week: the cart says so before cutting anything
    r = client.post("/budget/authorize", data={"amount": "140"}, follow_redirects=False)
    approve = r.headers["location"]
    token = approve.split("token=")[1].split("&")[0]
    r = client.get(f"/budget/approved?token={token}", follow_redirects=False)
    r = client.get("/cart")
    assert "Approve — order and pay" in r.text and "Basket score" in r.text
    # the person adds bacon and cookies on top of the agent's cart: in the cart, marked as lowering the reward
    client.post("/cart/extra", data={"sku": "PRO-BACON-200"}, follow_redirects=False)
    client.post("/cart/extra", data={"sku": "SNK-COOKIE-300"}, follow_redirects=False)
    r = client.get("/cart")
    assert "Bacon" in r.text and "− reward" in r.text
    r = client.post("/cart/order", follow_redirects=False)
    assert r.headers["location"] == "/reward"
    state = client.get("/api/state").json()
    assert state["money"]["spent"] > 0 and state["money"]["spent"] <= 140
    order = next(e for e in state["log"] if e["kind"] == "order")
    assert order["unhealthy"] >= 4.49 + 3.49 and order["healthy"] > 0          # bacon and cookies counted as junk
    client.post("/reward/steps", data={"steps": "8200, 6100, 9400, 7300, 4800, 11200, 7600"}, follow_redirects=False)
    for title in [r["title"] for r in state["plan"]["plan"]["recipes"]][:12]:
        client.post("/week/cooked", data={"title": title}, follow_redirects=False)
    r = client.get("/reward")
    assert "pays you back" in r.text and "verified by PayPal" in r.text and "self-reported" in r.text
    client.post("/budget/release", follow_redirects=False)                    # ends the week: its reward goes into the month
    state = client.get("/api/state").json()
    assert state["money"]["released"] == round(140 - state["money"]["spent"], 2)
    # one number on stage: the reward page and the ledger round the week's score the same way
    import re
    shown = re.search(r"score (\d+)/100", client.get("/reward").text).group(1)
    assert f"score {shown}/100" in client.get("/ledger").text
    assert state["money"]["cashback"] == 0                                    # nothing paid until the month closes
    assert client.post("/budget/release", follow_redirects=False).headers["location"].startswith("/cart?error")  # once only
    r = client.post("/month/settle", follow_redirects=False)
    assert r.headers["location"] == "/reward"
    # The ledger: one row per money movement, each with its PayPal id, adding up to the header's numbers.
    rows = client.get("/api/ledger").json()
    money = client.get("/api/state").json()["money"]
    kinds = [r["what"] for r in rows]
    assert kinds == ["Budget held", "Order captured", "Remainder released", "Week closed", "Reward paid back"]
    by = {r["what"]: r for r in rows}
    assert by["Budget held"]["amount"] == 140 and by["Budget held"]["paypal_id"].startswith("MOCK-AUTH-")
    assert by["Order captured"]["amount"] == money["spent"]
    assert by["Remainder released"]["amount"] == money["released"]
    assert by["Week closed"]["amount"] == by["Reward paid back"]["amount"] == money["cashback"] > 0
    assert by["Reward paid back"]["paypal_id"].startswith("MOCK-REF-")
    assert client.post("/month/settle", follow_redirects=False).headers["location"].startswith("/reward?error")  # not twice
    assert "ag-grid" in client.get("/ledger").text


def test_my_numbers_steer_the_plan_and_the_check_up_pays_through_the_month(client):
    client.post("/doctor", data={"doctor_said": "Eat less salt, walk more", "device": "Oven and stovetop", "budget": "130"})
    r = client.post("/numbers", data={"key": "ldl", "value": "162", "on": "2026-10-20", "target": "130"}, follow_redirects=False)
    assert r.headers["location"] == "/numbers"
    page = client.get("/numbers").text
    assert "LDL cholesterol" in page and "above your doctor&#39;s target" in page and "What the public sources say" in page
    assert client.post("/numbers", data={"key": "psa", "value": "3", "on": "2026-10-20"},
                       follow_redirects=False).headers["location"].startswith("/numbers?error")
    week_page = _built_week(client).text
    assert "From My numbers" in week_page and "LDL cholesterol" in week_page
    assert any(s["topic"] == "cholesterol" for s in client.get("/api/state").json()["plan"]["sources"])  # topic added
    # a week of shopping, then the check-up: the doctor says the goals are met
    client.post("/home", data={"have": []})
    client.get("/cart")
    token = client.post("/budget/authorize", data={"amount": "130"}, follow_redirects=False).headers["location"].split("token=")[1].split("&")[0]
    client.get(f"/budget/approved?token={token}")
    client.get("/cart")
    client.post("/cart/order")
    spent = client.get("/api/state").json()["money"]["spent"]
    client.post("/numbers/checkup", data={"verdict": "met", "on": "2026-11-10"})
    reward_page = client.get("/reward").text
    assert "Check-up bonus" in reward_page and "goals met" in reward_page
    from carpevigor import config as c
    rows = client.get("/api/ledger").json()
    assert any(r["what"] == "Check-up bonus" and r["amount"] == round(spent * c.CHECKUP_BONUS["met"], 2) for r in rows)


def test_guideline_numbers_have_a_source_and_show_only_when_the_source_says_them(monkeypatch):
    from carpevigor import guidelines, sources
    for e in guidelines.NUMBERS:  # every number points to a source we know, and quotes it
        assert guidelines.source_of(e["source"])["url"].startswith("https://") and e["quote"]
        assert e["topic"] is None or e["topic"] in sources.TOPICS
    salt = next(e for e in guidelines.NUMBERS if e["source"] == "who-sodium")
    # the source's own words, with other spacing and case: found
    monkeypatch.setattr(sources, "text_of", lambda sid: "WHO\n\n... LESS THAN 2000 mg/day   sodium (equivalent to < 5 g/day salt, ..."
                        if sid == "who-sodium" else None)
    assert guidelines.found(salt) is True
    week = guidelines.for_week(["blood_pressure"])
    assert any(e["source"] == "who-sodium" and e["checked"] for e in week)
    assert not any(e["topic"] == "cholesterol" for e in week)  # not this week's topic
    assert any(e["key"] == "sleep" and not e["checked"] for e in week)  # every week; not fetched here, still shown
    # a source text that no longer says it: the number is dropped, not shown and not given to the planner
    monkeypatch.setattr(sources, "text_of", lambda sid: "WHO\n\nThe page changed." if sid == "who-sodium" else None)
    assert guidelines.found(salt) is False
    assert not any(e["source"] == "who-sodium" for e in guidelines.for_week(["blood_pressure"]))
    assert "WHO — Sodium reduction" not in guidelines.as_task(guidelines.for_week(["blood_pressure"]))


def _two_closed_weeks(tmp_path, client, earned=(45.0, 40.0)):
    """Two closed weeks of 80 and 60 dollars on the given client; 85 earned by default, more than the larger capture."""
    from carpevigor import week as w
    paypal.use(client)
    s = Store(tmp_path / "m.sqlite")
    for spent, e in zip((80.0, 60.0), earned):
        order = w.start_authorization(s, 100.0, "http://x/ok", "http://x/ko")
        w.complete_authorization(s, order["id"])
        w.capture_order(s, spent, "groceries")
        w.release_remainder(s)
        w.close_week(s, reward.Reward(score=0.7, cashback_rate=e / spent, cashback=e, reasons=[]))
    return s


def test_a_refund_failing_halfway_never_pays_twice(tmp_path):
    from carpevigor import week as w

    class SecondFails(paypal.MockPayPal):
        fail = True

        def refund(self, capture_id, amount, note, invoice_id=""):
            if self.refunds and self.fail:  # the first refund goes through, the second does not
                raise paypal.PayPalError("422 UNPROCESSABLE", sent=False)
            return super().refund(capture_id, amount, note, invoice_id)

    pp = SecondFails()
    s = _two_closed_weeks(tmp_path, pp)
    with pytest.raises(paypal.PayPalError, match="trying again is safe"):
        w.settle_month(s)
    assert [r["amount"] for r in pp.refunds] == [80.0]                           # the first refund was made...
    assert w.month(s)["paid"][0]["amount"] == 80.0 and w.month(s)["weeks"]        # ...and saved; the month stays open
    pp.fail = False
    w.settle_month(s)                                                             # the retry pays only the rest
    assert round(sum(r["amount"] for r in pp.refunds), 2) == 85.0
    assert len({r["invoice_id"] for r in pp.refunds}) == len(pp.refunds)          # each refund its own invoice id
    assert round(sum(r["amount"] for r in s.get("refunds")), 2) == 85.0


def test_a_refund_whose_answer_was_lost_is_found_on_the_order_not_paid_again(tmp_path):
    from carpevigor import week as w

    class AnswerLost(paypal.MockPayPal):
        def refund(self, capture_id, amount, note, invoice_id=""):
            super().refund(capture_id, amount, note, invoice_id)       # PayPal refunds...
            raise paypal.PayPalError("no answer (ReadTimeout)", sent=True)  # ...and the answer never arrives

    pp = AnswerLost()
    s = _two_closed_weeks(tmp_path, pp, earned=(9.0, 12.0))
    paid = w.settle_month(s)
    assert len(pp.refunds) == 1 and paid[0]["amount"] == 21.0 and paid[0]["refund_id"] == pp.refunds[0]["id"]
    assert w.month(s)["last_paid"]["paid"] == 21.0


def test_the_reward_can_go_through_paypals_mcp_server_with_a_token_not_the_secret(monkeypatch):
    from carpevigor import config as c, paypal_mcp
    seen = {}

    def fake_refund(token, capture_id, amount, currency, note, invoice_id):
        seen.update(token=token, capture_id=capture_id, value=f"{amount:.2f}", invoice_id=invoice_id)
        return {"refund_id": "5RF12345AB678901C", "status": "COMPLETED", "amount": amount}

    monkeypatch.setattr(paypal_mcp, "refund", fake_refund)
    monkeypatch.setattr(c, "PAYPAL_REWARD_VIA", "mcp")
    sandbox = paypal.SandboxPayPal("id", "the-secret")
    monkeypatch.setattr(sandbox, "_headers", lambda: setattr(sandbox, "_token", "short-lived-token") or {})
    ref = sandbox.refund("27994506801896151", 4.5, "reward", invoice_id="CV-REWARD-27994506801896151-1")
    assert ref["via"] == "mcp" and ref["refund_id"] == "5RF12345AB678901C"
    assert seen == {"token": "short-lived-token", "capture_id": "27994506801896151", "value": "4.50",
                    "invoice_id": "CV-REWARD-27994506801896151-1"}
    # PayPal said no through the server: nothing moved, the error says so
    monkeypatch.setattr(paypal_mcp, "refund", lambda *a: (_ for _ in ()).throw(paypal_mcp.McpError("refused", sent=False)))
    with pytest.raises(paypal.PayPalError) as e:
        sandbox.refund("27994506801896151", 4.5, "reward")
    assert e.value.sent is False


def test_italian_sources_and_numbers_are_ready_and_kept_out_of_the_english_app(monkeypatch):
    from carpevigor import guidelines, rag, sources
    italian = {s["id"] for srcs in sources.TOPICS_IT.values() for s in srcs}
    assert set(sources.TOPICS_IT) <= set(sources.TOPICS)                      # the same topics as the English app
    for e in guidelines.NUMBERS_IT:
        assert e["source"] in italian and guidelines.source_of(e["source"])["url"].startswith("https://")
    monkeypatch.setattr(sources, "text_of", lambda sid: f"{sid}\nhttps://x\n\ntext")  # every source "fetched"
    english = {s["id"] for s in rag.everything()} | {u["id"] for u in sources.reference_for(list(sources.TOPICS))[1]}
    assert not english & italian                                               # never checked against Italian text
    assert {e["source"] for e in guidelines.for_week(["blood_pressure"], lang="it")} <= italian


def test_a_bot_check_page_is_not_saved_as_the_source(tmp_path, monkeypatch):
    from carpevigor import sources

    class Page:
        status_code, headers, text = 200, {"content-type": "text/html"}, "<html><title>Gcore</title>Checking your browser</html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(sources, "DIR", tmp_path)
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: Page())
    assert sources.fetch("it-min-sale") == []                                  # refused, reported, nothing written
    assert not (tmp_path / "it-min-sale.txt").exists()
