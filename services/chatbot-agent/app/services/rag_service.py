"""Retrieval for the procurement assistant (RAG).

retrieve() embeds the question, searches document_embeddings by cosine
distance (pgvector, HNSW index) and returns the closest chunks the user is
allowed to see:

  staff (approver, finance, admin)  everything
  everyone else                     business rules and vendors, plus their
                                    own purchase requests, the contracts of
                                    those requests and documents they uploaded
                                    (never licences, budgets or totals)

Generated contracts share most of their wording, so the top hits are often
the same clause from many contracts; at most MAX_PER_SECTION chunks per
(source type, section) are kept, so the context covers several clauses
and sources instead of one clause repeated.
"""
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import indexer
from shared.auth.middleware import CurrentUser

STAFF = ("approver", "finance", "admin", "service")
TOP_K = 25
CANDIDATES = 100
MAX_PER_SECTION = 3
MAX_DISTANCE = 0.6          # cosine distance; farther chunks aren't relevant enough to show the model
MAX_PER_TYPE = {"request": 8, "contract": 10, "document": 10}   # leave room for other kinds of source
TEMPLATE_WORDS = {"professional services": "Professional services", "consult": "Professional services",
                  "saas": "SaaS subscription", "subscription": "SaaS subscription",
                  "hardware": "Hardware purchase", "laptop": "Hardware purchase"}


@dataclass
class Hit:
    ref: str                # CT-1a2b3c4d / DOC-… / rule key: what the answer cites
    source_type: str
    source_id: str
    title: str
    section: Optional[str]
    text: str
    distance: float


def _ref(source_type: str, source_id: str) -> str:
    if source_type == "contract":
        return f"CT-{source_id[:8]}"
    if source_type == "document":
        return f"DOC-{source_id[:8]}"
    if source_type == "request":
        return f"PR-{source_id[:8]}"
    if source_type in ("vendor", "licence", "budget", "summary"):
        return f"{source_type}:{source_id[:8]}"
    return source_id


async def retrieve(db: AsyncSession, user: CurrentUser, query: str, k: int = TOP_K) -> list[Hit]:
    if not query.strip():
        return []
    [vector] = await indexer.embed([query], kind="search_query")
    rows = (await db.execute(text(
        "SELECT e.source_type, CAST(e.document_id AS TEXT) AS document_id, e.title, e.section, e.chunk_text, "
        "e.embedding <=> CAST(:q AS vector) AS distance "
        "FROM document_embeddings e "
        "LEFT JOIN documents d ON e.document_id = CAST(d.id AS TEXT) "
        "WHERE e.source_type IS NOT NULL "
        "AND (e.audience = 'all' OR :staff OR (e.audience = 'owner' AND e.owner_email = :email)) "
        "ORDER BY e.embedding <=> CAST(:q AS vector) LIMIT :n"),
        {"q": str(vector), "staff": user.role in STAFF, "email": (user.email or "").lower(), "n": CANDIDATES})).all()
    hits, per_section, per_type = [], {}, {}
    for r in rerank(query, [r for r in rows if r.distance <= MAX_DISTANCE]):
        key = (r.source_type, r.section or r.document_id)
        if per_section.get(key, 0) >= MAX_PER_SECTION or per_type.get(r.source_type, 0) >= MAX_PER_TYPE.get(r.source_type, k):
            continue
        per_section[key] = per_section.get(key, 0) + 1
        per_type[r.source_type] = per_type.get(r.source_type, 0) + 1
        hits.append(Hit(_ref(r.source_type, r.document_id), r.source_type, r.document_id, r.title, r.section,
                        r.chunk_text, round(float(r.distance), 3)))
        if len(hits) >= k:
            break
    return hits


def rerank(query: str, rows: list) -> list:
    """Vector order, adjusted by what the question names: a contract type
    named in the question keeps only contracts of that type, and chunks
    whose title names a vendor (or word) from the question move up."""
    q = query.lower()
    wanted = {label for word, label in TEMPLATE_WORDS.items() if word in q}
    words = {w for w in re.findall(r"[a-z0-9]{4,}", q)}

    def keep(r):
        return not (wanted and r.source_type == "contract" and not any(w in (r.title or "") for w in wanted))

    def score(r):
        title = (r.title or "").lower()
        bonus = 0.08 * sum(1 for w in words if w in title)
        return float(r.distance) - min(bonus, 0.16)
    return sorted((r for r in rows if keep(r)), key=score)


def as_context(hits: list[Hit]) -> str:
    if not hits:
        return "No matching passages were found in the contracts, documents or business rules this user can see."
    return "\n\n".join(f"[{h.ref}] {h.text}" for h in hits)


async def search_knowledge_base(query: str, db: AsyncSession, user: CurrentUser, limit: int = 25) -> str:
    """The search_documents tool: another retrieval with the model's own query."""
    try:
        return as_context(await retrieve(db, user, query, k=limit))
    except Exception as e:
        return f"Error searching the knowledge base: {e}"
