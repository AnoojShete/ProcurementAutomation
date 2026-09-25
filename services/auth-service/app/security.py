import hashlib

import bcrypt
import httpx


async def is_password_breached(password: str) -> bool:
    """Return whether HaveIBeenPwned has seen this password.

    Only the first five SHA-1 characters are sent; the remaining suffix is
    matched locally to preserve the API's k-anonymity design.
    """
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"https://api.pwnedpasswords.com/range/{prefix}")
        response.raise_for_status()
    return any(line.split(":", 1)[0].strip().upper() == suffix for line in response.text.splitlines())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
