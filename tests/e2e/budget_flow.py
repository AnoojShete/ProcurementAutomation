"""Budget control before approval (feature expansion Phase 1), end to end
through the gateway against the running stack.

    python tests/e2e/budget_flow.py

Uses its own department ("E2E Budget <run>") so demo budgets are untouched;
the budgets and requests it creates stay behind, like every e2e suite's data
(./scripts/reset-demo.sh clears them). Rules it changes are put back.
"""
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

GW = os.getenv("GATEWAY", "http://localhost:8080") + "/api"
PASSWORD = "DemoPass123!"
RUN = uuid.uuid4().hex[:6].upper()
DEPT = f"E2E Budget {RUN}"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    return bool(cond)


def step(title):
    print(f"\n── {title}")


def login(role):
    for _ in range(5):
        r = requests.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD})
        if r.status_code != 429:
            break
        time.sleep(15)
    check(f"login {role}", r.status_code == 200, r.text[:120])
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def new_request(h, amount, dept=DEPT, request_type="hardware"):
    return requests.post(f"{GW}/requests/", headers=h, json={
        "request_type": request_type, "requested_by": "ignored", "department": dept, "amount": amount,
        "currency": "INR", "items": [{"name": "Laptop", "quantity": 1, "unit_price": amount}]})


def set_rule(admin, key, value):
    r = requests.patch(f"{GW}/admin/business-rules/{key}", headers=admin,
                       json={"new_value": value, "justification": "budget e2e"})
    check(f"rule {key} = {value!r}", r.status_code == 200, r.text[:150])


def wait_for_status(make, status, timeout=40):
    """Services pick a rule change up from business_rule.updated within
    seconds. (Compares status codes: a 4xx Response object is falsy.)"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = make()
        if r.status_code == status:
            return r
        time.sleep(2)
    return None


def main():
    requester, approver, finance, admin = (login(r) for r in ("requester", "approver", "finance", "admin"))

    step("Access")
    check("requester can't list budgets", requests.get(f"{GW}/budgets/", headers=requester).status_code == 403)
    check("approver can list budgets", requests.get(f"{GW}/budgets/", headers=approver).status_code == 200)
    check("approver can't create budgets", requests.post(f"{GW}/budgets/", headers=approver,
          json={"department": DEPT, "category": "hardware", "amount_inr": 1}).status_code == 403)
    period = requests.get(f"{GW}/budgets/period", headers=finance).json()["data"]
    check("current period known", period["fiscal_year"] and period["period"], str(period))

    step(f"Budget {DEPT} hardware ₹10,000 for {period['period']} {period['fiscal_year']}")
    r = requests.post(f"{GW}/budgets/", headers=finance, json={"department": DEPT, "category": "hardware", "amount_inr": 10000})
    check("finance creates it -> 201", r.status_code == 201, r.text[:150])
    budget_id = r.json()["data"]["id"]
    dup = requests.post(f"{GW}/budgets/", headers=finance, json={"department": DEPT.lower(), "category": "hardware", "amount_inr": 1})
    check("same scope again (any case) -> 409", dup.status_code == 409, dup.text[:120])

    step("Requests drawing on it")
    r1 = new_request(requester, 3000).json()["data"]
    check("₹3,000 -> within", r1["budget_status"] == "within", str(r1.get("budget_status")))
    check("chain unchanged (manager only)", r1["approval_chain"] == ["dept_manager"], str(r1["approval_chain"]))
    r2 = new_request(requester, 5000).json()["data"]
    check("₹5,000 more (80 %) -> warning", r2["budget_status"] == "warning", str(r2.get("budget_status")))
    check("warning crossed is recorded", r2["budget_check"]["warning_crossed"] is True)
    r3 = new_request(requester, 4000).json()["data"]
    check("₹4,000 more -> over", r3["budget_status"] == "over", str(r3.get("budget_status")))
    check("over budget adds a finance step", r3["approval_chain"] == ["dept_manager", "finance_head"], str(r3["approval_chain"]))
    check("reason recorded", r3["budget_check"]["routing"] == ["over_budget"], str(r3["budget_check"].get("routing")))
    small = new_request(requester, 300).json()["data"]
    check("₹300 (auto tier) on an exhausted budget is not auto-approved",
          small["status"] == "pending_approval" and small["approval_chain"] == ["finance_head"],
          f"{small['status']} {small['approval_chain']}")

    line = requests.get(f"{GW}/requests/{r3['id']}/budget", headers=requester).json()["data"]
    check("requester sees own request's budget line", line["budget"] and line["status_at_creation"] == "over")
    b = requests.get(f"{GW}/budgets/{budget_id}", headers=finance).json()["data"]
    check("budget counts all four as pending", abs(b["pending"] - 12300) < 0.01 and len(b["requests"]) == 4,
          f"pending={b['pending']}")

    step("Rejecting releases the money")
    r = requests.post(f"{GW}/requests/{r3['id']}/reject", headers=approver, json={"comments": "budget e2e"})
    check("approver rejects the over-budget request", r.status_code == 200, r.text[:150])
    time.sleep(3)
    b = requests.get(f"{GW}/budgets/{budget_id}", headers=finance).json()["data"]
    check("₹4,000 no longer counted", abs(b["pending"] - 8300) < 0.01, f"pending={b['pending']}")
    check("delete refused while requests draw on it",
          requests.delete(f"{GW}/budgets/{budget_id}", headers=finance).status_code == 409)

    step("Two requests at once can't both fit")
    r = requests.post(f"{GW}/budgets/", headers=finance, json={"department": DEPT, "category": "saas", "amount_inr": 10000})
    check("SaaS budget ₹10,000", r.status_code == 201)
    with ThreadPoolExecutor(2) as pool:
        both = list(pool.map(lambda _: new_request(requester, 6000, request_type="saas").json()["data"], range(2)))
    statuses = sorted(x["budget_status"] for x in both)
    check("one fits, the other is over", statuses[0] == "over" and statuses[1] in ("within", "warning"), str(statuses))

    step("Rules")
    set_rule(admin, "budget.no_budget_policy", "block")
    blocked = wait_for_status(lambda: new_request(requester, 1000, dept=f"{DEPT} none"), 422)
    check("no budget + policy block -> 422 no_budget", blocked is not None and blocked.json()["error"]["code"] == "no_budget",
          blocked.text[:150] if blocked is not None else "never applied")
    set_rule(admin, "budget.no_budget_policy", "allow")
    allowed = wait_for_status(lambda: new_request(requester, 1000, dept=f"{DEPT} none"), 200)
    check("policy back to allow -> created as no_budget",
          allowed is not None and allowed.json()["data"]["budget_status"] == "no_budget")

    step("Budget list")
    rows = requests.get(f"{GW}/budgets/", headers=finance,
                        params={"fiscal_year": period["fiscal_year"], "period": period["period"]}).json()["data"]
    mine = [x for x in rows if x["department"] == DEPT]
    check("both budgets listed with usage", len(mine) == 2 and all("left" in x for x in mine))

    passed = sum(ok for _, ok in results)
    print(f"\nbudget flow: {passed} passed, {len(results) - passed} failed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
