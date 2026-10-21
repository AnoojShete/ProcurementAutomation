"""The procurement assistant's answer: retrieval-augmented generation.

For every question:
  1. retrieve  rag_service.retrieve() finds the passages closest to the
               question in the index (contract clauses, invoice/quote text,
               business rules, and current records: requests, vendors,
               licences, budgets, totals), limited to what this user may see
  2. generate  the local model (Ollama) answers from those passages only,
               citing them, and says so when they don't contain the answer

There are no function tools: the earlier version let the model choose API
calls, which a small local model often got wrong (wrong arguments, tool
calls printed as text). The records it used to fetch are now in the index,
refreshed every minute (indexer.py), and access control is applied when
retrieving, not left to the model.
"""
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import intent, rag_service, topics
from shared.auth.middleware import CurrentUser

HISTORY_TURNS = 6            # earlier turns kept for follow-up questions

SYSTEM_PROMPT = (
    "You are the procurement assistant of an IT procurement platform. The user is {email} (role: {role}).\n"
    "You answer questions about contracts and their clauses, uploaded invoices/quotes/POs, purchase requests and "
    "their status, vendors and their risk, licences, budgets and the platform's business rules.\n"
    "Rules:\n"
    "1. Use only the numbered PASSAGES given with the question. They come from the platform's records and are "
    "current to the minute. Never use outside knowledge about contracts, vendors, prices or policies.\n"
    "2. Read the passage that answers the question carefully and quote its key sentence in quotation marks, "
    "then answer in one or two sentences. Copy numbers exactly as written.\n"
    "3. Cite the passage reference in square brackets, e.g. [CT-1a2b3c4d] or [approval.spend_tiers].\n"
    "4. Each passage is about the contract, vendor or record named at its start. Only if the question names a "
    "specific vendor, contract or item by its proper name and no passage mentions it, say there is no record of it; "
    "ordinary words in the question are not names.\n"
    "5. If the passages don't contain the answer, say you couldn't find it in the platform's records. Never guess.\n"
    "5a. A passage about a business rule: explain in plain words what the rule does and what its current setting "
    "means for the user's question. Don't answer with just the setting or the rule's key.\n"
    "6. Never reveal bank account numbers or IFSC codes.\n"
    "7. For questions unrelated to procurement on this platform (or greetings), reply briefly in plain text: say "
    "what you can help with. Don't output JSON."
)


def search_query(history: list) -> str:
    """What to retrieve for: the latest question, plus the one before it when
    the latest is a short follow-up ("and for hardware?") to an actual
    question; a greeting or a remark before it is not carried over."""
    asked = [m.content for m in history if m.role == "user"]
    if not asked:
        return ""
    if len(asked) > 1 and len(asked[-1].split()) <= 8 and intent.classify(asked[-2]).kind == "question":
        return f"{asked[-2]} {asked[-1]}"
    return asked[-1]


def build_messages(history: list, user: CurrentUser, hits: list) -> list[dict]:
    turns = [{"role": m.role, "content": m.content} for m in history if m.role in ("user", "assistant")]
    turns = turns[-(HISTORY_TURNS * 2 + 1):]
    question = turns.pop() if turns and turns[-1]["role"] == "user" else {"role": "user", "content": ""}
    passages = rag_service.as_context(hits)
    return ([{"role": "system", "content": SYSTEM_PROMPT.format(email=user.email, role=user.role)}]
            + turns
            + [{"role": "user", "content": f"PASSAGES:\n{passages}\n\nQUESTION: {question['content']}"}])


async def _first_name(db: AsyncSession, user: CurrentUser) -> Optional[str]:
    try:
        name = (await db.execute(text("SELECT display_name FROM auth_users WHERE lower(email) = :e"),
                                 {"e": (user.email or "").lower()})).scalar()
    except Exception:
        return None
    return name.split()[0] if name else None


async def _vendor_names(db: AsyncSession) -> list[str]:
    try:
        return [r[0] for r in (await db.execute(text("SELECT name FROM vendors ORDER BY created_at"))).all()]
    except Exception:
        return []


async def query_llm_with_tools(history: list, user: CurrentUser, db: AsyncSession) -> str:
    """Kept under its old name so the chat endpoint's call doesn't change.
    Intent first (intent.py): conversational messages get a direct reply,
    licence anomalies come from live data (topics.py), an ambiguous vendor
    name gets a clarifying question; only real questions are retrieved for."""
    asked = [m.content for m in history if m.role == "user"]
    if asked:
        kind = intent.classify(asked[-1], asked[-2] if len(asked) > 1 else None)
        if kind.kind in ("greeting", "capabilities", "examples", "topic_only", "smalltalk"):
            names = await _vendor_names(db)
            said = [m.content for m in history if m.role == "assistant"]
            return intent.reply(kind, asked[-1], role=user.role, first_name=await _first_name(db, user),
                                vendor=names[0] if names else None, shown=said[-1] if said else "")
        if kind.kind == "licence_anomalies":
            return await topics.answer_licence_anomalies(db, user)
        question = intent.clarify_vendor(asked[-1], await _vendor_names(db))
        if question:
            return question
    try:
        hits = await rag_service.retrieve(db, user, search_query(history))
    except Exception:                    # index or embedding model unavailable: answer without passages
        hits = []
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(f"{settings.llm_api_base_url}/api/chat", json={
            "model": settings.llm_model_name, "messages": build_messages(history, user, hits), "stream": False,
            "options": {"temperature": 0}})
        r.raise_for_status()
        return r.json().get("message", {}).get("content") or "I could not generate a response."
