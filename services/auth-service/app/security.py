"""Password hashing and password policy.

New passwords are hashed with argon2id (the winner of the Password Hashing
Competition, recommended by OWASP): it is deliberately slow and needs
64 MiB of memory per guess, so a stolen database can't be brute-forced
cheaply on GPUs. The stored string carries its own salt and parameters:

    $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>

Accounts created before the switch have bcrypt hashes ("$2b$..."). Those
still verify, and login replaces them with argon2id (`needs_rehash`), so
they upgrade without anyone resetting a password.

Plain-text passwords are never stored, logged or returned by any endpoint.
"""
import hashlib

import bcrypt
import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# argon2-cffi's defaults are RFC 9106's "low memory" profile:
# time_cost=3, memory_cost=64 MiB, parallelism=4, argon2id.
_hasher = PasswordHasher()

MIN_PASSWORD_CHARS = 12
# argon2 hashes the whole input, so there is no 72-byte cut-off like
# bcrypt's; the cap only stops someone posting megabytes to burn CPU.
MAX_PASSWORD_CHARS = 128


class PasswordPolicyError(ValueError):
    pass


def check_password_policy(password: str, email: str = "") -> None:
    """Raises PasswordPolicyError with a message safe to show the user."""
    if len(password) < MIN_PASSWORD_CHARS:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_CHARS} characters.")
    if len(password) > MAX_PASSWORD_CHARS:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_CHARS} characters.")
    if email and normalize_email(email) in password.lower():
        raise PasswordPolicyError("Password must not contain your email address.")


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
    return _hasher.hash(plain)


def _is_bcrypt(hashed: str) -> bool:
    return hashed.startswith(("$2a$", "$2b$", "$2y$"))


def verify_password(plain: str, hashed: str) -> bool:
    if _is_bcrypt(hashed):
        # bcrypt only ever saw the first 72 bytes of a legacy password.
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    try:
        return _hasher.verify(hashed, plain)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """True for legacy bcrypt hashes, or argon2 hashes made with weaker
    parameters than the current ones."""
    return _is_bcrypt(hashed) or _hasher.check_needs_rehash(hashed)


_DUMMY_HASH = _hasher.hash("timing-equaliser")


def verify_password_dummy(plain: str) -> None:
    """Burns the same argon2 work as verify_password for unknown accounts,
    so response time doesn't reveal whether an account exists."""
    verify_password(plain, _DUMMY_HASH)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()
