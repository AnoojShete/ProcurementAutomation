import os

# All services verifying tokens and auth-service issuing them must agree on
# this secret — it comes from the shared .env (JWT_SECRET), not a
# per-service .env, since it's a platform-wide trust boundary, not a
# per-service setting.
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-jwt-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = int(os.environ.get("JWT_EXPIRY_MINUTES", "60"))
JWT_REFRESH_EXPIRY_DAYS = int(os.environ.get("JWT_REFRESH_EXPIRY_DAYS", "7"))

ROLES = ("requester", "approver", "finance", "admin")
