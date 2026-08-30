"""Typed contract each pipeline stage in app/services/pipeline.py produces,
alongside the plain envelope dict it already returns and mutates. Lets a
downstream stage check what an upstream stage actually claims about its
own output (confidence, validation_status) instead of only trusting that
expected envelope keys are present — see pipeline.py's per-stage
validation checks.

Deliberately additive: every pipeline function keeps its existing
envelope-dict signature and return value (document_service.py's call
sites are unchanged). Each stage just also appends one AgentResult to
envelope["_agent_trail"], which app/services/checkpoints.py persists as
one pipeline_checkpoints row per stage after the pipeline finishes.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

AGENT_VERSION = "1.0.0"

ValidationStatus = Literal["valid", "invalid", "needs_review"]


class AgentResult(BaseModel):
    task_id: str
    agent_name: str
    agent_version: str = AGENT_VERSION
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    input_reference: str
    confidence: Optional[float] = None
    validation_status: ValidationStatus = "valid"
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    next_action: str = "continue"


def record_agent_result(
    envelope: dict,
    agent_name: str,
    *,
    confidence: Optional[float] = None,
    validation_status: ValidationStatus = "valid",
    errors: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
    next_action: str = "continue",
) -> AgentResult:
    result = AgentResult(
        task_id=str(uuid.uuid4()),
        agent_name=agent_name,
        input_reference=str(envelope["document_id"]),
        confidence=confidence,
        validation_status=validation_status,
        errors=errors or [],
        warnings=warnings or [],
        next_action=next_action,
    )
    envelope.setdefault("_agent_trail", []).append(result)
    return result
