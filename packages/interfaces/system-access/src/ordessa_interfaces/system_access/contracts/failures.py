"""Safe public failures; unknown external effects always require reconciliation."""
from dataclasses import dataclass
from typing import Literal

from .refs import identifier

Retry = Literal["never", "same_key_after_delay", "refresh_then_new_key", "reconcile_first"]
FAILURE_CODES = frozenset({
    "INVALID_ARGUMENT", "UNKNOWN_OPERATION", "SCHEMA_VERSION_UNSUPPORTED",
    "AUTHENTICATION_REQUIRED", "CAPABILITY_DENIED", "SCOPE_MISMATCH",
    "REVISION_CONFLICT", "SET_VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT",
    "TRUSTED_HUMAN_CONFIRMATION_REQUIRED", "CONFIRMATION_EXPIRED",
    "CONFIRMATION_ALREADY_CONSUMED", "CURSOR_RESET_REQUIRED", "PROVIDER_UNAVAILABLE",
    "RESOURCE_EXHAUSTED", "OUTCOME_INDETERMINATE", "INTERNAL_ERROR",
    "OUTCOME_UNKNOWN", "EFFECT_UNKNOWN", "RETRY_REQUIRES_RECONCILIATION",
})
RECONCILE_CODES = frozenset({"OUTCOME_INDETERMINATE", "OUTCOME_UNKNOWN", "EFFECT_UNKNOWN",
                           "RETRY_REQUIRES_RECONCILIATION"})


@dataclass(frozen=True)
class Failure:
    code: str
    message: str
    retry: Retry
    correlation_id: str
    retry_after_ms: int | None = None

    def __post_init__(self):
        identifier(self.code)
        if self.code not in FAILURE_CODES:
            raise ValueError("unknown_failure_code")
        identifier(self.correlation_id)
        if type(self.message) is not str or len(self.message) > 2048:
            raise ValueError("invalid_safe_failure_message")
        if self.retry not in {"never", "same_key_after_delay", "refresh_then_new_key", "reconcile_first"}:
            raise ValueError("invalid_retry")
        if self.code in RECONCILE_CODES and self.retry != "reconcile_first":
            raise ValueError("unknown_effect_requires_reconciliation")
        if self.retry_after_ms is not None and (type(self.retry_after_ms) is not int or not 0 <= self.retry_after_ms <= 86400000):
            raise ValueError("invalid_retry_delay")
