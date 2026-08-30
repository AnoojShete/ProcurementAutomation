"""Persists one pipeline_checkpoints row per pipeline stage from the
AgentResult trail app/services/pipeline.py builds up on the envelope (see
app/services/agent_contracts.py). A diagnostic trail, not part of the
business transaction — a checkpoint-write failure is logged and
swallowed, never allowed to fail real document processing.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PipelineCheckpoint
from app.services.agent_contracts import AgentResult

logger = logging.getLogger(__name__)


async def write_checkpoints(
    db: AsyncSession,
    document_id: str,
    agent_trail: List[AgentResult],
    stage_durations_ms: Dict[str, float],
) -> None:
    try:
        for stage_index, result in enumerate(agent_trail):
            db.add(
                PipelineCheckpoint(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    stage_index=stage_index,
                    agent_name=result.agent_name,
                    agent_version=result.agent_version,
                    task_id=result.task_id,
                    confidence=result.confidence,
                    validation_status=result.validation_status,
                    errors=result.errors,
                    warnings=result.warnings,
                    duration_ms=stage_durations_ms.get(result.agent_name),
                    created_at=datetime.now(timezone.utc),
                )
            )
        await db.flush()
    except Exception as e:
        logger.warning(f"Failed to persist pipeline checkpoints for document_id={document_id}: {e}")
