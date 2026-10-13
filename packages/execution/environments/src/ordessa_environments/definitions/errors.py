"""Typed environment failures.

Every failure carries a stable ``code`` so callers branch on the code and never
on message text. Nothing here retries: an environment refusal is a decision, not
a transient transport error.
"""
from __future__ import annotations


class EnvironmentFailure(Exception):
    """Base typed failure for the environment contract."""

    code = "ENVIRONMENT_FAILURE"

    def __init__(self, detail: str):
        super().__init__(f"{self.code}: {detail}")
        self.detail = detail


class EnvironmentRefused(EnvironmentFailure):
    """The provider or handle refused the request (unsupported, stale, or absent)."""

    code = "ENVIRONMENT_REFUSED"


class EnvironmentGuaranteeUnmet(EnvironmentRefused):
    """A referenced capability/guarantee is not actually provided by the handle.

    This is the "configuration references plus actual guarantee checks" rule: a
    reference that asks for something the handle does not really provide must be
    refused here, never silently downgraded.
    """

    code = "ENVIRONMENT_GUARANTEE_UNMET"


class ProcessStartFailed(EnvironmentFailure):
    """The real spawn failed. No handle is handed back and no process is owned."""

    code = "PROCESS_START_FAILED"


class ProcessHandleStale(EnvironmentRefused):
    """The handle was released, superseded, or belongs to another owner view."""

    code = "PROCESS_HANDLE_STALE"


class BackendNotFound(EnvironmentRefused):
    code = "ENVIRONMENT_BACKEND_NOT_FOUND"


class EnvironmentOperationUnknown(EnvironmentFailure):
    """Effect may have happened. Evidence enables explicit reconciliation, not retry."""

    code = "ENVIRONMENT_OPERATION_UNKNOWN"

    def __init__(self, detail: str, *, identity: str, backend_id: str | None = None):
        super().__init__(detail)
        self.identity = identity
        self.backend_id = backend_id


class ProcessWaitTimeout(EnvironmentFailure):
    code = "PROCESS_WAIT_TIMEOUT"


__all__ = [
    "EnvironmentFailure",
    "EnvironmentRefused",
    "EnvironmentGuaranteeUnmet",
    "ProcessStartFailed",
    "ProcessHandleStale",
    "BackendNotFound",
    "EnvironmentOperationUnknown",
    "ProcessWaitTimeout",
]
