"""Builds and maintains the assistant's retrieval index (RAG).

What is indexed, read-only from the shared database:

  contract   every generated contract's text, one chunk per numbered clause
             ("6. LICENSE SCOPE …"), prefixed with the contract, template and
             vendor so a chunk makes sense on its own
  document   the text read from uploaded invoices, quotes and POs
             (documents.raw_text), in overlapping windows
  rule       each business rule: what it changes and its current value
  request    each purchase request: type, amount, status, approval step, vendor
  vendor     each vendor: status, risk band and rating, scorecard figures
  licence    each software licence: seats, usage, anomaly status
  budget     each budget with what is used and left
  summary    live totals (requests by status, risk bands) for staff

Each chunk records who may retrieve it (rag_service.retrieve applies it):
`all` (rules, vendors), `owner` (staff plus its owner: the requester of a
request or of a contract's purchase request, whoever uploaded a document)
or `staff` (approver, finance, admin only: licences, budgets, totals). Bank account numbers
and IFSC codes are masked before anything is embedded, so the assistant
can never quote them.

sync() compares a hash of each source (text + owner) with what is stored
and only re-embeds what changed; sources that disappeared are removed. It
runs on start-up and every SWEEP_SECONDS.
"""
import asyncio
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

import httpx
from sqlalchemy import text

from app.config import settings

logger = logging.getLogger(__name__)

EMBED_MODEL = "nomic-embed-text"     # 768 dimensions, matches document_embeddings.embedding
SWEEP_SECONDS = 60
WINDOW, OVERLAP = 900, 150
CLAUSE_PART = 160            # contract clauses are split into groups of whole sentences of about this size
_SECTION = re.compile(r"(?m)^\s*(\d{1,2})\.\s+([A-Z][A-Z0-9 &/,'()-]{2,})\s*$")
_ACCOUNT = re.compile(r"\b\d{9,18}\b")
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_ACCOUNT_LINE = re.compile(r"(?im)^(.*(account (number|no\.?)|a/c|iban|swift).*?:)\s*\S.*$")


@dataclass
class Chunk:
    source_type: str
    source_id: str
    title: str
    section: Optional[str]
    index: int
    text: str
    audience: str                    # all | owner | staff
    owner_email: Optional[str] = None
    content_hash: str = ""
    embedding: list = field(default_factory=list)


def mask_sensitive(s: str) -> str:
    """Bank details never reach the index (and so never the model)."""
    s = _ACCOUNT_LINE.sub(lambda m: f"{m.group(1)} [hidden]", s)
    s = _IFSC.sub("[IFSC hidden]", s)
    return _ACCOUNT.sub("[number hidden]", s)


def _windows(s: str) -> list[str]:
    s = re.sub(r"[ \t]+", " ", s).strip()
    if len(s) <= WINDOW:
        return [s] if s else []
    out, start = [], 0
    while start < len(s):
        end = min(len(s), start + WINDOW)
        if end < len(s):                      # break at a line or sentence end when possible
            cut = max(s.rfind("\n", start + WINDOW // 2, end), s.rfind(". ", start + WINDOW // 2, end))
            end = cut + 1 if cut > start else end
        out.append(s[start:end].strip())
        if end >= len(s):
            break
        start = max(end - OVERLAP, start + 1)
    return [w for w in out if w]


def split_contract(body: str) -> list[tuple[Optional[str], str]]:
    """[(section heading, text)] — one per numbered clause; the preamble
    (parties, dates) is its own chunk. Long clauses are windowed."""
    marks = list(_SECTION.finditer(body))
    if not marks:
        return [(None, w) for w in _windows(body)]
    parts = []
    if body[:marks[0].start()].strip():
        parts.append(("Parties and dates", body[:marks[0].start()]))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        parts.append((f"{m.group(1)}. {m.group(2).strip().title()}", body[m.start():end]))
    return [(head, piece) for head, part in parts for piece in _sentence_groups(part)]


_SENT = re.compile(r"(?<=[.;:])\s+(?=[A-Z(])")


def _sentence_groups(part: str) -> list[str]:
    """A clause in pieces of whole sentences (each about CLAUSE_PART
    characters), so one chunk carries one obligation: a liability cap and an
    insurance amount in the same clause end up in separate chunks, and a small
    model can't mix them up."""
    flat = re.sub(r"\s+", " ", part).strip()
    heading = _SECTION.match(part)
    head_text = ""
    if heading:
        head_text = f"{heading.group(1)}. {heading.group(2).strip()}"
        flat = flat[len(head_text):].strip() if flat.startswith(head_text) else flat
    sentences = [x for x in _SENT.split(flat) if x]
    groups, cur = [], ""
    for sent in sentences:
        if cur and len(cur) + len(sent) > CLAUSE_PART:
            groups.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        groups.append(cur)
    return groups or [flat]


def _hash(*parts) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()


ROLE_NAMES = {"dept_manager": "the department manager", "finance_head": "the finance head"}


def rule_value_text(key: str, value) -> str:
    """Rule values in words, so the model reads them right (JSON lists of
    tiers are easy to misread)."""
    if key == "approval.spend_tiers" and isinstance(value, list):
        parts = []
        for t in value:
            lo, hi = t.get("min_amount") or 0, t.get("max_amount")
            roles = [ROLE_NAMES.get(r, r) for r in t.get("required_roles") or []]
            who = "approved automatically, no approver" if not roles else "approved by " + ", then ".join(roles)
            span = f"above INR {lo:,.0f}" if hi is None else f"from INR {lo:,.0f} up to INR {hi:,.0f}"
            parts.append(f"requests {span} are {who}")
        return "; ".join(parts)
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list) and all(isinstance(x, dict) for x in value):
        return "; ".join(", ".join(f"{k} {v}" for k, v in x.items()) for x in value)
    return str(value)


TEMPLATE_LABEL = {"saas_subscription": "SaaS subscription", "hardware_purchase": "Hardware purchase",
                  "professional_services": "Professional services"}


async def load_sources(db) -> dict[tuple[str, str], list[Chunk]]:
    """Every indexable source, chunked: {(source_type, source_id): [Chunk]}."""
    out: dict[tuple[str, str], list[Chunk]] = {}

    contracts = (await db.execute(text(
        "SELECT c.id, c.contract_text, c.template, c.status, v.name AS vendor, lower(pr.requested_by) AS owner "
        "FROM contracts c LEFT JOIN vendors v ON v.id = c.vendor_id "
        "LEFT JOIN purchase_requests pr ON pr.id = c.purchase_request_id "
        "WHERE c.contract_text IS NOT NULL AND c.contract_text <> ''"))).all()
    for c in contracts:
        title = f"CT-{str(c.id)[:8]} · {TEMPLATE_LABEL.get(c.template, c.template or 'contract')} · {c.vendor or 'vendor unknown'} · {c.status}"
        body = mask_sensitive(c.contract_text)
        h = _hash(body, c.owner, c.status, c.vendor)
        out[("contract", str(c.id))] = [
            Chunk("contract", str(c.id), title, head, i, f"{title}\n{head or ''}\n{part}".strip(), "owner", c.owner, h)
            for i, (head, part) in enumerate(split_contract(body))]

    docs = (await db.execute(text(
        "SELECT d.id, d.raw_text, d.document_type, d.original_filename, lower(d.uploaded_by) AS owner, v.name AS vendor "
        "FROM documents d LEFT JOIN vendors v ON v.id = d.vendor_id "
        "WHERE d.raw_text IS NOT NULL AND d.raw_text <> ''"))).all()
    for d in docs:
        kind = (d.document_type or "document").replace("_", " ")
        title = f"DOC-{str(d.id)[:8]} · {kind} · {d.vendor or 'vendor unknown'} · {d.original_filename or ''}".strip(" ·")
        body = mask_sensitive(d.raw_text)
        h = _hash(body, d.owner, d.vendor, kind)
        out[("document", str(d.id))] = [
            Chunk("document", str(d.id), title, None, i, f"{title}\n{w}", "owner", d.owner, h)
            for i, w in enumerate(_windows(body))]

    for key, chunks in (await load_records(db)).items():
        out[key] = chunks

    rules = (await db.execute(text(
        "SELECT rule_key, display_name, description, current_value, category FROM business_rules"))).all()
    for r in rules:
        # Plain words first; the key stays only as the reference to cite.
        body = (f"Business rule “{r.display_name}” ({r.category.replace('_', ' ')}): {r.description}. "
                f"It is currently set to {rule_value_text(r.rule_key, r.current_value)}. Reference: {r.rule_key}.")
        out[("rule", r.rule_key)] = [Chunk("rule", r.rule_key, f"rule {r.rule_key}", r.display_name, 0, body, "all",
                                           None, _hash(body))]
    return out


def _one(source_type, source_id, title, body, audience, owner=None, section=None) -> list[Chunk]:
    return [Chunk(source_type, source_id, title, section, 0, f"{title}\n{body}", audience, owner, _hash(title, body, owner))]


def _money(v) -> str:
    return f"INR {float(v):,.0f}" if v is not None else "—"


async def _rows(db, sql: str) -> list:
    """Another service's table may not exist yet on a fresh database."""
    try:
        async with db.begin_nested():
            return (await db.execute(text(sql))).all()
    except Exception as e:
        logger.info(f"RAG: skipped a source ({e.__class__.__name__})")
        return []


async def load_records(db) -> dict[tuple[str, str], list[Chunk]]:
    """Live platform records as short factual passages (re-embedded when they change)."""
    out: dict[tuple[str, str], list[Chunk]] = {}
    for r in await _rows(db, (
            "SELECT pr.id, pr.request_type, pr.department, pr.amount, pr.currency, pr.status, pr.approval_chain, "
            "pr.current_approver_index, lower(pr.requested_by) AS owner, pr.requested_by, pr.created_at, pr.budget_status, "
            "pr.items, v.name AS vendor FROM purchase_requests pr LEFT JOIN vendors v ON v.id = pr.vendor_id")):
        chain = r.approval_chain or []
        waiting = (f"waiting on {chain[r.current_approver_index]} (step {r.current_approver_index + 1} of {len(chain)})"
                   if r.status == "pending_approval" and chain and r.current_approver_index < len(chain) else "")
        items = "; ".join(f"{i.get('name') or i.get('description') or i.get('app_name') or 'item'} × {i.get('quantity', 1)}"
                          for i in (r.items or [])[:6] if isinstance(i, dict))
        title = f"PR-{str(r.id)[:8]} · purchase request"
        body = (f"{(r.request_type or '').title()} request by {r.requested_by} for the {r.department} department, "
                f"{_money(r.amount)}{', raised ' + format(r.created_at, '%d %b %Y') if r.created_at else ''}. Status: {r.status}{' — ' + waiting if waiting else ''}. "
                f"Vendor: {r.vendor or 'not set'}. Budget check: {r.budget_status or '—'}. Items: {items or '—'}.")
        out[("request", str(r.id))] = _one("request", str(r.id), title, body, "owner", r.owner)

    for v in await _rows(db, (
            "SELECT v.id, v.name, v.status, v.gstin, v.contact_email, rs.final_band, rs.band, rs.rating_status, rs.total_points, "
            "rs.headline, sc.on_time_rate, sc.invoice_accuracy, sc.rfq_response_rate, sc.sla_breaches "
            "FROM vendors v LEFT JOIN LATERAL (SELECT * FROM risk_scores r WHERE r.vendor_id = v.id "
            "ORDER BY r.scored_at DESC NULLS LAST LIMIT 1) rs ON true "
            "LEFT JOIN vendor_scorecards sc ON sc.vendor_id = v.id")):
        pct = lambda x: f"{float(x):.0%}" if x is not None else "no data"
        body = (f"Vendor {v.name} (status {v.status}). Risk rating: {v.final_band or v.band or 'not scored'}"
                f"{' (' + v.rating_status + ')' if v.rating_status else ''}"
                f"{', ' + str(v.total_points) + ' of 100 risk points' if v.total_points is not None else ''}. "
                f"{(v.headline + '. ') if v.headline else ''}"
                f"On-time deliveries {pct(v.on_time_rate)}, invoice accuracy {pct(v.invoice_accuracy)}, "
                f"RFQ response rate {pct(v.rfq_response_rate)}, SLA breaches {v.sla_breaches or 0}. "
                f"GSTIN {'on file' if v.gstin else 'not on file'}.")
        out[("vendor", str(v.id))] = _one("vendor", str(v.id), f"vendor {v.name}", body, "all")

    for l in await _rows(db, (
            "SELECT l.id, l.app_name, l.total_seats, l.assigned_seats, l.cost_per_seat, l.status, l.anomaly_score, "
            "l.reclaim_cooldown_until, v.name AS vendor FROM licenses l LEFT JOIN vendors v ON v.id = l.vendor_id")):
        unused = (l.total_seats or 0) - (l.assigned_seats or 0)
        body = (f"Software licence {l.app_name} from {l.vendor or 'unknown vendor'}: {l.total_seats} seats, "
                f"{l.assigned_seats} assigned, {unused} unassigned, {_money(l.cost_per_seat)} per seat, status {l.status}. "
                f"Usage anomaly score {float(l.anomaly_score):.2f}." if l.anomaly_score is not None else
                f"Software licence {l.app_name} from {l.vendor or 'unknown vendor'}: {l.total_seats} seats, "
                f"{l.assigned_seats} assigned, {unused} unassigned, {_money(l.cost_per_seat)} per seat, status {l.status}. "
                f"Usage not scored yet.")
        out[("licence", str(l.id))] = _one("licence", str(l.id), f"licence {l.app_name}", body, "staff")

    for b in await _rows(db, (
            "SELECT b.id, b.department, b.category, b.fiscal_year, b.period, b.amount_inr, b.owner_email, "
            "COALESCE((SELECT sum(amount) FROM purchase_requests pr WHERE pr.budget_id = b.id AND pr.status NOT IN "
            "('rejected', 'cancelled', 'split')), 0) AS used FROM budgets b")):
        body = (f"Budget for {b.department} · {b.category} · {b.period} {b.fiscal_year}: {_money(b.amount_inr)}, "
                f"about {_money(b.used)} drawn by requests, {_money(float(b.amount_inr) - float(b.used))} left. "
                f"Owner: {b.owner_email or 'none'}.")
        out[("budget", str(b.id))] = _one("budget", str(b.id), f"budget {b.department} {b.category} {b.period} {b.fiscal_year}",
                                          body, "staff")

    counts = await _rows(db, "SELECT status, count(*), sum(amount) FROM purchase_requests GROUP BY status ORDER BY 2 DESC")
    if counts:
        words = {"pending_approval": "waiting for approval", "pending_grace_period": "in the reclaim grace period",
                 "backordered": "waiting for stock", "approved": "approved, contract not signed yet",
                 "ordered": "ordered (contract signed, goods not received)", "partially_received": "partly received",
                 "fulfilled": "received", "partially_invoiced": "partly invoiced", "invoice_received": "fully invoiced",
                 "rejected": "rejected", "cancelled": "cancelled", "split": "split into parts"}
        total = sum(c[1] for c in counts)
        body = f"There are {total} purchase requests in total. " + " ".join(
            f"{c[1]} purchase requests are {words.get(c[0], c[0])} (status {c[0]}), worth {_money(c[2])}."
            for c in counts)
        out[("summary", "requests")] = _one("summary", "requests", "summary of purchase requests", body, "staff")
    bands = await _rows(db, (
        "SELECT COALESCE(rs.final_band, rs.band, 'not scored'), count(*) FROM vendors v LEFT JOIN LATERAL "
        "(SELECT final_band, band FROM risk_scores r WHERE r.vendor_id = v.id ORDER BY r.scored_at DESC NULLS LAST LIMIT 1) rs "
        "ON true GROUP BY 1"))
    if bands:
        body = " ".join(f"{b[1]} vendors are currently rated {b[0]}." for b in bands)
        out[("summary", "vendor_risk")] = _one("summary", "vendor_risk", "summary of vendor risk", body, "staff")
    return out


async def embed(texts: list[str], kind: str = "search_document") -> list[list[float]]:
    """nomic-embed-text expects a task prefix: search_document / search_query."""
    prefixed = [f"{kind}: {t}" for t in texts]
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{settings.llm_api_base_url}/api/embed", json={"model": EMBED_MODEL, "input": prefixed})
        if r.status_code == 404:              # older Ollama: one text per call
            out = []
            for p in prefixed:
                rr = await client.post(f"{settings.llm_api_base_url}/api/embeddings", json={"model": EMBED_MODEL, "prompt": p})
                rr.raise_for_status()
                out.append(rr.json()["embedding"])
            return out
        r.raise_for_status()
        return r.json()["embeddings"]


async def stored_hashes(db) -> dict[tuple[str, str], str]:
    rows = (await db.execute(text(
        "SELECT source_type, document_id, max(content_hash) FROM document_embeddings "
        "WHERE source_type IS NOT NULL GROUP BY 1, 2"))).all()
    return {(r[0], r[1]): r[2] for r in rows}


async def sync(session_factory, batch: int = 32) -> dict:
    """Brings the index in line with the database. Returns counts."""
    async with session_factory() as db:
        sources = await load_sources(db)
        stored = await stored_hashes(db)
        changed = [k for k, chunks in sources.items() if chunks and stored.get(k) != chunks[0].content_hash]
        gone = [k for k in stored if k not in sources]
        # Rows from before this index existed (no source_type) can't be kept current.
        await db.execute(text("DELETE FROM document_embeddings WHERE source_type IS NULL"))
        for st, sid in gone:
            await db.execute(text("DELETE FROM document_embeddings WHERE source_type = :t AND document_id = :d"),
                             {"t": st, "d": sid})
        await db.commit()

        embedded = 0
        for k in changed:
            chunks = sources[k]
            for i in range(0, len(chunks), batch):
                part = chunks[i:i + batch]
                for c, e in zip(part, await embed([c.text for c in part])):
                    c.embedding = e
            await db.execute(text("DELETE FROM document_embeddings WHERE source_type = :t AND document_id = :d"),
                             {"t": k[0], "d": k[1]})
            for c in chunks:
                await db.execute(text(
                    "INSERT INTO document_embeddings (id, document_id, chunk_text, embedding, source_type, title, section, "
                    "chunk_index, audience, owner_email, content_hash, created_at) VALUES (:id, :d, :txt, CAST(:e AS vector), "
                    ":t, :title, :section, :i, :aud, :owner, :h, now())"),
                    {"id": str(uuid.uuid4()), "d": c.source_id, "txt": c.text, "e": str(c.embedding), "t": c.source_type,
                     "title": c.title, "section": c.section, "i": c.index, "aud": c.audience, "owner": c.owner_email,
                     "h": c.content_hash})
                embedded += 1
            await db.commit()
    result = {"sources": len(sources), "changed": len(changed), "removed": len(gone), "chunks_embedded": embedded}
    if changed or gone:
        logger.info(f"RAG index synced: {result}")
    return result


async def run_sweeps(session_factory):
    while True:
        try:
            await sync(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"RAG index sync failed (will retry): {e}")
        await asyncio.sleep(SWEEP_SECONDS)
