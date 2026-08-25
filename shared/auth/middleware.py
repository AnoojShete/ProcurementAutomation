"""Shared auth dependency for every service except auth-service itself.

Usage in a service's main.py:

    from shared.auth import get_current_user, require_role
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

Only GET /health and GET /metrics are exempt — every other route must
depend on `get_current_user` (directly, or transitively via
`require_role`), applied at the router level so it's impossible to forget
on an individual endpoint.
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.auth.jwt_tokens import decode_token, TokenError

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    email: str
    role: str


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
    return CurrentUser(id=claims["sub"], email=claims["email"], role=claims["role"])


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
