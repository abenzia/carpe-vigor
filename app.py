"""Carpe Vigor — the web app. Five screens, one loop.

    python -m uvicorn app:app --reload --port 8080

1. /doctor   "My doctor said": goals, constraints, kitchen device → topics and what goes back to the doctor
2. /week     the plan: 14 meals with "why" and "evidence", the review board's report, movement for 7 days
3. /home     pantry checklist, "finish, don't rebuy" with swaps (optional fridge photo pre-fill)
4. /cart     the agent's cart within the authorized budget → PayPal approval → order captured
5. /reward   what the week paid back, and why

Budget / spent / released is shown on every screen (base.html).
"""
from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from carpevigor import (__version__, ask, cart_agent, checkup, config, diary, guidelines, kitchen, nutrition, planner, profile,
                        rag, reward, sources, ui, week)
from carpevigor import apple_health, coach, health, phone, report
from carpevigor.catalog import Catalog
from carpevigor.pantry import Pantry
from carpevigor.paypal import PayPalError
from carpevigor.store import Store

app = FastAPI(title="Carpe Vigor", version=__version__)
app.mount("/static", StaticFiles(directory=str(config.ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(config.ROOT / "templates"))
# A recipe step as a recipe card prints it: what to do, the machine setting in bold, what follows
templates.env.filters["step_parts"] = kitchen.step_parts
store = Store()
catalog = Catalog.load()


# The only ways in for a phone shortcut (no Origin, maybe through the tunnel); each checks the token itself
PHONE_DOORS = ("/api/meal", "/api/health")


def _open_to_phones(path: str) -> bool:
    """What the tunnel may reach: the shortcuts' doors and the phone page (/m, its own cookie; its styles are inline)."""
    return path in PHONE_DOORS or path == "/m" or path.startswith("/m/pair/")


@app.middleware("http")
async def same_origin_posts(request: Request, call_next):
    """A form on another site cannot post here: the app moves money (PayPal) and keeps health data. Browsers send
    Origin (or at least Referer) with every POST; a post must show it came from this app's own pages, or it is refused
    (fail closed). /api/meal is the exception, for a phone shortcut that sends no Origin: it has its own token."""
    # Through the Cloudflare tunnel (marked by cf-connecting-ip) only the watch's door is open: the tunnel exists for
    # the shortcut, and anyone holding its address must not read measures, the diary or press PayPal buttons
    if "cf-connecting-ip" in request.headers and not _open_to_phones(request.url.path):
        return JSONResponse({"error": "Not available here."}, status_code=404)
    # /m is exempt too: its cookie is SameSite=Lax, so a form on another site arrives without it and is refused there
    if request.method == "POST" and request.url.path not in PHONE_DOORS and request.url.path != "/m":
        source = request.headers.get("origin") or request.headers.get("referer") or ""
        if not source or urlparse(source).netloc != request.headers.get("host", ""):
            return JSONResponse({"error": "Posts are accepted from this app's own pages only."}, status_code=403)
    return await call_next(request)


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    lang = ui.lang_of(request.cookies.get("lang"))
    base = {"request": request, "money": week.status(store), "currency": config.CURRENCY,
            "profile": store.get("profile"), "plan": store.get("plan"), "version": __version__,
            "lang": lang, "t": lambda key: ui.t(key, lang), "nav": ui.NAV, "more": ui.MORE}
    return templates.TemplateResponse(request, name, {**base, **ctx})


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """The landing (Forest Premium): its own styles and its own Italian/English switch (static/landing.js)."""
    return templates.TemplateResponse(request, "landing.html", {"version": __version__})


@app.get("/lang")
def set_lang(to: str = "en", back: str = "/journey"):
    """The interface's language, kept in a cookie. `back` must be a page of this app, never another site."""
    target = back if back.startswith("/") and not back.startswith("//") else "/journey"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie("lang", ui.lang_of(to), max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


@app.get("/journey", response_class=HTMLResponse)
def journey(request: Request):
    """My journey: where the person is, in one page — the doctor's goals, today's meals, what was eaten, steps, money."""
    prof, plan = store.get("profile"), store.get("plan")
    today = planner.DAYS[datetime.now().weekday()]
    meals = [{"i": i, "kind": planner.dish_kind(r), **r} for i, r in enumerate(plan["plan"]["recipes"]) if r["day"] == today] if plan else []
    return render(request, "journey.html", today=today, meals=meals, cooked=set((plan or {}).get("cooked", [])),
                  diary_today=diary.day(store.get("diary", [])), steps=store.get("steps", []),
                  month=week.month(store), checkups=store.get("checkups", []), reading=health.read(store.get("health") or {}))


# 1 ------------------------------------------------------------------------------------------------------------------
@app.get("/doctor", response_class=HTMLResponse)
def doctor(request: Request):
    return render(request, "doctor.html", devices=profile.DEVICES, sources=sources.status())


@app.post("/doctor")
def doctor_submit(request: Request, doctor_said: str = Form(...), device: str = Form(...), constraints: str = Form(""),
                  budget: float = Form(140.0), report_attached: str = Form(""), people: int = Form(1)):
    guidance = profile.read(doctor_said, device, constraints, bool(report_attached))
    people = min(6, max(1, people))
    store.put("profile", {"doctor_said": doctor_said, "device": device, "people": people, "constraints_text": constraints,
                          "budget": budget, "guidance": guidance.model_dump()})
    store.delete("plan")
    store.log("profile", {"topics": guidance.topics})
    return RedirectResponse("/week?build=1", status_code=303)


# 2 ------------------------------------------------------------------------------------------------------------------
# With real models a week takes about three minutes: it is built in the background while the screen shows each
# step (building.html asks /api/building every second). One build at a time: the app has one person.
building = {"running": False, "done": False, "step": "", "percent": 0, "error": ""}
_building_lock = threading.Lock()


def start_building(prof: dict):
    with _building_lock:
        if building["running"]:
            return  # a reload of the waiting screen does not start a second week
        building.update(running=True, done=False, step="Starting", percent=0, error="")
    threading.Thread(target=_build_week, args=(prof,), daemon=True).start()


def _build_week(prof: dict):
    def progress(step: str, percent: int):
        with _building_lock:
            building.update(step=step, percent=percent)
    try:
        guidance = profile.Guidance.model_validate(prof["guidance"])
        # My numbers (optional): a measure off the doctor's target adds its topic and a lifestyle goal for the week
        focus = [v for v in checkup.view(store.get("numbers", [])) if v["target"] is not None and not v["status"].startswith("at ")]
        guidance.topics = list(dict.fromkeys(guidance.topics + [v["topic"] for v in focus]))
        guidance.goals = guidance.goals + [f"Food and habits that help with {v['label']}" for v in focus]
        made, report, used = planner.make(guidance, prof["device"], prof.get("people", 1), progress,
                                          energy=health.for_planner(store.get("health") or {}),
                                          activity=(store.get("health") or {}).get("activity"), steps=store.get("steps", []))
        plan = {"plan": made.model_dump(), "report": report, "sources": used, "cooked": [],
                "focus": [f"{v['label']}: {v['status']}" for v in focus], "numbers": guidelines.for_week(guidance.topics)}
        store.put("plan", plan)
        store.log("plan", {"approved": report.get("approved"), "provider": report.get("provider")})
        with _building_lock:
            building.update(running=False, done=True, step="Your week is ready", percent=100)
    except Exception as error:  # shown on the waiting screen, with the way to try again: never a silent stop
        with _building_lock:
            building.update(running=False, done=False, error=f"{type(error).__name__}: {error}")


@app.get("/api/building")
def building_status():
    with _building_lock:
        return dict(building)


@app.get("/week", response_class=HTMLResponse)
def week_view(request: Request, build: int = 0, day: str = ""):
    prof = store.get("profile")
    if not prof:
        return RedirectResponse("/doctor")
    plan = store.get("plan")
    if build or not plan:
        start_building(prof)
        return render(request, "building.html")
    day = day if day in planner.DAYS else planner.DAYS[datetime.now().weekday()]
    recipes = [{"i": i, "kind": planner.dish_kind(r), **r} for i, r in enumerate(plan["plan"]["recipes"])]
    return render(request, "week.html", week_plan=plan["plan"], recipes=recipes, report=plan["report"], used=plan["sources"],
                  numbers=plan.get("numbers") or guidelines.for_week(prof["guidance"]["topics"]),
                  cooked=set(plan.get("cooked", [])), days=planner.DAYS, day=day)


def _plan_or_start():
    """The week's plan, or None when there is none yet (the page then says how to start)."""
    plan = store.get("plan")
    return plan if plan and plan.get("plan") else None


@app.get("/recipes", response_class=HTMLResponse)
def recipes_view(request: Request, kind: str = "all"):
    plan = _plan_or_start()
    cards = [{"i": i, **r, "kind": planner.dish_kind(r)} for i, r in enumerate(plan["plan"]["recipes"])] if plan else []
    shown = [c for c in cards if kind == "all" or c["kind"] == kind or (kind == "quick" and c.get("total_minutes", 99) <= 30)]
    return render(request, "recipes.html", cards=shown, kind=kind, kinds=planner.DISH_KINDS, total=len(cards),
                  cooked=set((plan or {}).get("cooked", [])))


@app.get("/recipes/{i}", response_class=HTMLResponse)
def recipe_view(request: Request, i: int):
    plan = _plan_or_start()
    if not plan or not 0 <= i < len(plan["plan"]["recipes"]):
        return RedirectResponse("/recipes")
    r = plan["plan"]["recipes"][i]
    return render(request, "recipe.html", r={**r, "kind": planner.dish_kind(r)}, i=i, cooked=set(plan.get("cooked", [])),
                  device=(store.get("profile") or {}).get("device", ""))


@app.get("/move", response_class=HTMLResponse)
def move_view(request: Request):
    plan = _plan_or_start()
    return render(request, "move.html", movement=plan["plan"]["movement"] if plan else [], days=planner.DAYS,
                  coach=((plan or {}).get("report") or {}).get("coach"),
                  steps=store.get("steps", []), goal=config.STEPS_GOAL)


@app.get("/body", response_class=HTMLResponse)
def body_view(request: Request, day: str = ""):
    plan = _plan_or_start()
    movement = plan["plan"]["movement"] if plan else []
    day = day if day in planner.DAYS else planner.DAYS[datetime.now().weekday()]
    line = movement[planner.DAYS.index(day)] if len(movement) == 7 else ""
    return render(request, "body.html", day=day, days=planner.DAYS, line=line, areas=coach.areas_worked(line),
                  measures=store.get("health", {}))


@app.get("/team", response_class=HTMLResponse)
def team_view(request: Request):
    plan = _plan_or_start()
    return render(request, "team.html", report=(plan or {}).get("report"), used=(plan or {}).get("sources", []),
                  numbers=(plan or {}).get("numbers", []), kitchen=((plan or {}).get("report") or {}).get("kitchen"),
                  coach=((plan or {}).get("report") or {}).get("coach"))


# My numbers (optional) -------------------------------------------------------------------------------------------
@app.get("/numbers", response_class=HTMLResponse)
def numbers_view(request: Request, error: str = ""):
    rows = store.get("numbers", [])
    shown = checkup.view(rows)
    quotes = store.get("quotes", {})  # what the sources say about each measure: retrieved once, kept
    for v in shown:
        if v["key"] not in quotes:
            quotes[v["key"]] = rag.quotes(f"What is a healthy {v['label']} level for adults, and how do food and habits affect it?",
                                          [v["topic"]])
    store.put("quotes", quotes)
    return render(request, "numbers.html", measures=checkup.MEASURES, shown=shown, quotes=quotes, error=error,
                  checkups=store.get("checkups", []), verdicts=checkup.VERDICTS, bonus_rates=config.CHECKUP_BONUS,
                  spent_since=spent_since_last_checkup(), month=week.month(store),
                  health=store.get("health") or {}, reading=health.read(store.get("health") or {}),
                  activities=list(health.ACTIVITY), health_sources=health.SOURCES)


def _number(value: str, low: float, high: float) -> float | None:
    """A measure typed in a form, or None when empty or outside what a person can measure."""
    try:
        v = float(value.replace(",", "."))
    except ValueError:
        return None
    return v if low <= v <= high else None


@app.post("/numbers/report")
async def report_upload(file: UploadFile = File(...), send_ok: str = Form("")):
    """A lab report to read: sent to Gemini only with the box ticked; the file is read once and never stored."""
    if not send_ok:
        return RedirectResponse("/numbers?error=" + quote("Tick the box to send the report to be read: nothing was sent."),
                              status_code=303)
    data = await file.read(report.MAX_BYTES + 1)
    try:
        draft = report.read(data, file.content_type or "")
    except ValueError as error:
        return RedirectResponse(f"/numbers?error={quote(str(error))}", status_code=303)
    store.put("report_draft", draft)   # the values read, waiting for the person's check; not the file
    return RedirectResponse("/numbers/report", status_code=303)


@app.get("/numbers/report", response_class=HTMLResponse)
def report_check(request: Request, error: str = ""):
    draft = store.get("report_draft")
    if not draft:
        return RedirectResponse("/numbers")
    return render(request, "report.html", draft=draft, measures=checkup.MEASURES, error=error)


@app.post("/numbers/report/confirm")
async def report_confirm(request: Request):
    draft = store.get("report_draft")
    if not draft:
        return RedirectResponse("/numbers", status_code=303)
    form = await request.form()
    picked = {i: (str(form.get(f"value_{i}", "")), str(form.get(f"date_{i}", "")), str(form.get(f"target_{i}", "")))
              for i in range(len(draft["rows"])) if form.get(f"keep_{i}")}
    try:
        rows = report.confirm(store.get("numbers", []), draft, picked)
    except ValueError as error:
        return RedirectResponse(f"/numbers/report?error={quote(str(error))}", status_code=303)
    store.put("numbers", rows)
    store.delete("report_draft")
    store.log("report", {"kept": len(picked)})  # how many, not which values
    return RedirectResponse("/numbers", status_code=303)


@app.post("/numbers/report/discard")
def report_discard():
    store.delete("report_draft")
    return RedirectResponse("/numbers", status_code=303)


@app.post("/numbers/measures")
def measures_save(consent: str = Form(""), height_cm: str = Form(""), weight_kg: str = Form(""), waist_cm: str = Form(""),
                  age: str = Form(""), sex: str = Form(""), activity: str = Form(""), pregnant: str = Form(""),
                  goal_kg: str = Form(""), pace: str = Form(""), doctor_kcal: str = Form("")):
    """The person's measures. Without the consent box ticked nothing is kept (and what was kept is deleted)."""
    if not consent:
        store.delete("health")
        return RedirectResponse("/numbers?error=" + quote("Nothing kept: tick the consent box to save your measures."),
                                status_code=303)
    h = {"consent": True, "height_cm": _number(height_cm, 120, 230), "weight_kg": _number(weight_kg, 30, 300),
         "waist_cm": _number(waist_cm, 40, 200), "age": _number(age, 12, 110), "sex": sex if sex in ("female", "male") else None,
         "activity": activity if activity in health.ACTIVITY else None, "pregnant": bool(pregnant),
         "goal_kg": _number(goal_kg, 30, 300), "pace": _number(pace, 0.25, 1.0), "doctor_kcal": _number(doctor_kcal, 800, 5000)}
    if h["age"]:
        h["age"] = int(h["age"])
    if h["height_cm"] and h["weight_kg"]:
        h["bmi"] = health.bmi(h["height_cm"], h["weight_kg"])
    store.put("health", {k: v for k, v in h.items() if v not in (None, "")})
    store.log("measures", {"kept": True})  # the values stay in the store, not in the log
    return RedirectResponse("/numbers", status_code=303)


@app.post("/numbers/measures/delete")
def measures_delete():
    store.delete("health")
    return RedirectResponse("/numbers", status_code=303)


@app.post("/numbers")
def numbers_add(key: str = Form(...), value: float = Form(...), on: str = Form(...), target: str = Form("")):
    try:
        rows = checkup.add(store.get("numbers", []), key, value, on, float(target) if target.strip() else None)
    except ValueError as e:
        return RedirectResponse(f"/numbers?error={e}", status_code=303)
    store.put("numbers", rows)
    store.log("numbers", {"key": key, "on": on})  # the value stays in the store, not in the log
    return RedirectResponse("/numbers", status_code=303)


def spent_since_last_checkup() -> float:
    last = (store.get("checkups") or [{}])[-1].get("at", "")
    return round(sum(e["amount"] for e in store.events("captured") if e["at"] > last), 2)


@app.post("/numbers/checkup")
def numbers_checkup(verdict: str = Form(...), on: str = Form(...)):
    """The doctor's verdict at a check-up. In the product the doctor confirms it from their own portal; in the demo it
    is entered here, and the screen says so."""
    try:
        spent = spent_since_last_checkup()
        earned = checkup.bonus(verdict, spent)
    except ValueError as e:
        return RedirectResponse(f"/numbers?error={e}", status_code=303)
    checkups = store.get("checkups", [])
    checkups.append({"on": on, "verdict": verdict, "spent": spent, "earned": earned,
                     "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")})  # same clock as the log
    store.put("checkups", checkups)
    if earned > 0:
        week.add_checkup_bonus(store, verdict, spent, earned)
    return RedirectResponse("/numbers", status_code=303)


# Ask the sources ---------------------------------------------------------------------------------------------------
@app.get("/ask", response_class=HTMLResponse)
def ask_view(request: Request):
    return render(request, "ask.html", asked=store.get("asked", []), library=len(sources.library()))


@app.post("/ask")
def ask_post(question: str = Form(...)):
    question = question.strip()[:500]
    if question:
        out = ask.answer(question, store.get("numbers", []))
        store.put("asked", [out] + store.get("asked", [])[:9])  # the last ten, newest first
        store.log("asked", {"held_back": bool(out["held_back"]), "passages": len(out["passages"])})  # not the question
    return RedirectResponse("/ask", status_code=303)


@app.post("/week/cooked")
def cooked(title: str = Form(...), back: str = Form("/week")):
    plan = store.get("plan")
    if plan:
        done = set(plan.get("cooked", []))
        done.symmetric_difference_update({title})
        plan["cooked"] = sorted(done)
        store.put("plan", plan)
        # a cooked meal of the plan goes into today's diary with its recipe's values; unticked, it comes out again
        entries = [e for e in store.get("diary", []) if not (e.get("plan") and e["dish"] == title
                                                              and e["at"][:10] == diary.day([])["on"])]
        recipe = next((r for r in plan["plan"]["recipes"] if r["title"] == title), None)
        if title in done and recipe and (entry := diary.from_plan(recipe)):
            entries.append(entry)
        store.put("diary", entries)
    # back to the page the button was on (journey, week, a recipe), never to another site
    return RedirectResponse(back if back.startswith("/") and not back.startswith("//") else "/week", status_code=303)


# What I ate -------------------------------------------------------------------------------------------------------
@app.get("/diary", response_class=HTMLResponse)
def diary_view(request: Request, error: str = "", on: str = ""):
    # The shortcut's address and secret are shown only to someone sitting at this computer: the connection itself comes
    # from this machine (not the Host header, which a client writes), and it went through no proxy. A tunnel also
    # connects from this machine, so its marks (cf-connecting-ip, x-forwarded-for...) rule it out.
    peer = request.client.host if request.client else ""
    proxied = any(h in request.headers for h in ("cf-connecting-ip", "x-forwarded-for", "forwarded", "x-real-ip"))
    # and the page was asked for by a loopback name: a site that rebinds its own name to 127.0.0.1 (DNS rebinding)
    # connects from here too, but its Host is not ours
    loopback_name = request.url.hostname in ("127.0.0.1", "localhost", "::1")
    here = peer in ("127.0.0.1", "::1") and loopback_name and not proxied
    return render(request, "diary.html", today=diary.day(store.get("diary", []), on or None), error=error,
                  portions=list(diary.PORTIONS), food_db=nutrition.available(), watch=bool(config.API_TOKEN),
                  setup={"url": config.PUBLIC_URL, "token": config.API_TOKEN} if here and config.API_TOKEN else None,
                  qr=phone.qr_svg(f"{config.PUBLIC_URL}/m/pair/{phone.new_code()}")
                  if here and config.API_TOKEN and config.PUBLIC_URL else None)


def _phone_ok(request: Request) -> bool:
    given = request.cookies.get(phone.COOKIE, "")
    return bool(config.API_TOKEN) and secrets.compare_digest(given, config.API_TOKEN)


@app.get("/m/pair/{code}", response_class=HTMLResponse)
def phone_pair(request: Request, code: str):
    """Opened by the phone's camera from the QR code: one use, ten minutes, then a cookie keeps the phone paired."""
    if not config.API_TOKEN or not phone.take(code):
        return templates.TemplateResponse(request, "phone.html", {"paired": False, "expired": True, "version": __version__})
    response = RedirectResponse("/m", status_code=303)
    response.set_cookie(phone.COOKIE, config.API_TOKEN, max_age=60 * 60 * 24 * 90, httponly=True,
                        secure=request.url.scheme == "https" or "cf-connecting-ip" in request.headers, samesite="lax")
    return response


@app.get("/m", response_class=HTMLResponse)
def phone_page(request: Request, said: str = "", error: str = ""):
    if not _phone_ok(request):
        return templates.TemplateResponse(request, "phone.html", {"paired": False, "version": __version__})
    today = diary.day(store.get("diary", []))
    return templates.TemplateResponse(request, "phone.html", {"paired": True, "today": today, "said": said,
                                                               "error": error, "portions": list(diary.PORTIONS),
                                                               "version": __version__})


@app.post("/m")
def phone_add(request: Request, text: str = Form(""), portion: str = Form("normal")):
    if not _phone_ok(request):
        return RedirectResponse("/m", status_code=303)
    try:
        entry = diary.say(text, portion if portion in diary.PORTIONS else "normal")
    except ValueError as error:
        return RedirectResponse(f"/m?error={quote(str(error))}", status_code=303)
    store.put("diary", store.get("diary", []) + [entry])
    return RedirectResponse(f"/m?said={quote(diary.spoken(entry, diary.day(store.get('diary', []))))}", status_code=303)


@app.post("/diary")
def diary_add(text: str = Form(...), portion: str = Form("normal")):
    try:
        entry = diary.say(text, portion)
    except ValueError as error:
        return RedirectResponse(f"/diary?error={quote(str(error))}", status_code=303)
    store.put("diary", store.get("diary", []) + [entry])
    return RedirectResponse("/diary", status_code=303)


@app.post("/diary/remove")
def diary_remove(at: str = Form(...), dish: str = Form(...)):
    entries = store.get("diary", [])
    gone = next((i for i, e in enumerate(entries) if e["at"] == at and e["dish"] == dish), None)
    if gone is not None:
        del entries[gone]
        store.put("diary", entries)
    return RedirectResponse("/diary", status_code=303)


def _phone_token_ok(request: Request) -> bool:
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return bool(config.API_TOKEN) and secrets.compare_digest(given, config.API_TOKEN)


@app.get("/api/meal")
@app.get("/api/health")
def phone_door_wrong_method():
    """A shortcut left on GET (the default of "Get Contents of URL"): say what to fix, in words the phone reads aloud."""
    return JSONResponse({"spoken": "Almost there: in the shortcut, open Get Contents of URL, set Method to POST, "
                                   "then add the Authorization header and the JSON body."}, status_code=405)


@app.post("/api/health")
async def api_health(request: Request):
    """For an iPhone shortcut reading Apple Health: {"steps": "...", "weight_kg": "...", "sleep_hours": "...",
    "resting_hr": "...", "systolic": "...", "diastolic": "..."} as Shortcuts writes them, with the same token as
    /api/meal. Kept only with the consent given on the measures page."""
    if not _phone_token_ok(request):
        return JSONResponse({"spoken": "This shortcut is not allowed to write to Carpe Vigor."}, status_code=403)
    if not (store.get("health") or {}).get("consent"):
        return JSONResponse({"spoken": "Give your consent on the Measures page first: nothing was kept."}, status_code=403)
    raw = await request.body()
    if len(raw) > 20000:
        return JSONResponse({"spoken": "Too much at once."}, status_code=413)
    try:
        body = json.loads(raw)
    except ValueError:
        return JSONResponse({"spoken": "The shortcut must send a JSON body."}, status_code=422)
    if not isinstance(body, dict):
        return JSONResponse({"spoken": "The shortcut must send a JSON dictionary."}, status_code=422)
    result = apple_health.apply(body, store)
    store.log("apple_health", {"fields": sorted(result["kept"])})  # the values stay in the store, not in the log
    return {"spoken": apple_health.spoken(result), **result}


@app.post("/api/meal")
async def api_meal(request: Request):
    """For a phone or watch shortcut: {"text": "cacio e pepe", "portion": "normal"} with the header
    'Authorization: Bearer <CARPE_API_TOKEN>'. Answers {"spoken": "...", "entry": {...}}. Without a token set in .env
    the door stays shut: on a deployed app anyone could otherwise write into the diary."""
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not config.API_TOKEN or not secrets.compare_digest(given, config.API_TOKEN):
        return JSONResponse({"spoken": "This shortcut is not allowed to write to the diary."}, status_code=403)
    raw = await request.body()
    if len(raw) > 4000:  # a sentence and a portion, not a document
        return JSONResponse({"spoken": "That is too long for one meal."}, status_code=413)
    try:
        body = json.loads(raw)
    except ValueError:
        body = {"text": raw.decode("utf-8", "replace")}
    if not isinstance(body, dict):
        body = {"text": str(body)}
    try:
        entry = diary.say(str(body.get("text", "")), body.get("portion") if body.get("portion") in diary.PORTIONS else "normal")
    except ValueError as error:
        return JSONResponse({"spoken": str(error)}, status_code=422)
    store.put("diary", store.get("diary", []) + [entry])
    return {"spoken": diary.spoken(entry, diary.day(store.get("diary", []))), "entry": entry}


# 3 ------------------------------------------------------------------------------------------------------------------
@app.get("/home", response_class=HTMLResponse)
def home(request: Request):
    pantry = Pantry.from_rows(store.get("pantry", []))
    prof = store.get("profile") or {}
    flagged = pantry.review(catalog, (prof.get("guidance") or {}).get("constraints", []))
    store.put("pantry", pantry.to_rows())
    items = sorted(catalog.items.values(), key=lambda i: (i.tags[0] if i.tags else "", i.name))
    return render(request, "home.html", items=items, pantry=pantry, flagged=flagged, catalog=catalog)


@app.post("/home")
def home_submit(request: Request, have: list[str] = Form([])):
    pantry = Pantry()
    for sku in have:
        if sku in catalog.items:
            pantry.tick(sku, catalog.items[sku].name)
    prof = store.get("profile") or {}
    pantry.review(catalog, (prof.get("guidance") or {}).get("constraints", []))
    store.put("pantry", pantry.to_rows())
    store.log("pantry", {"at_home": len(pantry.at_home()), "dont_rebuy": len(pantry.blacklist())})
    return RedirectResponse("/cart", status_code=303)


# 4 ------------------------------------------------------------------------------------------------------------------
@app.get("/cart", response_class=HTMLResponse)
def cart_view(request: Request, error: str = ""):
    prof = store.get("profile")
    plan = store.get("plan")
    if not prof or not plan:
        return RedirectResponse("/doctor")
    pantry = Pantry.from_rows(store.get("pantry", []))
    money = week.status(store)
    budget = money["remaining"] if money["authorized"] else float(prof["budget"])
    cart = cart_agent.build(plan["plan"]["recipes"], pantry, catalog, budget,
                            avoid=catalog.off_plan((prof.get("guidance") or {}).get("constraints", [])))
    cart_agent.add_extras(cart, store.get("extras", []), catalog)
    store.put("cart", {"lines": [{"sku": l.item.sku, "quantity": l.quantity, "reason": l.reason, "swapped_from": l.swapped_from,
                                  "extra": l.extra, "amount": l.total} for l in cart.lines],
                       "subtotal": cart.subtotal, "delivery_fee": cart.delivery_fee, "total": cart.total, "skipped": cart.skipped,
                       "needed": cart.needed, "over_budget": cart.over_budget})
    healthy, unhealthy = cart_agent.basket([(l.item.sku, l.total) for l in cart.lines], catalog, pantry.blacklist())
    kinds = {l.item.sku: ("unhealthy" if l.item.sku in pantry.blacklist() else catalog.kind(l.item.sku)) for l in cart.lines}
    return render(request, "cart.html", cart=cart, store_name=catalog.store["name"], store_note=catalog.store.get("note", ""),
                  budget=budget, error=error, orders=store.events("captured"), kinds=kinds,
                  basket=reward.basket_quality(healthy, unhealthy, cart.subtotal), healthy=healthy, unhealthy=unhealthy,
                  extras_menu=sorted(catalog.items.values(), key=lambda i: i.name), max_rate=config.CASHBACK_MAX)


@app.post("/cart/extra")
def cart_extra(sku: str = Form(...), remove: str = Form("")):
    """The person adds (or takes back) something of their own choice: the agent never would, the reward counts it."""
    extras = store.get("extras", [])
    if remove:
        if sku in extras:
            extras.remove(sku)
    elif sku in catalog.items:
        extras.append(sku)
    store.put("extras", extras)
    return RedirectResponse("/cart", status_code=303)


@app.post("/budget/authorize")
def budget_authorize(request: Request, amount: float = Form(...)):
    base = str(request.base_url).rstrip("/")
    order = week.start_authorization(store, amount, f"{base}/budget/approved", f"{base}/cart?error=cancelled")
    return RedirectResponse(order["approve_url"], status_code=303)


@app.get("/budget/approved")
def budget_approved(token: str):
    try:
        week.complete_authorization(store, token)
    except PayPalError as e:
        return RedirectResponse(f"/cart?error={e}", status_code=303)
    return RedirectResponse("/cart", status_code=303)


@app.post("/cart/order")
def cart_order():
    cart = store.get("cart")
    if not cart or not cart["lines"]:
        return RedirectResponse("/cart?error=Nothing+to+order", status_code=303)
    try:
        week.capture_order(store, cart["total"], f"Carpe Vigor order: {len(cart['lines'])} items from {catalog.store['name']}")
    except PayPalError as e:
        return RedirectResponse(f"/cart?error={e}", status_code=303)
    pantry = Pantry.from_rows(store.get("pantry", []))
    blacklisted_bought = [l["sku"] for l in cart["lines"] if l["sku"] in pantry.blacklist()]
    healthy, unhealthy = cart_agent.basket([(l["sku"], l["amount"]) for l in cart["lines"]], catalog, pantry.blacklist())
    for line in cart["lines"]:
        pantry.tick(line["sku"], catalog.items[line["sku"]].name)
    store.put("pantry", pantry.to_rows())
    store.put("extras", [])
    store.log("order", {"items": len(cart["lines"]), "total": cart["total"], "blacklisted_bought": blacklisted_bought,
                        "healthy": healthy, "unhealthy": unhealthy})
    return RedirectResponse("/reward", status_code=303)


@app.post("/budget/release")
def budget_release():
    try:
        week.release_remainder(store)
        week.close_week(store, reward.score(behaviour()))  # the week's reward goes into the month, paid at its end
    except PayPalError as e:
        return RedirectResponse(f"/cart?error={e}", status_code=303)
    return RedirectResponse("/reward", status_code=303)


# 5 ------------------------------------------------------------------------------------------------------------------
def this_week(kind: str) -> list[dict]:
    """Events of one kind since the week's budget was authorized (the log keeps every week)."""
    out = []
    for e in store.events():
        if e["kind"] == "authorized":
            break
        if e["kind"] == kind:
            out.append(e)
    return out


def behaviour() -> reward.WeekBehaviour:
    plan = store.get("plan") or {"plan": {"recipes": []}, "cooked": []}
    steps = store.get("steps", [])  # 7 daily step counts, from a watch or simulated
    money = week.status(store)
    orders = this_week("order")
    return reward.WeekBehaviour(
        planned_meals=len(plan["plan"]["recipes"]), cooked_meals=len(plan.get("cooked", [])),
        days_with_steps=sum(1 for s in steps if s >= config.STEPS_GOAL), spent=money["spent"],
        healthy_spend=round(sum(o.get("healthy", 0.0) for o in orders), 2),
        unhealthy_spend=round(sum(o.get("unhealthy", 0.0) for o in orders), 2))


@app.get("/reward", response_class=HTMLResponse)
def reward_view(request: Request, error: str = ""):
    b = behaviour()
    return render(request, "reward.html", behaviour=b, result=reward.score(b), steps=store.get("steps", []),
                  steps_goal=config.STEPS_GOAL, max_rate=config.CASHBACK_MAX, days=planner.DAYS,
                  month=week.month(store), week_closed=bool(this_week("week_closed")), error=error)


@app.post("/reward/steps")
def steps_submit(steps: str = Form(...), back: str = Form("/reward")):
    """Seven numbers, comma separated: what a watch would send. Simulated in the demo."""
    values = [int(x) for x in steps.replace(";", ",").split(",") if x.strip().isdigit()][:7]
    store.put("steps", values)
    return RedirectResponse(back if back in ("/reward", "/move") else "/reward", status_code=303)


@app.post("/month/settle")
def month_settle():
    """The last day of the month (a button in the demo): the month's reward is refunded through PayPal."""
    try:
        week.settle_month(store)
    except PayPalError as e:
        return RedirectResponse(f"/reward?error={e}", status_code=303)
    return RedirectResponse("/reward", status_code=303)


# -------------------------------------------------------------------------------------------------------------------
@app.post("/reset")
def reset():
    store.reset()
    return RedirectResponse("/doctor", status_code=303)


@app.get("/ledger", response_class=HTMLResponse)
def ledger_view(request: Request):
    return render(request, "ledger.html", rows=week.ledger(store))


@app.get("/api/ledger")
def api_ledger():
    return week.ledger(store)


@app.get("/api/state")
def api_state():
    return {"money": week.status(store), "profile": store.get("profile"), "plan": store.get("plan"),
            "pantry": store.get("pantry"), "cart": store.get("cart"), "steps": store.get("steps"),
            "diary": store.get("diary", []), "log": store.events()}
