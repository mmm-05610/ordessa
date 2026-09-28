"""Stable Harness domain error codes; no host or wire dependency."""

from enum import Enum


class ErrorCode(str, Enum):
    ADAPTER_MISSING = "adapter-missing"
    VERSION_UNVERIFIED = "version-unverified"
    CAPABILITY_UNSUPPORTED = "capability-unsupported"
    INVALID_FRAGMENT = "invalid-fragment"
    TARGET_CONFLICT = "target-conflict"
    STALE_PLAN = "stale-plan"
    AUTHORIZATION_REFUSED = "authorization-refused"
    ISOLATION_UNPROVEN = "isolation-unproven"
    BUSY = "busy"
    RESUME_UNAVAILABLE = "resume-unavailable"
    VERIFICATION_MISMATCH = "verification-mismatch"
    OPERATION_UNKNOWN = "operation-unknown"


class ContractError(ValueError):
    """Malformed public DTO. The ``code`` is suitable for wire-family mapping."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.INVALID_FRAGMENT):
        super().__init__(message)
        self.code = code
