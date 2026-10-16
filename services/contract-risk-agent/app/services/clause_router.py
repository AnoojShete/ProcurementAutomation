"""Clause extraction router: Legal-BERT primary, regex rules fallback (FR-13)."""
import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelRoutingLog
from app.services import clause_model
from app.services.clause_extraction import (
    ClauseExtractionResult, end_date_from, extract_clauses, notice_days_from, renewal_type_from,
)
from app.metrics import model_routing_total

logger = logging.getLogger(__name__)

@dataclass
class ClauseRoutingResult:
    route_name: str          # "legal_bert_primary" | "regex_fallback"
    model_used: str          # "legal-bert-cuad" | "regex"
    fallback_triggered: bool
    fallback_reason: Optional[str]   # model_unavailable | forced | low_confidence | exception
    confidence: float
    clauses: ClauseExtractionResult
    duration_ms: float

def _log_to_db(db: AsyncSession, document_id: str, result: ClauseRoutingResult):
    try:
        log_entry = ModelRoutingLog(
            id=str(uuid.uuid4()),
            document_id=document_id,
            route_name=result.route_name,
            model_used=result.model_used,
            fallback_triggered=result.fallback_triggered,
            fallback_reason=result.fallback_reason,
            confidence=result.confidence,
            duration_ms=result.duration_ms,
            created_at=datetime.now(timezone.utc),
        )
        db.add(log_entry)
    except Exception as e:
        logger.warning(f"Could not persist ModelRoutingLog: {e}")

    try:
        model_routing_total.labels(
            service="contract-risk-agent",
            route_name=result.route_name,
            model_used=result.model_used,
            fallback_triggered=str(result.fallback_triggered).lower()
        ).inc()
    except Exception:
        pass

def _fallback_forced(router: str) -> bool:
    """FR-08 demo switch: the rule dev.force_model_fallback lists routers
    whose primary should be treated as failed, so the fallback can be shown
    on demand. Honoured only in development (APP_ENV=development)."""
    from shared.rules_engine import get_rule
    from shared.runtime_env import is_development
    forced = get_rule("dev.force_model_fallback", fallback=[])
    return is_development() and isinstance(forced, list) and router in forced


def _model_clauses(contract_text: str) -> ClauseExtractionResult:
    """Legal-BERT finds the passage for each clause; the parsers turn the
    passages into values (FR-13)."""
    passages = clause_model.find_passages(contract_text)

    def text(field):
        return passages[field]["text"] if passages[field] else None
    return {
        "renewal_type": renewal_type_from(text("renewal_type")),
        "notice_period_days": notice_days_from(text("notice_period_days")),
        "contract_end_date": end_date_from(text("contract_end_date")),
    }


async def route_clause_extraction(db: AsyncSession, contract_id: str, contract_text: str) -> ClauseRoutingResult:
    """Legal-BERT (CUAD) first; the regex rules when the model isn't
    downloaded, fails, is forced off (FR-08), or finds fewer clauses than
    the rule contract.clause_extraction_fallback_threshold (share of the
    three). Evaluation: docs/results/clauses.md."""
    from shared.rules_engine import get_rule
    start_time = time.perf_counter()
    confidence = 0.0
    fallback_reason = None

    if _fallback_forced("clauses"):
        fallback_reason = "forced"
    elif not clause_model.available():
        fallback_reason = "model_unavailable"
    else:
        try:
            clauses = await asyncio.to_thread(_model_clauses, contract_text)
            confidence = round(sum(1 for v in clauses.values() if v is not None) / 3.0, 3)
            threshold = float(get_rule("contract.clause_extraction_fallback_threshold", fallback=0.4))
            if confidence < threshold:
                fallback_reason = "low_confidence"
            else:
                result = ClauseRoutingResult(
                    route_name="legal_bert_primary", model_used="legal-bert-cuad", fallback_triggered=False,
                    fallback_reason=None, confidence=confidence, clauses=clauses,
                    duration_ms=(time.perf_counter() - start_time) * 1000,
                )
                _log_to_db(db, contract_id, result)
                return result
        except Exception as e:
            logger.warning(f"[clause_router] Legal-BERT failed for contract {contract_id}: {e}", exc_info=True)
            fallback_reason = "exception"

    clauses = extract_clauses(contract_text)
    result = ClauseRoutingResult(
        route_name="regex_fallback", model_used="regex", fallback_triggered=True, fallback_reason=fallback_reason,
        confidence=confidence, clauses=clauses, duration_ms=(time.perf_counter() - start_time) * 1000,
    )
    _log_to_db(db, contract_id, result)
    return result
