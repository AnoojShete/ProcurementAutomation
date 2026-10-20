from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase): pass

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    session_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(768))
    # RAG index metadata (app/services/indexer.py)
    source_type: Mapped[Optional[str]] = mapped_column(String(20))   # contract | document | rule
    title: Mapped[Optional[str]] = mapped_column(Text)
    section: Mapped[Optional[str]] = mapped_column(Text)
    chunk_index: Mapped[Optional[int]] = mapped_column(Integer)
    audience: Mapped[Optional[str]] = mapped_column(String(10))      # all | owner (staff always see)
    owner_email: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
