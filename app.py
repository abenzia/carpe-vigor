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

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from carpevigor import __version__, cart_agent, config, planner, profile, reward, sources, week
from carpevigor.catalog import Catalog
from carpevigor.pantry import Pantry
from carpevigor.paypal import PayPalError
from carpevigor.store import Store

app = FastAPI(title="Carpe Vigor", version=__version__)
app.mount("/static", StaticFiles(directory=str(config.ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(config.ROOT / "templates"))
store = Store()
catalog = Catalog.load()


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    base = {"request": request, "money": week.status(store), "currency": config.CURRENCY,
            "profile": store.get("profile"), "plan": store.get("plan"), "version": __version__}
    return templates.TemplateResponse(request, name, {**base, **ctx})


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return RedirectResponse("/doctor" if not store.get("profile") else "/week")


# 1 ------------------------------------------------------------------------------------------------------------------
@app.get("/doctor", response_class=HTMLResponse)
def doctor(request: Request):
    return render(request, "doctor.html", devices=profile.DEVICES, sources=sources.status())


@app.post("/doctor")
def doctor_submit(request: Request, doctor_said: str = Form(...), device: str = Form(...), constraints: str = Form(""),
                  budget: float = Form(120.0), report_attached: str = Form("")):
    guidance = profile.read(doctor_said, device, constraints, bool(report_attached))
    store.put("profile", {"doctor_said": doctor_said, "device": device, "constraints_text": constraints,
                          "budget": budget, "guidance": guidance.model_dump()})
    store.delete("plan")
    store.log("profile", {"topics": guidance.topics})
    return RedirectResponse("/week?build=1", status_code=303)


# 2 ------------------------------------------------------------------------------------------------------------------
@app.get("/week", response_class=HTMLResponse)
def week_view(request: Request, build: int = 0):
    prof = store.get("profile")
    if not prof:
        return RedirectResponse("/doctor")
    plan = store.get("plan")
    if build or not plan:
        guidance = profile.Guidance.model_validate(prof["guidance"])
        made, report, used = planner.make(guidance, prof["device"])
        plan = {"plan": made.model_dump(), "report": report, "sources": used, "cooked": []}
        store.put("plan", plan)
        store.log("plan", {"approved": report.get("approved"), "provider": report.get("provider")})
    return render(request, "week.html", week_plan=plan["plan"], report=plan["report"], used=plan["sources"],
                  cooked=set(plan.get("cooked", [])), days=planner.DAYS)


@app.post("/week/cooked")
def cooked(title: str = Form(...)):
    plan = store.get("plan")
    if plan:
        done = set(plan.get("cooked", []))
        done.symmetric_difference_update({title})
        plan["cooked"] = sorted(done)
        store.put("plan", plan)
    return RedirectResponse("/week", status_code=303)


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
    store.put("cart", {"lines": [{"sku": l.item.sku, "quantity": l.quantity, "reason": l.reason, "swapped_from": l.swapped_from} for l in cart.lines],
                       "subtotal": cart.subtotal, "delivery_fee": cart.delivery_fee, "total": cart.total, "skipped": cart.skipped,
                       "needed": cart.needed, "over_budget": cart.over_budget})
    return render(request, "cart.html", cart=cart, store_name=catalog.store["name"], store_note=catalog.store.get("note", ""),
                  budget=budget, error=error, orders=store.events("captured"))


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
    for line in cart["lines"]:
        pantry.tick(line["sku"], catalog.items[line["sku"]].name)
    store.put("pantry", pantry.to_rows())
    store.log("order", {"items": len(cart["lines"]), "total": cart["total"], "blacklisted_bought": blacklisted_bought})
    return RedirectResponse("/reward", status_code=303)


@app.post("/budget/release")
def budget_release():
    try:
        week.release_remainder(store)
    except PayPalError as e:
        return RedirectResponse(f"/cart?error={e}", status_code=303)
    return RedirectResponse("/reward", status_code=303)


# 5 ------------------------------------------------------------------------------------------------------------------
def behaviour() -> reward.WeekBehaviour:
    plan = store.get("plan") or {"plan": {"recipes": []}, "cooked": []}
    steps = store.get("steps", [])  # 7 daily step counts, from a watch or simulated
    money = week.status(store)
    orders = store.events("order")
    return reward.WeekBehaviour(
        planned_meals=len(plan["plan"]["recipes"]), cooked_meals=len(plan.get("cooked", [])),
        days_with_steps=sum(1 for s in steps if s >= config.STEPS_GOAL),
        blacklist_respected=not any(o.get("blacklisted_bought") for o in orders),
        spent=money["spent"])


@app.get("/reward", response_class=HTMLResponse)
def reward_view(request: Request):
    b = behaviour()
    return render(request, "reward.html", behaviour=b, result=reward.score(b), steps=store.get("steps", []),
                  steps_goal=config.STEPS_GOAL, max_rate=config.CASHBACK_MAX, days=planner.DAYS, paid=store.get("refunds", []))


@app.post("/reward/steps")
def steps_submit(steps: str = Form(...)):
    """Seven numbers, comma separated: what a watch would send. Simulated in the demo."""
    values = [int(x) for x in steps.replace(";", ",").split(",") if x.strip().isdigit()][:7]
    store.put("steps", values)
    return RedirectResponse("/reward", status_code=303)


@app.post("/reward/pay")
def reward_pay():
    result = reward.score(behaviour())
    if result.cashback > 0 and not store.get("refunds"):
        try:
            week.pay_reward(store, result)
        except PayPalError as e:
            return RedirectResponse(f"/cart?error={e}", status_code=303)
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
            "pantry": store.get("pantry"), "cart": store.get("cart"), "steps": store.get("steps"), "log": store.events()}
