"""Operation result layering for in-process system-access commands.

Four terminal layers are defined, and none of them is an engineering acceptance
claim (that decision belongs to a different owner):

``accepted``
    The operation was received and dispatched; its outcome is not yet observed.
    Nothing in the current in-process slice returns it — the model carries it so
    a later asynchronous transport can, without inventing a new status.
``completed``
    The requested execution/observation was actually achieved.
``refused``
    The operation was refused before any effect happened.
``unknown``
    An effect may have happened and its outcome is not observed. Unknown
    outcomes are never retried implicitly; they require explicit inspection.

A pre-effect refusal is raised as :class:`InterfaceRefusal`; an unobserved
effect is raised as :class:`InterfaceUnknown`. Both carry the same safe
``code``/``message``/``retryable`` triple the CLI envelope renders, so a caller
never has to parse an exception type out of a message.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STATUS_ACCEPTED = "accepted"
STATUS_COMPLETED = "completed"
STATUS_REFUSED = "refused"
STATUS_UNKNOWN = "unknown"
STATUSES = frozenset({STATUS_ACCEPTED, STATUS_COMPLETED, STATUS_REFUSED, STATUS_UNKNOWN})

#: Stable interface error codes. They name the interface failure, never a
#: provider or execution internal, and never an engineering decision.
INVALID_ARGUMENT = "ENVIRONMENTS_INVALID_ARGUMENT"
NO_COMMAND = "ENVIRONMENTS_NO_COMMAND"
INVALID_REFERENCE = "ENVIRONMENTS_INVALID_REFERENCE"
UNKNOWN_RESOURCE = "ENVIRONMENTS_UNKNOWN_RESOURCE"
INVALID_ALIAS = "ENVIRONMENTS_INVALID_ALIAS"
ALIAS_CONFLICT = "ENVIRONMENTS_ALIAS_CONFLICT"
ALIAS_STORE_INVALID = "ENVIRONMENTS_ALIAS_STORE_INVALID"
CONFLICT = "ENVIRONMENTS_CONFLICT"
REFUSED = "ENVIRONMENTS_REFUSED"
LOCAL_LIFECYCLE_UNSUPPORTED = "ENVIRONMENTS_LOCAL_LIFECYCLE_UNSUPPORTED"
PROVIDER_UNAVAILABLE = "ENVIRONMENTS_PROVIDER_UNAVAILABLE"
BACKEND_NOT_FOUND = "ENVIRONMENTS_BACKEND_NOT_FOUND"
GUARANTEE_UNMET = "ENVIRONMENTS_GUARANTEE_UNMET"
START_FAILED = "ENVIRONMENTS_START_FAILED"
ENVIRONMENT_FAILURE = "ENVIRONMENTS_ENVIRONMENT_FAILURE"
IO_ERROR = "ENVIRONMENTS_IO_ERROR"
UNAVAILABLE = "ENVIRONMENTS_UNAVAILABLE"
OPERATION_UNKNOWN = "ENVIRONMENTS_OPERATION_UNKNOWN"
IO_UNKNOWN = "ENVIRONMENTS_IO_UNKNOWN"
OBSERVATION_TIMEOUT = "ENVIRONMENTS_OBSERVATION_TIMEOUT"
UNKNOWN_COMMAND = "ENVIRONMENTS_UNKNOWN_COMMAND"
STATE_REQUIRED = "ENVIRONMENTS_STATE_REQUIRED"


@dataclass(frozen=True)
class OperationError:
    """The safe error triple a refusal/unknown outcome carries."""

    code: str
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("operation error requires a code")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("operation error requires a message")
        if type(self.retryable) is not bool:
            raise ValueError("operation error retryable must be an explicit boolean")

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True)
class OperationResult:
    """One layered operation outcome.

    ``refused`` and ``unknown`` must carry an error; ``accepted`` and
    ``completed`` must not. The data payload is already a safe projection, not a
    provider object.
    """

    status: str
    data: Any = None
    error: OperationError | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown operation status {self.status!r}")
        if self.status in (STATUS_REFUSED, STATUS_UNKNOWN):
            if not isinstance(self.error, OperationError):
                raise ValueError(f"{self.status} result requires an OperationError")
        elif self.error is not None:
            raise ValueError(f"{self.status} result must not carry an error")

    @property
    def is_completed(self) -> bool:
        return self.status == STATUS_COMPLETED

    @property
    def is_refused(self) -> bool:
        return self.status == STATUS_REFUSED

    @property
    def is_unknown(self) -> bool:
        return self.status == STATUS_UNKNOWN

    @classmethod
    def accepted(cls, data: Any = None) -> "OperationResult":
        return cls(STATUS_ACCEPTED, data)

    @classmethod
    def completed(cls, data: Any = None) -> "OperationResult":
        return cls(STATUS_COMPLETED, data)

    @classmethod
    def refused(cls, code: str, message: str, data: Any = None) -> "OperationResult":
        return cls(STATUS_REFUSED, data, OperationError(code, message, False))

    @classmethod
    def unknown(cls, code: str, message: str, data: Any = None) -> "OperationResult":
        return cls(STATUS_UNKNOWN, data, OperationError(code, message, False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data": self.data,
            "error": self.error.to_dict() if self.error is not None else None,
        }


class InterfaceError(Exception):
    """Base class for a classified interface failure raised before rendering."""

    def __init__(self, code: str, message: str, *, retryable: bool = False, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = bool(retryable)
        self.data = data

    @property
    def status(self) -> str:
        raise NotImplementedError

    def error(self) -> OperationError:
        return OperationError(self.code, self.message, self.retryable)

    def result(self) -> OperationResult:
        return OperationResult(self.status, self.data, self.error())


class InterfaceRefusal(InterfaceError):
    """A refusal decided before any effect: safe to report and safe to repeat."""

    @property
    def status(self) -> str:
        return STATUS_REFUSED


class InterfaceUnknown(InterfaceError):
    """An effect whose outcome was not observed: never retried implicitly."""

    @property
    def status(self) -> str:
        return STATUS_UNKNOWN


__all__ = [
    "STATUS_ACCEPTED",
    "STATUS_COMPLETED",
    "STATUS_REFUSED",
    "STATUS_UNKNOWN",
    "STATUSES",
    "INVALID_ARGUMENT",
    "NO_COMMAND",
    "INVALID_REFERENCE",
    "UNKNOWN_RESOURCE",
    "INVALID_ALIAS",
    "ALIAS_CONFLICT",
    "ALIAS_STORE_INVALID",
    "CONFLICT",
    "REFUSED",
    "LOCAL_LIFECYCLE_UNSUPPORTED",
    "PROVIDER_UNAVAILABLE",
    "BACKEND_NOT_FOUND",
    "GUARANTEE_UNMET",
    "START_FAILED",
    "ENVIRONMENT_FAILURE",
    "IO_ERROR",
    "UNAVAILABLE",
    "OPERATION_UNKNOWN",
    "IO_UNKNOWN",
    "OBSERVATION_TIMEOUT",
    "UNKNOWN_COMMAND",
    "STATE_REQUIRED",
    "OperationError",
    "OperationResult",
    "InterfaceError",
    "InterfaceRefusal",
    "InterfaceUnknown",
]
