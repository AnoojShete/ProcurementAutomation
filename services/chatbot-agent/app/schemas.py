from typing import Optional, List
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatMessageOut(BaseModel):
    role: str
    content: str

class ChatResponse(BaseModel):
    session_id: str
    message: str
    history: List[ChatMessageOut]