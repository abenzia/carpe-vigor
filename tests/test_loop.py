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
    assert tight.within_budget and tight.skipped


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
    r = client.post("/budget/authorize", data={"amount": "70"}, follow_redirects=False)
    approve = r.headers["location"]
    token = approve.split("token=")[1].split("&")[0]
    r = client.get(f"/budget/approved?token={token}", follow_redirects=False)
    r = client.get("/cart")
    assert "Approve — order and pay" in r.text
    r = client.post("/cart/order", follow_redirects=False)
    assert r.headers["location"] == "/reward"
    state = client.get("/api/state").json()
    assert state["money"]["spent"] > 0 and state["money"]["spent"] <= 70
    client.post("/reward/steps", data={"steps": "8200, 6100, 9400, 7300, 4800, 11200, 7600"}, follow_redirects=False)
    r = client.get("/reward")
    assert "Care that pays you back" in r.text
    client.post("/budget/release", follow_redirects=False)
    state = client.get("/api/state").json()
    assert state["money"]["released"] == round(70 - state["money"]["spent"], 2)
