import logging
import json
import re
from datetime import datetime, timezone
from shared.logging.context import CorrelationContext

# Regex patterns for sensitive redactions
_EMAIL_ACTION_PATH = re.compile(r'(/(?:api/)?email-action/)[^/\s?&#]+')
_QUERY_SENSITIVE = re.compile(r'([?&](?:token|key|secret|password|api_key)=)[^&\s]+', re.IGNORECASE)
_BEARER_TOKEN = re.compile(r'(Bearer\s+)[A-Za-z0-9\-_.~+/]+=*', re.IGNORECASE)
_JSON_SENSITIVE = re.compile(
    r'("(?:password|hashed_password|token|access_token|refresh_token|api_key|secret|client_secret)"\s*:\s*")[^"]+(")',
    re.IGNORECASE
)
_KEY_VALUE_SENSITIVE = re.compile(
    r'(\b(?:password|current_password|new_password|client_secret|api_key|token)\s*=\s*)[^\s,;&]+',
    re.IGNORECASE
)


def redact_sensitive_patterns(text: str) -> str:
    if not text:
        return text

    # Redact path segment after /email-action/
    text = _EMAIL_ACTION_PATH.sub(r'\1[REDACTED]', text)

    # Redact sensitive query parameters
    text = _QUERY_SENSITIVE.sub(r'\1[REDACTED]', text)

    # Redact Authorization: Bearer <token>
    text = _BEARER_TOKEN.sub(r'\1[REDACTED]', text)

    # Redact sensitive JSON attributes
    text = _JSON_SENSITIVE.sub(r'\1[REDACTED]\2', text)

    # Redact sensitive key=value pairs
    text = _KEY_VALUE_SENSITIVE.sub(r'\1[REDACTED]', text)

    return text


def escape_newlines(text: str) -> str:
    """Escape CR and LF characters to prevent log forging and injection."""
    if not text:
        return text
    return text.replace("\r", "\\r").replace("\n", "\\n")


class JSONFormatter(logging.Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        msg = redact_sensitive_patterns(record.getMessage())
        log_data = {
            "correlation_id": CorrelationContext.get() or "",
            "service": self.service_name,
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": escape_newlines(msg),
        }
        if record.exc_info:
            exc_str = self.formatException(record.exc_info)
            log_data["exception"] = escape_newlines(redact_sensitive_patterns(exc_str))
        return json.dumps(log_data)
