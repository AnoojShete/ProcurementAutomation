"""The account emails: plain text first (every client can show it), with a
simple HTML version alongside.

Links put the token after "#", not "?": the part after "#" is never sent
to a server, so the token doesn't land in the gateway's access log or in
a Referer header. The page reads it in the browser and POSTs it.
"""
import html
import logging

from shared.mailer import load_settings, send_email

logger = logging.getLogger(__name__)

PRODUCT = "Procurement Platform"


def _link(path: str, token: str | None = None) -> str:
    base = load_settings().app_base_url
    return f"{base}{path}#token={token}" if token else f"{base}{path}"


def _html(heading: str, paragraphs: list[str], button: tuple[str, str] | None, footer: str) -> str:
    parts = [f'<h1 style="font-size:20px;margin:0 0 16px">{html.escape(heading)}</h1>']
    parts += [f'<p style="margin:0 0 14px">{html.escape(p)}</p>' for p in paragraphs]
    if button:
        label, url = button
        safe = html.escape(url, quote=True)
        parts.append(
            f'<p style="margin:22px 0"><a href="{safe}" style="background:#1d4ed8;color:#fff;'
            f'padding:10px 18px;border-radius:6px;text-decoration:none;display:inline-block">{html.escape(label)}</a></p>'
            f'<p style="margin:0 0 14px;font-size:13px;color:#555">If the button doesn\'t work, copy this address '
            f'into your browser:<br><a href="{safe}" style="color:#1d4ed8;word-break:break-all">{safe}</a></p>'
        )
    parts.append(f'<p style="margin:24px 0 0;font-size:12px;color:#777">{html.escape(footer)}</p>')
    return (
        '<!doctype html><html><body style="margin:0;background:#f4f5f7">'
        '<div style="max-width:520px;margin:0 auto;padding:32px 24px;font-family:Arial,Helvetica,sans-serif;'
        'font-size:15px;line-height:1.5;color:#111;background:#fff">'
        f'<p style="margin:0 0 24px;font-weight:bold;color:#1d4ed8">{PRODUCT}</p>{"".join(parts)}</div></body></html>'
    )


def _text(heading: str, paragraphs: list[str], button: tuple[str, str] | None, footer: str) -> str:
    lines = [heading, ""]
    for p in paragraphs:
        lines += [p, ""]
    if button:
        lines += [f"{button[0]}:", button[1], ""]
    lines += ["--", footer]
    return "\n".join(lines)


def _compose(subject, heading, paragraphs, button, footer):
    return subject, _text(heading, paragraphs, button, footer), _html(heading, paragraphs, button, footer)


def verification_email(token: str):
    return _compose(
        f"Confirm your email for {PRODUCT}",
        "Confirm your email address",
        ["Thanks for signing up. Confirm this is your email address to finish creating your account.",
         "This link works once and expires in 24 hours."],
        ("Confirm email address", _link("/verify-email", token)),
        "If you didn't create an account, ignore this email — nothing happens without the confirmation.",
    )


def account_exists_email():
    # Sent instead of a second verification email when someone signs up
    # with an address that already has an account. The sign-up page shows
    # the same message either way, so it can't be used to find accounts.
    return _compose(
        f"Sign-up attempt on {PRODUCT}",
        "You already have an account",
        ["Someone (hopefully you) tried to sign up with this email address, "
         "but it already has an account.",
         "If you've forgotten your password, you can reset it."],
        ("Reset your password", _link("/forgot-password")),
        "If this wasn't you, you can ignore this email. Your account has not changed.",
    )


def reset_email(token: str):
    return _compose(
        f"Reset your {PRODUCT} password",
        "Reset your password",
        ["We received a request to reset the password for this account.",
         "This link works once and expires in 30 minutes."],
        ("Choose a new password", _link("/reset-password", token)),
        "If you didn't ask for this, ignore this email — your password stays the same.",
    )


def password_changed_email():
    return _compose(
        f"Your {PRODUCT} password was changed",
        "Your password was changed",
        ["The password for your account was just changed, and other signed-in devices were signed out.",
         "If you did this, there's nothing else to do."],
        ("Reset your password", _link("/forgot-password")),
        "If you didn't change it, reset your password now and tell your administrator.",
    )


async def send_quietly(to: str, message) -> None:
    """For background tasks: a failed send is logged, never raised — the
    person can ask for a new link, and the API response must not depend on
    whether an email could be sent (or whether the account exists)."""
    subject, text_body, html_body = message
    try:
        await send_email(to, subject, text_body, html_body)
    except Exception as exc:
        # In the message itself: the JSON log formatter drops `extra` fields.
        logger.error(f"account email failed ({subject!r}): {type(exc).__name__}: {str(exc)[:300]}")
