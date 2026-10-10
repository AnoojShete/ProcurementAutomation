import logging
import json
import re
from datetime import datetime, timezone
from shared.logging.context import CorrelationContext

def redact_sensitive_patterns(text: str) -> str:
    if not text:
        return text
    # Redact any path segment after /email-action/
    text = re.sub(r'(/(?:api/)?email-action/)[^/\s?&#]+', r'\1[REDACTED]', text)
    # Redact any query parameter named token
    text = re.sub(r'([?&]token=)[^&\s]+', r'\1[REDACTED]', text)
    return text

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
            "message": msg,
        }
        if record.exc_info:
            exc_str = self.formatException(record.exc_info)
            log_data["exception"] = redact_sensitive_patterns(exc_str)
        return json.dumps(log_data)

