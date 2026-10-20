import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import ChatSession, ChatMessage
from app.schemas import ChatRequest, ChatResponse, ChatMessageOut
from app.services.llm_client import query_llm_with_tools
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
