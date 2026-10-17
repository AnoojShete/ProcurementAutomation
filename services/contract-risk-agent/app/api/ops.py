"""Replay for events this service's consumer dead-lettered. Listing and
discarding DLQ entries is platform-wide (approval-inventory-agent /ops);
replay has to run here because it re-runs this service's own handler."""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import async_session_factory
from app.kafka.consumer import CONSUMER_NAME, dispatch
from shared.auth import CurrentUser, get_current_user, require_role
from shared.eventing import replay_dlq_entry

router = APIRouter(dependencies=[Depends(require_role("finance", "admin"))])


@router.post("/dlq/{dlq_id}/replay")
async def replay(dlq_id: str, request: Request, user: CurrentUser = Depends(get_current_user)):
    app = request.app
    try:
        result = await replay_dlq_entry(
            async_session_factory, dlq_id, CONSUMER_NAME, lambda topic, event: dispatch(app, topic, event), user.email,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"data": result}
