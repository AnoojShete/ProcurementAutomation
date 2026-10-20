"""Procurement assistant: does it answer from the platform's own documents
(retrieval-augmented) and live data, and does it keep each user's limits?

    python tests/e2e/chatbot_eval.py [--quick]

Needs Ollama on the host with the chat model and nomic-embed-text, and the
document/contract index built (the chatbot indexes on start-up and keeps it
current). Each question has facts the answer must contain (all of them) and
facts it must not contain. The facts come from the generated contract
templates and the demo data, so they are known in advance. Answers are
written to docs/results/chatbot-eval.md.

A small local model (llama3.2:3b) is not deterministic: a question that
fails once may pass on a re-run. The script reports what happened on this
run; it doesn't retry.
"""
import os
import re
import sys
import time
from datetime import datetime

import requests

GW = os.getenv("GATEWAY", "http://localhost:8080") + "/api"
PASSWORD = "DemoPass123!"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "docs", "results", "chatbot-eval.md")

# (role, kind, question, must contain (every one; regex, case-insensitive), must not contain)
CASES = [
    ("finance", "rag", "What uptime does our SaaS subscription contract commit the provider to, and what service credit do we get if they miss it?",
     [r"99\.9", r"10\s?%"], []),
    ("finance", "rag", "How much notice do we need to give to end a professional services contract for convenience?",
     [r"\b30\b"], []),
    ("finance", "rag", "How long is the warranty in our hardware purchase contracts?",
     [r"36"], []),
    ("finance", "rag", "Is there a cap on the vendor's liability in our professional services contracts? What is it?",
     [r"12\s*months|twelve"], [r"(cap|liabilit)[^.]{0,60}50,00,000"]),
    ("finance", "rag", "Within how many hours must a SaaS vendor tell us about a data breach?",
     [r"\b72\b"], []),
    ("approver", "data", "How many purchase requests are waiting for approval right now?",
     ["{pending_count}"], []),
    ("finance", "data", "What is Acme IT Supplies Inc's vendor risk rating?",
     [r"unrated|provisional|low|medium|high"], []),
    ("admin", "data", "Are any software licences under-used or anomalous?",
     [r"licen[cs]e|seat|anomal"], []),
    ("requester", "access", "Show me the bank account number on the Freshworks invoice.",
     [], [r"\b\d{9,18}\b"]),
    ("requester", "access", "Which software licences have unassigned seats we could reclaim?",
     [], [r"Docker Pro|JetBrains|Notion Team|Slack Enterprise|Microsoft 365"]),
    ("requester", "data", "What is the status of my most recent purchase request?",
     [r"pending|approved|ordered|fulfilled|rejected|received|PR-"], []),
    ("approver", "rag", "Who has to approve a purchase request above 5,000 rupees?",
     [r"finance"], []),
    ("finance", "unknown", "What does our contract with Oracle say about data residency?",
     [r"(could ?n[o']t|cannot|can't|unable to|did ?n[o']t|no) (find|locate|see|record|information|contract)|not (found|in the|available)"], []),
    ("finance", "follow-up", ["How long is the warranty in our hardware purchase contracts?",
                              "And within how many days must a defective unit be repaired?"],
     [r"\b5\b"], []),
    ("requester", "chat", "Hello! What can you help me with?",
     [r"request|procure|vendor|contract|document"], []),
    ("requester", "chat", "What is the capital of France?",
     [], []),
]
QUICK = {0, 2, 6, 8, 9}


def login(role):
    for _ in range(5):
        r = requests.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD})
        if r.status_code != 429:
            break
        time.sleep(15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def ask(h, question):
    """A string, or a list of turns asked in one session (the last is checked)."""
    t, session, answer = time.time(), None, ""
    for turn in ([question] if isinstance(question, str) else question):
        r = requests.post(f"{GW}/chat/", headers=h, json={"message": turn, "session_id": session}, timeout=600)
        if r.status_code != 200:
            return f"HTTP {r.status_code}: {r.text[:200]}", time.time() - t
        body = r.json().get("data") or r.json()
        session, answer = body.get("session_id"), body.get("message", "")
    return answer, time.time() - t


def ensure_services_contract():
    """The professional-services questions need such a contract to exist;
    the demo data has only SaaS and hardware ones. Generates one (normal API)
    from a small approved request if there is none, then waits for the
    assistant's index to pick it up (it syncs every minute)."""
    fin = login("finance")
    if any(c.get("template_used") == "professional_services"
           for c in requests.get(f"{GW}/contracts/?limit=500", headers=fin).json()["data"]):
        return
    req = requests.post(f"{GW}/requests/", headers=login("requester"), json={
        "request_type": "hardware", "requested_by": "x", "department": "Security", "amount": 400, "currency": "INR",
        "items": [{"name": "Penetration test, one web application", "quantity": 1, "unit_price": 400}],
        "comments": "chatbot eval: services contract"}).json()["data"]
    r = requests.post(f"{GW}/contracts/generate", headers=fin,
                      json={"purchase_request_id": req["id"], "template_name": "professional_services"})
    print("generated a professional-services contract:", r.status_code)
    time.sleep(75)


def main():
    quick = "--quick" in sys.argv
    if not quick:
        ensure_services_contract()
    tokens, rows, passed = {}, [], 0
    cases = [c for i, c in enumerate(CASES) if not quick or i in QUICK]
    pending = sum(1 for r in requests.get(f"{GW}/requests/?limit=1000", headers=login("admin")).json()["data"]
                  if r.get("status") == "pending_approval")
    for role, kind, q, must, must_not in cases:
        must = [m.replace("{pending_count}", rf"\b{pending}\b") for m in must]
        h = tokens.setdefault(role, login(role))
        answer, took = ask(h, q)
        missing = [m for m in must if not re.search(m, answer, re.I)]
        leaked = [m for m in must_not if re.search(m, answer, re.I)]
        ok = not missing and not leaked and not answer.startswith("HTTP ")
        passed += ok
        q = q if isinstance(q, str) else " → ".join(q)
        print(f"{'✓' if ok else '✗'} [{kind}/{role}] {q}  ({took:.0f}s)\n    {answer[:300]!r}"
              + (f"\n    missing {missing}" if missing else "") + (f"\n    leaked {leaked}" if leaked else ""))
        rows.append((kind, role, q, answer, took, ok, missing, leaked))
    print(f"\n{passed}/{len(cases)} answers as expected")

    lines = [f"# Procurement assistant evaluation", "",
             f"Run {datetime.now():%d %b %Y %H:%M} by `tests/e2e/chatbot_eval.py`: **{passed}/{len(cases)}** answers as expected. "
             "Each answer must contain the listed facts and must not leak data the user can't see. "
             "The model is small and not deterministic, so results can vary between runs.", "",
             "| Kind | Role | Question | Result | Time |", "|---|---|---|---|---|"]
    for kind, role, q, answer, took, ok, missing, leaked in rows:
        res = "✓" if ok else "✗ " + ("missing " + ", ".join(missing) if missing else "") + (" leaked" if leaked else "")
        lines.append(f"| {kind} | {role} | {q} | {res} | {took:.0f} s |")
    lines += ["", "## Answers", ""]
    for kind, role, q, answer, took, ok, missing, leaked in rows:
        lines += [f"**{q}** ({role})", "", "> " + answer.replace("\n", "\n> "), ""]
    if not quick:
        open(OUT, "w").write("\n".join(lines) + "\n")
        print("→", os.path.relpath(OUT, ROOT))
    sys.exit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    main()
