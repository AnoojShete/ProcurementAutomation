"""Shared auth dependency for every service except auth-service itself.

Usage in a service's main.py:

    from shared.auth import get_current_user, require_role, require_step_up
    app.include_router(health.router)                       # no auth
    Instrumentator().instrument(app).expose(app, "/metrics") # no auth
    app.include_router(
        contracts.router, prefix="/contracts",
        dependencies=[Depends(get_current_user)],            # any logged-in user
    )
    app.include_router(
        admin.router, prefix="/admin",
        dependencies=[Depends(require_role("admin"))],       # role-gated
    )

Step-up re-authentication (OWASP API2):
Critical actions require recent password confirmation (valid for 5 minutes):
    dependencies=[Depends(require_step_up())]
"""
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.auth.jwt_tokens import decode_token, TokenError

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    email: str
    role: str
    reauth_at: Optional[float] = None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        claims = decode_token(credentials.credentials)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if claims.get("type") != "access":
        raise HTTPException(status_code=401, detail="not an access token")
    user_id = claims.get("sub")
    email = claims.get("email")
    role = claims.get("role")
    reauth_at = claims.get("reauth_at")
    if not all(isinstance(value, str) and value for value in (user_id, email, role)):
        raise HTTPException(status_code=401, detail="invalid token claims")
    return CurrentUser(
        id=user_id,
        email=email,
        role=role,
        reauth_at=float(reauth_at) if reauth_at is not None else None,
    )


def require_role(*roles: str):
    """FastAPI dependency factory: `Depends(require_role("approver", "finance"))`."""

    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"role '{user.role}' is not permitted — requires one of {list(roles)}",
            )
        return user

    return _check


def require_step_up(max_age_seconds: int = 300):
    """FastAPI dependency for sensitive operations requiring recent re-authentication (OWASP API2).
    Requires `reauth_at` claim within the last `max_age_seconds` (default 5 minutes).
    """

    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        now = time.time()
        if user.reauth_at is None or (now - user.reauth_at > max_age_seconds):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "step_up_required",
                    "message": "Step-up re-authentication required. Re-enter your password to proceed.",
                    "step_up_timeout_seconds": max_age_seconds,
                },
            )
        return user

    return _check
