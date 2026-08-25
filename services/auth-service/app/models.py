"""auth-service owns its own `users` table in its own migration — this is
NOT part of shared/db/init.sql, per Prompt 5's instruction (a users table
is auth-service's own concern, not the shared procurement schema)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Uuid = PG_UUID(as_uuid=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "auth_users"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
