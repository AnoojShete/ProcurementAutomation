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
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import rag_service
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
    "4. Each passage is about the contract, vendor or record named at its start. If the question names a vendor, "
    "contract or item that no passage mentions, say there is no record of it; don't answer from other passages.\n"
    "5. If the passages don't contain the answer, say you couldn't find it in the platform's records. Never guess.\n"
    "6. Never reveal bank account numbers or IFSC codes.\n"
    "7. For questions unrelated to procurement on this platform (or greetings), reply briefly in plain text: say "
    "what you can help with. Don't output JSON."
)


def search_query(history: list) -> str:
    """What to retrieve for: the latest question, plus the one before it when
    the latest is a short follow-up ("and for hardware?") that means little
    on its own."""
    asked = [m.content for m in history if m.role == "user"]
    if not asked:
        return ""
    if len(asked) > 1 and len(asked[-1].split()) <= 8:
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


async def query_llm_with_tools(history: list, user: CurrentUser, db: AsyncSession) -> str:
    """Kept under its old name so the chat endpoint's call doesn't change."""
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
