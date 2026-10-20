import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import ChatSession, ChatMessage
from app.schemas import ChatRequest, ChatResponse, ChatMessageOut
from app.services.llm_client import query_llm_with_tools
from shared.auth.middleware import get_current_user, CurrentUser

router = APIRouter()

@router.post("/", response_model=ChatResponse)
async def send_message(
    body: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    session_id = body.session_id

    # Create session if needed
    if not session_id:
        session_id = str(uuid.uuid4())
        new_session = ChatSession(id=session_id, user_id=user.id, title=body.message[:50], created_at=now, updated_at=now)
        db.add(new_session)
    
    # Save User message
    user_msg = ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role="user", content=body.message, created_at=now)
    db.add(user_msg)
    await db.commit()

    # Load recent history
    history_res = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at))
    history = history_res.scalars().all()[-10:] # last 10 messages

    # Call LLM with Tool Calling!
    reply = await query_llm_with_tools(history, user, db)

    # Save Assistant message
    assistant_msg = ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role="assistant", content=reply, created_at=datetime.now(timezone.utc))
    db.add(assistant_msg)
    await db.commit()

    # Format history for frontend
    out_history = [ChatMessageOut(role=m.role, content=m.content) for m in history]
    out_history.append(ChatMessageOut(role="assistant", content=reply))

    return ChatResponse(session_id=session_id, message=reply, history=out_history)