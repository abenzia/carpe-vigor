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


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app as webapp
    webapp.store = Store(tmp_path / "t.sqlite")
    paypal.use(paypal.MockPayPal())
    return TestClient(webapp.app)


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


def test_reward_rewards_behaviour_not_weight():
    good = reward.score(reward.WeekBehaviour(14, 12, 6, True, 60.0))
    assert good.earned and 0 < good.cashback_rate <= 0.10 and good.cashback == round(60 * good.cashback_rate, 2)
    lazy = reward.score(reward.WeekBehaviour(14, 2, 1, False, 60.0))
    assert not lazy.earned
    broke_list = reward.score(reward.WeekBehaviour(14, 14, 7, False, 60.0))
    assert broke_list.score < 1.0 and "don't rebuy" in broke_list.reasons[2]


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


def test_cart_buys_from_the_recipes_store_list_when_there_is_one():
    catalog = Catalog.load()
    recipes = [{"title": "Soup", "ingredients": ["1 potato, cubed", "500g water", "1 carrot"], "buy": ["Carrots", "Yellow onions"]}]
    names = {l.item.name for l in cart_agent.build(recipes, Pantry(), catalog, budget=100.0).lines}
    assert names == {"Carrots", "Yellow onions"}


def test_sources_pick_topics_and_flag_clinical():
    assert sources.topics_for("my doctor says I have high blood pressure, eat less salt") == ["blood_pressure"]
    assert "activity" in sources.topics_for("walk more")
    assert sources.mentions_clinical("should I stop my statin?")
    assert not sources.mentions_clinical("eat less salt")


def test_review_board_mock_is_honest_about_itself():
    report = review_board.convene("Salt raises blood pressure. Walking helps.", "SOURCE: test\n\nsome text")
    assert report["provider"] == "mock" and report["approved"]
    assert all("Simulated" in r["checks"][0] or "Ruled on" in r["checks"][0] for r in report["reviewers"])


def test_full_loop_through_the_web_app(client):
    r = client.post("/doctor", data={"doctor_said": "High blood pressure: eat less salt, lose weight, walk more",
                                     "device": "Thermomix / Bimby", "constraints": "", "budget": "70"}, follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/week?build=1")
    assert r.status_code == 200 and "Review board" in r.text and "simulated" in r.text
    r = client.post("/week/cooked", data={"title": "Lentil and vegetable soup"}, follow_redirects=False)
    r = client.post("/home", data={"have": ["DAI-BUTTER-250", "FAT-EVOO-500", "GRA-BROWN-1K"]}, follow_redirects=False)
    r = client.get("/cart")
    assert "Authorize this week's budget" in r.text
    assert "raise it by" in r.text  # 70 does not buy the demo week: the cart says so before cutting anything
    r = client.post("/budget/authorize", data={"amount": "120"}, follow_redirects=False)
    approve = r.headers["location"]
    token = approve.split("token=")[1].split("&")[0]
    r = client.get(f"/budget/approved?token={token}", follow_redirects=False)
    r = client.get("/cart")
    assert "Approve — order and pay" in r.text
    r = client.post("/cart/order", follow_redirects=False)
    assert r.headers["location"] == "/reward"
    state = client.get("/api/state").json()
    assert state["money"]["spent"] > 0 and state["money"]["spent"] <= 120
    client.post("/reward/steps", data={"steps": "8200, 6100, 9400, 7300, 4800, 11200, 7600"}, follow_redirects=False)
    r = client.get("/reward")
    assert "Care that pays you back" in r.text
    client.post("/budget/release", follow_redirects=False)
    state = client.get("/api/state").json()
    assert state["money"]["released"] == round(120 - state["money"]["spent"], 2)
    for title in [r["title"] for r in state["plan"]["plan"]["recipes"]][:12]:
        client.post("/week/cooked", data={"title": title}, follow_redirects=False)
    client.post("/reward/pay", follow_redirects=False)
    # The ledger: one row per money movement, each with its PayPal id, adding up to the header's numbers.
    rows = client.get("/api/ledger").json()
    money = client.get("/api/state").json()["money"]
    kinds = [r["what"] for r in rows]
    assert kinds == ["Budget held", "Order captured", "Remainder released", "Reward paid back"]
    by = {r["what"]: r for r in rows}
    assert by["Budget held"]["amount"] == 120 and by["Budget held"]["paypal_id"].startswith("MOCK-AUTH-")
    assert by["Order captured"]["amount"] == money["spent"]
    assert by["Remainder released"]["amount"] == money["released"]
    assert by["Reward paid back"]["amount"] == money["cashback"] > 0 and by["Reward paid back"]["paypal_id"].startswith("MOCK-REF-")
    assert "ag-grid" in client.get("/ledger").text
