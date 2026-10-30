import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import ChatSession, ChatMessage
from app.schemas import ChatRequest, ChatResponse, ChatMessageOut
from app.services.llm_client import query_llm_with_tools, stream_llm_with_tools
from shared.auth.middleware import get_current_user, CurrentUser

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/", response_model=ChatResponse)
async def send_message(
    body: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    session_id = body.session_id

    if not session_id:
        session_id = str(uuid.uuid4())
        new_session = ChatSession(id=session_id, user_id=user.id, title=body.message[:50], created_at=now, updated_at=now)
        db.add(new_session)
        await db.commit()
    
    user_msg = ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role="user", content=body.message, created_at=now)
    db.add(user_msg)
    await db.commit()

    history_res = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at))
    history = list(history_res.scalars().all())[-10:]

    try:
        # The user object scopes both retrieval and tool calls to what this user may see.
        reply = await query_llm_with_tools(history, user, db)
    except Exception as e:
        logger.error(f"Assistant reply failed: {type(e).__name__}: {e}", exc_info=True)
        reply = "Sorry, I am having trouble connecting to my AI brain."

    assistant_msg = ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role="assistant", content=reply, created_at=datetime.now(timezone.utc))
    db.add(assistant_msg)
    await db.commit()

    out_history = [ChatMessageOut(role=m.role, content=m.content) for m in history]
    out_history.append(ChatMessageOut(role="assistant", content=reply))

    return ChatResponse(session_id=session_id, message=reply, history=out_history)


@router.post("/stream")
async def send_message_stream(
    body: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Stream the assistant reply token-by-token as Server-Sent Events.

    The final SSE event contains ``{"done": true, "full_reply": "..."}`` and a
    ``session_id`` field so the client can track the conversation.  The assistant
    message is persisted to the database *after* the stream completes.
    """
    import json as _json

    now = datetime.now(timezone.utc)
    session_id = body.session_id

    if not session_id:
        session_id = str(uuid.uuid4())
        new_session = ChatSession(id=session_id, user_id=user.id, title=body.message[:50], created_at=now, updated_at=now)
        db.add(new_session)
        await db.commit()

    user_msg = ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role="user", content=body.message, created_at=now)
    db.add(user_msg)
    await db.commit()

    history_res = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at))
    history = list(history_res.scalars().all())[-10:]

    async def event_generator():
        full_reply = ""
        try:
            async for sse_chunk in stream_llm_with_tools(history, user, db):
                # Parse the SSE data line to accumulate the full reply
                if sse_chunk.startswith("data: "):
                    try:
                        payload = _json.loads(sse_chunk[6:].strip())
                        if payload.get("done"):
                            full_reply = payload.get("full_reply", full_reply)
                            # Inject session_id into the final event
                            payload["session_id"] = session_id
                            yield f"data: {_json.dumps(payload)}\n\n"
                            continue
                    except _json.JSONDecodeError:
                        pass
                yield sse_chunk
        except Exception as e:
            logger.error(f"Stream failed: {type(e).__name__}: {e}", exc_info=True)
            full_reply = full_reply or "Sorry, I am having trouble connecting to my AI brain."
            yield f"data: {_json.dumps({'token': full_reply})}\n\n"
            yield f"data: {_json.dumps({'done': True, 'full_reply': full_reply, 'session_id': session_id})}\n\n"
        finally:
            # Persist the assistant message after the stream finishes
            if full_reply:
                assistant_msg = ChatMessage(
                    id=str(uuid.uuid4()), session_id=session_id,
                    role="assistant", content=full_reply,
                    created_at=datetime.now(timezone.utc))
                db.add(assistant_msg)
                await db.commit()

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

