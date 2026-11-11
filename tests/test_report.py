from fastapi.testclient import TestClient

from carpevigor import activity, config, diary, llm
from carpevigor.store import Store


def test_each_synced_day_is_kept_under_its_date_and_the_report_adds_them_up(tmp_path):
    s = Store(tmp_path / "a.sqlite")
    activity.record(s, {"steps": [8000, 3000, 9000], "exercise_min": [30, 0, 45]}, today="2026-11-11")
    activity.record(s, {"steps": [9500]}, today="2026-11-11")             # the evening sync replaces today's steps
    assert s.get("days")["2026-11-09"] == {"steps": 8000, "exercise_min": 30}
    assert s.get("days")["2026-11-11"] == {"steps": 9500, "exercise_min": 45}
    s.put("diary", [{"at": "2026-11-10T13:00", "nutrition": {"kcal": 640.4}},
                    {"at": "2026-11-10T20:00", "nutrition": {"kcal": 700}}])
    w = activity.report(s, "week", today="2026-11-11")
    assert [r["on"] for r in w["rows"]][-1] == "2026-11-11" and len(w["rows"]) == 7
    assert w["days_known"] == 3 and w["days_moved"] == 2                  # 8,000 and 9,500 are over 7,000
    assert w["minutes"] == 75 and w["minutes_goal"] == 150 and not w["minutes_met"]
    assert w["rows"][-2]["kcal"] == 1340 and w["rows"][0]["kcal"] is None  # a day with nothing said is no data, not 0
    assert len(activity.report(s, "month", today="2026-11-11")["rows"]) == 30
    assert activity.report(s, "day", today="2026-11-11")["minutes_goal"] == 21


def test_the_watch_sends_exercise_minutes_and_the_report_page_shows_them(tmp_path, monkeypatch):
    import app as webapp
    webapp.store = Store(tmp_path / "t.sqlite")
    monkeypatch.setattr(config, "API_TOKEN", "s3cret-token")
    c = TestClient(webapp.app, headers={"Origin": "http://testserver"})
    c.post("/numbers/measures", data={"consent": "1", "height_cm": "178", "weight_kg": "95"})
    r = c.post("/api/health", json={"steps": "8.234\n7.600", "exercise_min": "35\n22 min"},
               headers={"Authorization": "Bearer s3cret-token"})
    assert r.status_code == 200 and "22 exercise minutes today" in r.json()["spoken"]
    page = c.get("/report?view=week").text
    assert "How you are" in page and "57<span" in page and "7,600" in page
    assert "Never for your weight" in page
    assert c.get("/report?view=nonsense").status_code == 200


def test_a_photo_of_the_plate_is_read_by_the_model_counted_by_code_and_not_kept(tmp_path, monkeypatch):
    seen = {}

    def fake_ask(system, task, shape, tier="strong", temperature=0.1, attachment=None):
        seen["attachment"] = attachment
        return diary.Breakdown(dish="pasta with tomato", parts=[diary.Part(name="spaghetti", grams=100)])
    monkeypatch.setattr(llm, "ask", fake_ask)
    monkeypatch.setattr(diary.nutrition, "count", lambda parts, n: type("V", (), {
        "model_dump": lambda self: {"kcal": 371 * parts[0][1] / 100}})())
    entry = diary.photo(b"\xff\xd8jpeg", "image/jpeg", "large")
    assert seen["attachment"] == (b"\xff\xd8jpeg", "image/jpeg") and entry["from_photo"] and entry["estimate"]
    assert round(entry["nutrition"]["kcal"]) == 519                         # 140 g: a large portion is 1.4 times
    assert b"jpeg" not in repr(entry).encode()                              # the photo itself is not in the entry
    for bad in [(b"x", "application/pdf"), (b"", "image/png")]:
        try:
            diary.photo(*bad)
            raise AssertionError("accepted")
        except ValueError:
            pass
    monkeypatch.setattr(llm, "ask", lambda *a, **k: diary.Breakdown(dish="", parts=[]))
    try:
        diary.photo(b"\xff\xd8", "image/jpeg")
        raise AssertionError("a photo with no food was counted")
    except ValueError as e:
        assert "No food" in str(e)


def test_the_lab_report_can_be_sent_from_the_doctors_page_and_an_error_comes_back_there(tmp_path):
    import app as webapp
    webapp.store = Store(tmp_path / "d.sqlite")
    c = TestClient(webapp.app, headers={"Origin": "http://testserver"})
    assert 'action="/numbers/report"' in c.get("/doctor").text
    r = c.post("/numbers/report", files={"file": ("r.txt", b"x", "text/plain")}, data={"send_ok": "1", "back": "/doctor"},
               follow_redirects=False)
    assert r.headers["location"].startswith("/doctor?error=")
    r = c.post("/numbers/report", files={"file": ("r.txt", b"x", "text/plain")}, data={"send_ok": "1", "back": "//evil"},
               follow_redirects=False)
    assert r.headers["location"].startswith("/numbers?error=")                  # nowhere else
