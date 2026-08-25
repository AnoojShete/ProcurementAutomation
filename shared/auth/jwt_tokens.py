"""JWT encode/decode shared by auth-service (issues tokens) and every
other service (verifies them via shared.auth.middleware)."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from shared.auth.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_MINUTES, JWT_REFRESH_EXPIRY_DAYS


class TokenError(Exception):
    pass


def create_access_token(user_id: str, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRY_MINUTES),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=JWT_REFRESH_EXPIRY_DAYS),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Raises TokenError on missing/invalid/expired tokens — callers turn
    this into the standard 401 {"error": {...}} envelope."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise TokenError("token expired")
    except jwt.InvalidTokenError as e:
        raise TokenError(f"invalid token: {e}")
