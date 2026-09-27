"""auth-service owns its own `users` table in its own migration — this is
NOT part of shared/db/init.sql, per Prompt 5's instruction (a users table
is auth-service's own concern, not the shared procurement schema)."""
from datetime import datetime
from typing import Optional, Any

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
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
    # migrations/versions/0003_account_lifecycle.py
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Copied into every refresh token as "tv"; bumping it ends every
    # existing session at its next refresh.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class BusinessRule(Base):
    __tablename__ = "business_rules"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    rule_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    current_value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    default_value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    min_value: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    max_value: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class BusinessRuleHistory(Base):
    __tablename__ = "business_rule_history"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    rule_key: Mapped[str] = mapped_column(String(255), nullable=False)
    old_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    changed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    justification: Mapped[str] = mapped_column(String, nullable=False)
