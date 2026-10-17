"""Learning from reviewer corrections.

Every human review is a labelled example, and until now each one was
thrown away: submit_review overwrote the fields and the next document from
the same vendor needed the same fix. This module keeps them and uses them.

  record_review()        — on each review: which fields the reviewer
                           changed, and for each corrected value, the label
                           that precedes it in the document text ("Amount
                           Due", "Bill#"). Label counts per vendor+field are
                           the learned hints.
  vendor_learning_agent  — pipeline stage after vendor matching: for a
                           vendor with a hint confirmed by at least
                           MIN_SUPPORT reviews, read the field from next to
                           that label and override/confirm the extraction.
  vendor_review_threshold — per-vendor review threshold: vendors whose
                           documents reviewers keep confirming unchanged
                           need less review; vendors that keep needing
                           fixes need more.

A single correction never changes behaviour (MIN_SUPPORT), so one wrong
review can't poison a vendor's hints.
"""
import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

MIN_SUPPORT = 2
MIN_REVIEWS_FOR_CALIBRATION = 5
RELIABLE_CLEAN_RATE = 0.9
UNRELIABLE_CLEAN_RATE = 0.5
RECENT_REVIEWS = 20

# field -> value kind. Only fields that sit next to a label in the text.
LEARNABLE = {
    "total": "amount",
    "tax_amount": "amount",
    "document_number": "token",
    "invoice_number": "token",
    "po_number": "token",
    "quote_number": "token",
    "document_date": "date",
    "invoice_date": "date",
    "due_date": "date",
}
# Fields that feed a confidence score, and which score.
CONFIDENCE_KEY = {
    "total": "total", "document_number": "document_number", "invoice_number": "document_number",
    "po_number": "document_number", "quote_number": "document_number",
    "document_date": "document_date", "invoice_date": "document_date",
}
# Fields that mirror each other in the extraction output.
MIRRORS = {
    "invoice_number": "document_number", "po_number": "document_number", "quote_number": "document_number",
    "invoice_date": "document_date",
}

_CURRENCY = r"(?:INR|USD|EUR|Rs\.?|₹|\$)?"
_VALUE_PATTERNS = {
    "amount": re.compile(r"^[\s:#\-]*" + _CURRENCY + r"\s*([\d,]+(?:\.\d{1,2})?)"),
    "token": re.compile(r"^[\s:#\-]*([A-Za-z0-9][A-Za-z0-9/_.\-]*)"),
    "date": re.compile(r"^[\s:\-]*([0-9A-Za-z ,./\-]{6,20})"),
}


# --- pure helpers -------------------------------------------------------------

def normalize_value(kind: str, value) -> Optional[str]:
    if value is None or value == "":
        return None
    if kind == "amount":
        try:
            return f"{float(str(value).replace(',', '')):.2f}"
        except ValueError:
            return None
    if kind == "date":
        parsed = _parse_date(str(value))
        return parsed.isoformat() if parsed else None
    return str(value).strip()


def _parse_date(value: str) -> Optional[date]:
    try:
        from dateutil import parser as d_parser
        return d_parser.parse(value.strip(), dayfirst=False, fuzzy=False).date()
    except Exception:
        return None


def _value_forms(kind: str, value: str) -> list[str]:
    if kind == "amount":
        v = float(value)
        return list(dict.fromkeys([f"{v:,.2f}", f"{v:.2f}", f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"]))
    if kind == "date":
        d = date.fromisoformat(value)
        return [d.isoformat(), d.strftime("%d/%m/%Y"), d.strftime("%d-%m-%Y"), d.strftime("%d %b %Y"),
                d.strftime("%b %d, %Y"), d.strftime("%m/%d/%Y")]
    return [value]


def clean_label(label: str) -> Optional[str]:
    label = re.sub(_CURRENCY + r"\s*$", "", label.strip())
    label = re.sub(r"[\s:#\-.]+$", "", label).strip()
    label = re.sub(r"\s+", " ", label)
    if not label or not re.search(r"[A-Za-z]", label) or len(label) > 40:
        return None
    return label


def derive_label(raw_text: str, kind: str, value: str) -> Optional[str]:
    """The text right before `value` on the line where it appears, e.g.
    'Amount Due' for 'Amount Due: 3,894.00'."""
    if not raw_text or value is None:
        return None
    for line in raw_text.splitlines():
        for form in _value_forms(kind, value):
            idx = line.find(form)
            if idx > 0:
                label = clean_label(line[:idx])
                if label:
                    return label
    return None


def read_by_label(raw_text: str, label: str, kind: str) -> Optional[str]:
    """Inverse of derive_label: the value that follows `label`."""
    if not raw_text:
        return None
    pattern = _VALUE_PATTERNS[kind]
    for line in raw_text.splitlines():
        m = re.search(re.escape(label), line, re.IGNORECASE)
        if not m:
            continue
        v = pattern.match(line[m.end():])
        if not v:
            continue
        raw = v.group(1).strip()
        normalized = normalize_value(kind, raw)
        if normalized:
            return normalized
    return None


def corrected_fields(before: dict, after: dict) -> dict:
    """{field: (old, new)} for learnable fields the reviewer actually changed."""
    changes = {}
    for field, kind in LEARNABLE.items():
        if field not in after:
            continue
        old, new = normalize_value(kind, before.get(field)), normalize_value(kind, after.get(field))
        if new is not None and old != new:
            changes[field] = (before.get(field), after.get(field))
    return changes


def calibrated_threshold(base: float, reviews: int, clean: int) -> tuple[float, str]:
    if reviews < MIN_REVIEWS_FOR_CALIBRATION:
        return base, "default"
    rate = clean / reviews
    if rate >= RELIABLE_CLEAN_RATE:
        return round(max(0.6, base - 0.15), 2), "relaxed"
    if rate < UNRELIABLE_CLEAN_RATE:
        return round(min(0.95, base + 0.1), 2), "strict"
    return base, "default"


# --- database side -----------------------------------------------------------

async def record_review(db, doc, before: dict, after: dict, reviewer: str) -> dict:
    """Stores the review outcome and any learned hints. Caller commits."""
    changes = corrected_fields(before, after)
    raw_text = doc.raw_text or ""
    learned = []
    for field, (old, new) in changes.items():
        kind = LEARNABLE[field]
        norm_new = normalize_value(kind, new)
        label = derive_label(raw_text, kind, norm_new)
        await db.execute(
            text(
                "INSERT INTO extraction_feedback (id, document_id, vendor_id, field, original_value, corrected_value, "
                "label, reviewer, created_at) VALUES (:id, :doc, :vendor, :field, :old, :new, :label, :by, now())"
            ),
            {"id": str(uuid.uuid4()), "doc": doc.id, "vendor": doc.vendor_id, "field": field,
             "old": None if old is None else str(old), "new": str(new), "label": label, "by": reviewer},
        )
        if label and doc.vendor_id:
            await db.execute(
                text(
                    "INSERT INTO vendor_field_hints (vendor_id, field, label, support, last_seen_at) "
                    "VALUES (:vendor, :field, :label, 1, now()) ON CONFLICT (vendor_id, field, label) "
                    "DO UPDATE SET support = vendor_field_hints.support + 1, last_seen_at = now()"
                ),
                {"vendor": doc.vendor_id, "field": field, "label": label},
            )
            learned.append({"field": field, "label": label})
    await db.execute(
        text(
            "INSERT INTO review_outcomes (document_id, vendor_id, fields_corrected, corrected_fields, reviewer, reviewed_at) "
            "VALUES (:doc, :vendor, :n, CAST(:fields AS JSONB), :by, now()) ON CONFLICT (document_id) DO UPDATE SET "
            "vendor_id = EXCLUDED.vendor_id, fields_corrected = EXCLUDED.fields_corrected, "
            "corrected_fields = EXCLUDED.corrected_fields, reviewer = EXCLUDED.reviewer, reviewed_at = now()"
        ),
        {"doc": doc.id, "vendor": doc.vendor_id, "n": len(changes), "fields": json.dumps(sorted(changes)), "by": reviewer},
    )
    return {"corrected": sorted(changes), "learned": learned}


async def vendor_hints(db, vendor_id: str) -> dict:
    """field -> (label, support), strongest label per field with enough support."""
    rows = (
        await db.execute(
            text(
                "SELECT DISTINCT ON (field) field, label, support FROM vendor_field_hints "
                "WHERE vendor_id = :v AND support >= :min ORDER BY field, support DESC, last_seen_at DESC"
            ),
            {"v": vendor_id, "min": MIN_SUPPORT},
        )
    ).all()
    return {r.field: (r.label, r.support) for r in rows}


async def vendor_review_threshold(db, vendor_id: str, base: float) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT count(*) AS reviews, count(*) FILTER (WHERE fields_corrected = 0) AS clean FROM ("
                "SELECT fields_corrected FROM review_outcomes WHERE vendor_id = :v "
                "ORDER BY reviewed_at DESC LIMIT :n) recent"
            ),
            {"v": vendor_id, "n": RECENT_REVIEWS},
        )
    ).first()
    reviews, clean = int(row.reviews or 0), int(row.clean or 0)
    threshold, mode = calibrated_threshold(base, reviews, clean)
    return {"threshold": threshold, "mode": mode, "reviews": reviews, "clean": clean}


async def vendor_learning_agent(db, envelope: dict) -> dict:
    from app.services.agent_contracts import record_agent_result
    from app.services.confidence import load_threshold

    vendor_id = envelope.get("vendor_id")
    if not vendor_id:
        record_agent_result(envelope, "vendor_learning_agent", next_action="skipped_no_vendor")
        return envelope

    fields = envelope["extracted_fields"]
    conf = envelope["field_confidences"]
    applied = []
    for field, (label, support) in (await vendor_hints(db, vendor_id)).items():
        if field not in fields:
            continue
        kind = LEARNABLE[field]
        value = read_by_label(envelope.get("raw_text", ""), label, kind)
        if value is None:
            continue
        current = normalize_value(kind, fields.get(field))
        new_value = float(value) if kind == "amount" else value
        if current != value:
            applied.append({"field": field, "label": label, "support": support,
                            "previous": fields.get(field), "value": new_value, "action": "corrected"})
            fields[field] = new_value
            mirror = MIRRORS.get(field)
            if mirror and mirror in fields:
                fields[mirror] = new_value
        else:
            applied.append({"field": field, "label": label, "support": support, "value": new_value, "action": "confirmed"})
        key = CONFIDENCE_KEY.get(field)
        if key and key in conf:
            conf[key] = max(conf[key], 0.95)

    calibration = await vendor_review_threshold(db, vendor_id, load_threshold())
    envelope["review_threshold"] = calibration
    if applied:
        envelope["learned_fields"] = applied
    logger.info(
        f"[vendor_learning_agent] document_id={envelope['document_id']} applied={len(applied)} "
        f"threshold={calibration['threshold']} ({calibration['mode']}, {calibration['clean']}/{calibration['reviews']} clean)"
    )
    record_agent_result(
        envelope, "vendor_learning_agent",
        warnings=[f"{a['field']} {a['action']} from learned label '{a['label']}'" for a in applied],
    )
    return envelope


async def learning_stats(db) -> dict:
    vendors = (
        await db.execute(text("""
            SELECT v.id, v.name,
                   count(r.document_id) AS reviews,
                   count(r.document_id) FILTER (WHERE r.fields_corrected = 0) AS clean
            FROM vendors v JOIN review_outcomes r ON r.vendor_id = v.id
            GROUP BY v.id, v.name ORDER BY count(r.document_id) DESC LIMIT 50
        """))
    ).all()
    hints = (
        await db.execute(text(
            "SELECT vendor_id, field, label, support, last_seen_at FROM vendor_field_hints ORDER BY support DESC"
        ))
    ).all()
    by_field = (
        await db.execute(text("SELECT field, count(*) AS n FROM extraction_feedback GROUP BY field ORDER BY n DESC"))
    ).all()
    daily = (
        await db.execute(text("""
            SELECT date_trunc('day', uploaded_at)::date AS day, count(*) AS documents,
                   count(*) FILTER (WHERE needs_review) AS needs_review,
                   count(*) FILTER (WHERE extracted ? 'learned_fields') AS learned
            FROM documents WHERE uploaded_at > now() - interval '30 days' AND status = 'classified'
            GROUP BY 1 ORDER BY 1
        """))
    ).all()
    from app.services.confidence import load_threshold
    base = load_threshold()
    hints_by_vendor: dict = {}
    for h in hints:
        hints_by_vendor.setdefault(str(h.vendor_id), []).append(
            {"field": h.field, "label": h.label, "support": h.support, "active": h.support >= MIN_SUPPORT}
        )
    out_vendors = []
    for v in vendors:
        threshold, mode = calibrated_threshold(base, v.reviews, v.clean)
        out_vendors.append({
            "vendor_id": str(v.id), "vendor_name": v.name, "reviews": v.reviews, "clean": v.clean,
            "threshold": threshold, "mode": mode, "hints": hints_by_vendor.get(str(v.id), []),
        })
    return {
        "base_threshold": base,
        "min_support": MIN_SUPPORT,
        "min_reviews_for_calibration": MIN_REVIEWS_FOR_CALIBRATION,
        "vendors": out_vendors,
        "corrections_by_field": [{"field": r.field, "count": r.n} for r in by_field],
        "daily": [{"day": r.day.isoformat(), "documents": r.documents, "needs_review": r.needs_review,
                   "learned": r.learned} for r in daily],
    }
