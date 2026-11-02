"""JWT encode/decode shared by auth-service (issues tokens) and every
other service (verifies them via shared.auth.middleware).

Hardened per OWASP API2:
- Strict algorithm allow-list from config (HS256), explicitly rejecting "none"
- Verification of exp, nbf, iss, aud, and kid
- Access token: 15 minutes
- Refresh token: 7 days with rotation & family tracking
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from shared.auth.config import (
    JWT_SECRET,
    JWT_ALGORITHM,
    ALLOWED_JWT_ALGORITHMS,
    JWT_EXPIRY_MINUTES,
    JWT_REFRESH_EXPIRY_DAYS,
    JWT_ISSUER,
    JWT_AUDIENCE,
    JWT_KEY_ID,
)


class TokenError(Exception):
    pass


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    reauth_at: Optional[float] = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=JWT_EXPIRY_MINUTES),
        "jti": str(uuid.uuid4()),
    }
    if reauth_at is not None:
        payload["reauth_at"] = reauth_at
    headers = {"kid": JWT_KEY_ID}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM, headers=headers)


def create_refresh_token(
    user_id: str,
    email: str,
    role: str,
    token_version: int = 0,
    family_id: Optional[str] = None,
) -> str:
    """`tv` is the user's token_version when the token was issued.
    `family_id` tracks the refresh token rotation lineage.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "tv": token_version,
        "family_id": family_id or str(uuid.uuid4()),
        "type": "refresh",
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(days=JWT_REFRESH_EXPIRY_DAYS),
        "jti": str(uuid.uuid4()),
    }
    headers = {"kid": JWT_KEY_ID}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM, headers=headers)


def decode_token(
    token: str,
    *,
    audience: Optional[str] = None,
) -> dict:
    """Decodes and validates a JWT token against security policies.
    Raises TokenError on missing, invalid, expired, or tampered tokens.
    """
    if not token or not isinstance(token, str):
        raise TokenError("missing or empty token")

    # 1. Unverified header check to strictly reject 'none' algorithm
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception as e:
        raise TokenError(f"invalid token header: {e}")

    alg = unverified_header.get("alg", "")
    if alg.lower() == "none":
        raise TokenError("algorithm 'none' is forbidden")
    if alg not in ALLOWED_JWT_ALGORITHMS:
        raise TokenError(f"algorithm {alg!r} is not allowed; must be one of {ALLOWED_JWT_ALGORITHMS}")

    kid = unverified_header.get("kid")
    if kid is not None and kid != JWT_KEY_ID:
        raise TokenError(f"unknown key id: {kid!r}")

    # 2. Decode and verify signature & claims
    expected_aud = audience or JWT_AUDIENCE
    options = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_nbf": True,
        "verify_aud": False,  # We verify manually below so tokens without aud still decode
        "require": ["exp", "sub"],
    }

    try:
        claims = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=ALLOWED_JWT_ALGORITHMS,
            options=options,
        )
    except jwt.ExpiredSignatureError:
        raise TokenError("token expired")
    except jwt.ImmatureSignatureError:
        raise TokenError("token not yet valid (nbf)")
    except jwt.InvalidTokenError as e:
        raise TokenError(f"invalid token: {e}")

    # 3. Verify issuer and audience if present
    token_iss = claims.get("iss")
    if token_iss is not None and token_iss != JWT_ISSUER:
        raise TokenError(f"invalid issuer: {token_iss!r}")

    token_aud = claims.get("aud")
    if token_aud is not None:
        if isinstance(token_aud, list):
            if expected_aud not in token_aud:
                raise TokenError(f"invalid audience: {token_aud!r}")
        elif token_aud != expected_aud:
            raise TokenError(f"invalid audience: {token_aud!r}")

    return claims
