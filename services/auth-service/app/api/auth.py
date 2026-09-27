"""Account endpoints: sign-up, email verification, login, logout, forgot /
reset password, change password.

Safety rules applied throughout:
  - Answers never reveal whether an email address has an account: sign-up,
    resend-verification and forgot-password always return the same 202
    message, and a wrong email or wrong password give the same 401.
  - Wrong passwords count towards a per-address lockout (app/lockout.py).
  - Email links are single-use and expire (app/account_tokens.py).
  - Changing or resetting a password bumps token_version, which ends every
    other session at its next refresh.
  - The gateway rate-limits these endpoints per IP (infra/nginx/nginx.conf).
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import account_tokens, audit, emails, lockout
from app.database import get_db
from app.models import User
from app.schemas import (
    AccessTokenResponse, ChangePasswordRequest, DataResponse, EmailOnlyRequest, LoginRequest, RegisterRequest,
    ResetPasswordRequest, TokenRequest, TokenResponse, UserResponse,
)
from app.security import (
    PasswordPolicyError, check_password_policy, hash_password, is_password_breached, needs_rehash, normalize_email,
    verify_password, verify_password_dummy,
)
from app.session_cookies import clear_session_cookies, refresh_token_from, require_csrf, set_session_cookies
from shared.auth.config import JWT_EXPIRY_MINUTES
from shared.auth.jwt_tokens import TokenError, create_access_token, create_refresh_token, decode_token
from shared.auth.middleware import CurrentUser, get_current_user

router = APIRouter()

SIGNUP_ACCEPTED = ("Check your inbox. If this address can be used to sign up, we've sent it a link "
                   "to confirm it. The link expires in 24 hours.")
RESEND_ACCEPTED = "If that address has an account waiting for confirmation, we've sent a new link."
RESET_ACCEPTED = ("If an account exists for that address, we've sent a link to reset the password. "
                  "The link expires in 30 minutes.")
INVALID_CREDENTIALS = "Invalid email or password."
INVALID_LINK = {"code": "invalid_token",
                "message": "This link is invalid, has expired, or was already used. Request a new one."}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(func.lower(User.email) == email))).scalars().first()


async def _user_by_id(db: AsyncSession, user_id: str) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalars().first()


async def _require_new_password_ok(password: str, email: str) -> None:
    """Length / not-the-email rules, then the breached-password check."""
    try:
        check_password_policy(password, email)
    except PasswordPolicyError as e:
        raise HTTPException(status_code=400, detail={"code": "weak_password", "message": str(e)})
    try:
        breached = await is_password_breached(password)
    except Exception:
        # Fail closed: without the check we can't tell a leaked password
        # from a good one.
        raise HTTPException(status_code=503, detail="The password check service is unavailable. Try again shortly.")
    if breached:
        raise HTTPException(status_code=400, detail={
            "code": "weak_password",
            "message": "This password has appeared in a known data breach. Choose a different one."})


def _session_response(response: Response, user: User) -> DataResponse:
    set_session_cookies(response, create_refresh_token(user.id, user.email, user.role, user.token_version))
    return DataResponse(data=TokenResponse(
        access_token=create_access_token(user.id, user.email, user.role), expires_in_minutes=JWT_EXPIRY_MINUTES))


def _accepted(message: str) -> DataResponse:
    return DataResponse(data={"message": message})


# ---------------------------------------------------------------- sign-up

@router.post("/register", response_model=DataResponse, status_code=202)
async def register(data: RegisterRequest, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    email = normalize_email(data.email)
    await _require_new_password_ok(data.password, email)
    # Hashed before the lookup so "new" and "already registered" take the
    # same time.
    hashed = hash_password(data.password)

    existing = await _user_by_email(db, email)
    if existing is None:
        user = User(id=str(uuid.uuid4()), email=email, hashed_password=hashed, role="requester",
                    created_at=_now(), is_active=True, token_version=0, password_changed_at=_now())
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            # Someone registered the same address at the same moment.
            await db.rollback()
            existing = await _user_by_email(db, email)
        else:
            token = await account_tokens.issue(db, user.id, account_tokens.VERIFY_EMAIL)
            await audit.record(db, user.id, "user.registered", performed_by=email)
            await db.commit()
            background.add_task(emails.send_quietly, email, emails.verification_email(token))
            return _accepted(SIGNUP_ACCEPTED)

    # Already registered. The new password is ignored — otherwise anyone
    # could set the password of an account that isn't confirmed yet.
    if existing is not None and existing.is_active:
        if existing.email_verified_at is None:
            token = await account_tokens.issue(db, existing.id, account_tokens.VERIFY_EMAIL)
            await db.commit()
            if token:
                background.add_task(emails.send_quietly, email, emails.verification_email(token))
        else:
            background.add_task(emails.send_quietly, email, emails.account_exists_email())
    return _accepted(SIGNUP_ACCEPTED)


@router.post("/verify-email", response_model=DataResponse)
async def verify_email(data: TokenRequest, db: AsyncSession = Depends(get_db)):
    user_id = await account_tokens.consume(db, data.token, account_tokens.VERIFY_EMAIL)
    user = await _user_by_id(db, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=400, detail=INVALID_LINK)
    if user.email_verified_at is None:
        user.email_verified_at = _now()
        await audit.record(db, user.id, "user.email_verified", performed_by=user.email)
    await db.commit()
    return DataResponse(data={"verified": True, "email": user.email})


@router.post("/resend-verification", response_model=DataResponse, status_code=202)
async def resend_verification(data: EmailOnlyRequest, background: BackgroundTasks,
                              db: AsyncSession = Depends(get_db)):
    email = normalize_email(data.email)
    user = await _user_by_email(db, email)
    if user is not None and user.is_active and user.email_verified_at is None:
        token = await account_tokens.issue(db, user.id, account_tokens.VERIFY_EMAIL)
        await db.commit()
        if token:
            background.add_task(emails.send_quietly, email, emails.verification_email(token))
    return _accepted(RESEND_ACCEPTED)


# ---------------------------------------------------------------- sessions

@router.post("/login", response_model=DataResponse)
async def login(data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    email = normalize_email(data.email)
    if await lockout.locked_until(db, email):
        verify_password_dummy(data.password)
        raise HTTPException(status_code=429, detail={"code": "account_locked", "message": lockout.LOCKED_MESSAGE})

    user = await _user_by_email(db, email)
    if user is None:
        # Same hashing cost as a real check, so the response time doesn't
        # reveal whether the account exists.
        verify_password_dummy(data.password)
        ok = False
    else:
        ok = verify_password(data.password, user.hashed_password)

    if not ok:
        locked = await lockout.record_failure(db, email)
        if locked and user is not None:
            await audit.record(db, user.id, "user.locked_out", minutes=lockout.LOCK_DURATION.seconds // 60)
        await db.commit()
        if locked:
            raise HTTPException(status_code=429, detail={"code": "account_locked", "message": lockout.LOCKED_MESSAGE})
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)

    # The password is right, so saying why they can't get in reveals nothing
    # to a stranger.
    await lockout.clear(db, email)
    if not user.is_active:
        await db.commit()
        raise HTTPException(status_code=403, detail={
            "code": "account_disabled", "message": "This account has been disabled. Contact your administrator."})
    if user.email_verified_at is None:
        await db.commit()
        raise HTTPException(status_code=403, detail={
            "code": "email_not_verified",
            "message": "Confirm your email address first — check your inbox for the link, or request a new one."})

    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(data.password)  # bcrypt → argon2id
    user.last_login_at = _now()
    await db.commit()
    # The refresh token goes into an httpOnly cookie, never the response
    # body (app/session_cookies.py).
    return _session_response(response, user)


@router.post("/refresh", response_model=DataResponse, dependencies=[Depends(require_csrf)])
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    try:
        claims = decode_token(refresh_token_from(request))
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if claims.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="not a refresh token")

    # Re-read the user: a password change, deactivation or role change since
    # the token was issued must take effect now, not when it expires.
    user = await _user_by_id(db, claims["sub"])
    if (user is None or not user.is_active or user.email_verified_at is None
            or claims.get("tv", 0) != user.token_version):
        clear_session_cookies(response)
        raise HTTPException(status_code=401, detail="session has ended; sign in again")

    access_token = create_access_token(user.id, user.email, user.role)
    return DataResponse(
        data=AccessTokenResponse(access_token=access_token, expires_in_minutes=JWT_EXPIRY_MINUTES)
    )


@router.post("/logout", dependencies=[Depends(require_csrf)])
async def logout(response: Response):
    clear_session_cookies(response)
    return {"data": {"signed_out": True}}


@router.post("/logout-all", response_model=DataResponse)
async def logout_all(response: Response, current_user: CurrentUser = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    """Signs this account out on every device."""
    user = await _current_db_user(db, current_user)
    user.token_version += 1
    await audit.record(db, user.id, "user.signed_out_everywhere", performed_by=user.email)
    await db.commit()
    clear_session_cookies(response)
    return DataResponse(data={"signed_out": True})


async def _current_db_user(db: AsyncSession, current_user: CurrentUser) -> User:
    user = await _user_by_id(db, current_user.id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="user no longer exists")
    return user


@router.get("/me", response_model=DataResponse)
async def me(current_user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return DataResponse(data=UserResponse.model_validate(await _current_db_user(db, current_user)))


# ---------------------------------------------------------------- passwords

@router.post("/forgot-password", response_model=DataResponse, status_code=202)
async def forgot_password(data: EmailOnlyRequest, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    email = normalize_email(data.email)
    user = await _user_by_email(db, email)
    if user is not None and user.is_active:
        token = await account_tokens.issue(db, user.id, account_tokens.RESET_PASSWORD)
        if token:
            await audit.record(db, user.id, "user.password_reset_requested")
        await db.commit()
        if token:
            background.add_task(emails.send_quietly, email, emails.reset_email(token))
    return _accepted(RESET_ACCEPTED)


@router.post("/reset-password", response_model=DataResponse)
async def reset_password(data: ResetPasswordRequest, response: Response, background: BackgroundTasks,
                         db: AsyncSession = Depends(get_db)):
    # Checked before the link is used up, so a rejected password doesn't
    # cost the person their link.
    await _require_new_password_ok(data.new_password, "")

    user_id = await account_tokens.consume(db, data.token, account_tokens.RESET_PASSWORD)
    user = await _user_by_id(db, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail=INVALID_LINK)
    try:
        check_password_policy(data.new_password, user.email)
    except PasswordPolicyError as e:
        await db.rollback()  # keeps the link usable
        raise HTTPException(status_code=400, detail={"code": "weak_password", "message": str(e)})

    user.hashed_password = hash_password(data.new_password)
    user.password_changed_at = _now()
    user.token_version += 1
    # Getting the email proves they own the address.
    user.email_verified_at = user.email_verified_at or _now()
    await account_tokens.revoke_all(db, user.id, account_tokens.RESET_PASSWORD)
    await lockout.clear(db, user.email)
    await audit.record(db, user.id, "user.password_reset")
    await db.commit()
    clear_session_cookies(response)
    background.add_task(emails.send_quietly, user.email, emails.password_changed_email())
    return DataResponse(data={"message": "Your password has been reset. Sign in with your new password."})


@router.post("/change-password", response_model=DataResponse)
async def change_password(data: ChangePasswordRequest, response: Response, background: BackgroundTasks,
                          current_user: CurrentUser = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    user = await _current_db_user(db, current_user)
    if await lockout.locked_until(db, user.email):
        raise HTTPException(status_code=429, detail={"code": "account_locked", "message": lockout.LOCKED_MESSAGE})
    if not verify_password(data.current_password, user.hashed_password):
        # Counts like a failed login: a stolen, unattended session must not
        # become an unlimited password-guessing oracle.
        await lockout.record_failure(db, user.email)
        await db.commit()
        raise HTTPException(status_code=400, detail={"code": "wrong_password",
                                                     "message": "Your current password is incorrect."})
    if data.new_password == data.current_password:
        raise HTTPException(status_code=400, detail={"code": "weak_password",
                                                     "message": "The new password must be different."})
    await _require_new_password_ok(data.new_password, user.email)

    user.hashed_password = hash_password(data.new_password)
    user.password_changed_at = _now()
    user.token_version += 1  # signs out other devices
    await lockout.clear(db, user.email)
    await audit.record(db, user.id, "user.password_changed", performed_by=user.email)
    await db.commit()
    background.add_task(emails.send_quietly, user.email, emails.password_changed_email())
    # This device gets a fresh session carrying the new token_version.
    return _session_response(response, user)
