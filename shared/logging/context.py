import contextvars
from typing import Optional

_correlation_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)

class CorrelationContext:
    @staticmethod
    def get() -> Optional[str]:
        return _correlation_id_var.get()

    @staticmethod
    def set(correlation_id: str) -> contextvars.Token:
        return _correlation_id_var.set(correlation_id)

    @staticmethod
    def reset(token: contextvars.Token) -> None:
        _correlation_id_var.reset(token)
