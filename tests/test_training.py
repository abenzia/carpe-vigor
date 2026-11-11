"""My training: the program follows the person's record, stops where the doctor must decide, and moves with feedback."""
import os

os.environ["LLM_PROVIDER"] = "mock"
os.environ["CARPE_VOICE_LANG"] = "en"

from datetime import date, timedelta

from fastapi.testclient import TestClient

from carpevigor import training as T
from carpevigor.store import Store

HIGH_PRESSURE = [{"key": "systolic", "value": 145, "date": "2026-11-01", "target": 130}]
SETUP = {"start": "2026-11-09", "setup": {"days": 4, "minutes": 30}, "level": 0, "log": {}}


def week_of(state, limits, on=date(2026, 11, 11)):
    return T.week(state, {}, [], limits, on)


def exercises(days):
    return [b["exercise"] for d in days for b in d.get("blocks", [])]


def test_the_record_shapes_every_exercise():
    doctor = T.read_doctor("Walk every day, but no running because of your knee.")
    assert doctor.avoid_impact and doctor.spare == ["knees"] and "knee" in doctor.quote
    L = T.limits({"age": 67, "bmi": 31.2}, HIGH_PRESSURE, doctor, {}, cleared=False)
    days = week_of(SETUP, L)
    chosen = exercises(days)
    assert chosen and not any(e.floor or e.knees or e.impact for e in chosen)        # BMI 31 and the doctor's knee
    assert all(b["seconds"] <= 20 for d in days for b in d.get("blocks", []) if b["seconds"])   # pressure: short holds
    assert all(d["rpe"] <= 6 for d in days)                                           # pressure: moderate effort
    assert T.summary(days, L)["balance_days"] == 3                                    # 67: balance on 3 days
    assert any("Lunges" in w for d in days for w in d.get("left_out", []))            # said, not silently dropped
    whys = " ".join(r["why"] for r in L.reasons)
    assert "you are 67" in whys and "BMI 31.2" in whys and "blood pressure" in whys and "knee" in whys


def test_where_the_doctor_must_decide_there_is_no_program():
    assert "adults" in T.limits({"age": 16}, [], None, {}, False).stop
    assert "pregnancy" in T.limits({"pregnant": True}, [], None, {}, False).stop
    assert "doctor" in T.limits({}, [], None, {"chest": True}, False).stop
    assert not T.limits({}, [], None, {"chest": True}, cleared=True).stop             # the doctor said yes


def test_a_readiness_yes_keeps_it_gentle_until_the_doctor_clears_it():
    L = T.limits({"activity": "active"}, [], None, {"joints": True}, cleared=False)
    days = week_of(SETUP | {"level": 2}, L)
    assert L.gentle and all(d["rpe"] <= 5 for d in days)
    assert all(T.LADDERS[p].index(e) == 0 for e in exercises(days) for p in T.LADDERS if e in T.LADDERS[p])


def test_feedback_moves_an_exercise_one_rung_and_pain_twice_drops_it():
    L = T.limits({}, [], None, {}, False)
    monday = date(2026, 11, 9)
    first = week_of(SETUP, L, monday)[0]
    squat = next(b for b in first["blocks"] if b["id"] in [e.id for e in T.LADDERS["squat"]])
    state = T.log_session(SETUP, "2026-11-09", True, 5, {squat["id"]: "easy"}, 35)
    later = week_of(state, L, monday + timedelta(days=7))[0]
    up = next(b for b in later["blocks"] if b["id"] in [e.id for e in T.LADDERS["squat"]])
    assert [e.id for e in T.LADDERS["squat"]].index(up["id"]) == [e.id for e in T.LADDERS["squat"]].index(squat["id"]) + 1
    for on in ("2026-11-09", "2026-11-16"):
        state = T.log_session(state, on, True, 6, {up["id"]: "hurt"}, 30)
    after = week_of(state, L, monday + timedelta(days=14))[0]
    assert not any(b["id"] in [e.id for e in T.LADDERS["squat"]] for b in after["blocks"])
    assert any("hurt twice" in w for w in after["left_out"])


def test_a_block_grows_only_when_it_was_done():
    L = T.limits({}, [], None, {}, False)
    start = date(2026, 11, 9)
    planned = [start + timedelta(days=i) for i in range(28) if i % 7 in T.SCHEDULE[4]]
    state = SETUP
    for d in planned:
        state = T.log_session(state, d.isoformat(), True, 5, {}, 30)
    next_block = start + timedelta(weeks=4)
    assert T.block_shift(state, next_block) == 1
    assert week_of(state, L, next_block)[0]["level"] == "intermediate"
    assert T.block_shift(SETUP, next_block) == -1                                      # nothing done: it does not grow


def test_the_pages_walk_from_questions_to_a_logged_session(tmp_path, monkeypatch):
    import app as webapp
    webapp.store = Store(tmp_path / "t.sqlite")
    webapp.store.put("health", {"consent": True, "age": 67, "height_cm": 170, "weight_kg": 92, "bmi": 31.8})
    webapp.store.put("profile", {"doctor_said": "No running, protect your knees."})
    client = TestClient(webapp.app, headers={"Origin": "http://testserver"})
    page = client.get("/training").text
    assert "Before you start" in page and "No running, protect your knees." in page
    r = client.post("/training/setup", data={"days": "4", "minutes": "30"}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/training").text
    assert "Built around your record" in page and "you are 67" in page and "This week" in page
    today = date.today().isoformat()
    day = client.get(f"/training/day/{today}").text
    assert "How did it go?" in day
    client.post(f"/training/log/{today}", data={"done": "yes", "rpe": "6"})
    assert webapp.store.get("training")["log"][today]["rpe"] == 6


def test_bmi_comes_from_height_and_weight_when_not_stored():
    L = T.limits({"height_cm": 165, "weight_kg": 90}, [], None, {}, False)
    assert L.low_impact and any("BMI 33.1" in r["why"] for r in L.reasons)


def test_every_exercise_and_warm_up_move_has_its_clip():
    from pathlib import Path
    from carpevigor.exercises import COOL_DOWN, WARM_UP, all_exercises
    clips = {e.clip for e in all_exercises().values() if e.clip} | {c for *_, c in WARM_UP + COOL_DOWN if c}
    from carpevigor import coach
    clips |= {name for name, _, _ in coach.EXERCISES}   # the Movement page's demonstrations
    from carpevigor.exercises import media
    files = lambda c: media(c)["src"] if isinstance(media(c)["src"], list) else [media(c)["src"]]
    missing = sorted(c for c in clips if not all(Path(f.lstrip("/")).exists() for f in files(c)))
    assert not missing, f"no clip for: {missing}"


def test_the_library_shows_every_exercise(tmp_path):
    import app as webapp
    webapp.store = Store(tmp_path / "t.sqlite")
    page = TestClient(webapp.app).get("/training/exercises").text
    assert all(e.name in page for e in T.all_exercises().values())
    assert page.count("<video") >= 15
