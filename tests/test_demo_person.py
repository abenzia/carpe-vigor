"""The public demo's example person: the person's days end today, the money keeps its real sandbox dates and ids."""
import os

os.environ["LLM_PROVIDER"] = "mock"
os.environ["CARPE_VOICE_LANG"] = "en"

from datetime import date

from fastapi.testclient import TestClient

from carpevigor import demo_person
from carpevigor.store import Store


def test_the_days_move_to_today_and_the_money_does_not(tmp_path):
    store = Store(tmp_path / "d.sqlite")
    store.put("profile", {"doctor_said": "something typed by a judge"})
    demo_person.load(store, today=date(2026, 12, 2))  # 20 days after the recording
    assert max(store.get("days")) == "2026-12-02"  # recorded up to 12 Nov, the recording day
    assert store.get("authorization")["authorization_id"] == "4NP38678F46892931"
    assert store.get("refunds")[0]["refund_id"] == "40198090VD119811D"
    closed = store.events("week_closed")[0]
    assert closed["earned"] == 17.99 and closed["at"].startswith("2026-11-10")
    assert "judge" not in str(store.get("profile"))


def test_the_button_exists_only_on_the_public_demo(tmp_path, monkeypatch):
    import app as webapp
    webapp.store = Store(tmp_path / "t.sqlite")
    webapp.store.put("profile", {"doctor_said": "my own data"})
    client = TestClient(webapp.app, headers={"Origin": "http://testserver"})
    monkeypatch.setattr(webapp.config, "HOSTED", False)
    assert client.post("/demo/example", follow_redirects=False).status_code == 404
    assert webapp.store.get("profile") == {"doctor_said": "my own data"}
    monkeypatch.setattr(webapp.config, "HOSTED", True)
    assert client.post("/demo/example", follow_redirects=False).status_code == 303
    assert webapp.store.get("authorization")["authorization_id"] == "4NP38678F46892931"


def test_the_simulated_reader_reads_only_the_invented_report():
    from carpevigor import report
    draft = report.read(report.SAMPLE.read_bytes(), "application/pdf")
    assert draft["test_date"] == "2026-10-20"
    assert {r["measure"]: r["value"] for r in draft["rows"]}["ldl"] == 138 and all(r["ok"] for r in draft["rows"])
    assert report.read(b"%PDF-1.4 another report", "application/pdf")["rows"] == []


def test_a_photo_address_names_its_dish(tmp_path):
    """Caches keep a photo for a day: an address by position alone showed the previous week's dish."""
    import app as webapp
    from carpevigor import dish_photo
    webapp.store = Store(tmp_path / "p.sqlite")
    demo_person.load(webapp.store)
    first = webapp.store.get("plan")["plan"]["recipes"][0]
    page = TestClient(webapp.app).get("/recipes").text
    assert f'/dish/0.jpg?k={dish_photo.path(first).name}"' in page
