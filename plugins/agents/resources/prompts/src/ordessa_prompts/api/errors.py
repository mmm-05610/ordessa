"""Typed domain failures of the Prompts boundary.

Every refusal is one of these with a stable machine code from
`contracts.md` (NOT_FOUND … NATIVE_SEMANTICS_UNSUPPORTED, plus the
idempotency-replay refusal). Messages never carry prompt body text: the
body is user content that must not reach logs or error envelopes
(G05 / FR14). A message may carry IDs, revision numbers, digests and
byte counts only.
"""
from __future__ import annotations

from typing import Any, Mapping

#: The error family the public contract freezes. Anything the service
#: refuses must be one of these codes; the Server wire maps them into its
#: standard error envelope at the registration seam.
PROMPT_ERROR_CODES = (
    "NOT_FOUND",
    "REVISION_CONFLICT",
    "INVALID_CONTENT",
    "LIMIT_EXCEEDED",
    "REF_KIND_MISMATCH",
    "SCOPE_REFUSED",
    "ARCHIVED_SELECTION",
    "DEPENDENCY_UNAVAILABLE",
    "NATIVE_SEMANTICS_UNSUPPORTED",
    "IDEMPOTENCY_CONFLICT",
    "INVALID_REQUEST",
)


class PromptError(Exception):
    """Base of every Prompts refusal. Carries a code and a body-free message."""

    def __init__(self, code: str, message: str,
                 details: "Mapping[str, Any] | None" = None) -> None:
        if code not in PROMPT_ERROR_CODES:
            raise ValueError(f"unknown Prompts error code: {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details: Mapping[str, Any] = dict(details or {})


class NotFoundError(PromptError):
    def __init__(self, message: str = "no such prompt in this Server's content library",
                 **details: Any) -> None:
        super().__init__("NOT_FOUND", message, details)


class RevisionConflictError(PromptError):
    """A compare-and-set saw a different version than the caller expected.

    `current` carries the live metadataVersion/latestRevision so a client
    can rebase; it never carries body text.
    """

    def __init__(self, message: str = "the prompt changed since the expected version",
                 **details: Any) -> None:
        super().__init__("REVISION_CONFLICT", message, details)


class InvalidContentError(PromptError):
    """Title/body/kind/scope/encoding rules were violated (pre-apply check)."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__("INVALID_CONTENT", message, details)


class LimitExceededError(PromptError):
    """A capacity bound (body size, count, snapshot total) was exceeded.

    Refused *before* application; nothing is silently truncated.
    """

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__("LIMIT_EXCEEDED", message, details)


class RefKindMismatchError(PromptError):
    """A PromptRef points at a record whose kind differs from the slot."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__("REF_KIND_MISMATCH", message, details)


class ScopeRefusedError(PromptError):
    """The request addresses a profile scope the caller is not entitled to."""

    def __init__(self, message: str = "the requested scope is not authorised for this caller",
                 **details: Any) -> None:
        super().__init__("SCOPE_REFUSED", message, details)


class ArchivedSelectionError(PromptError):
    """An archived record was used for a mutation (editing) request."""

    def __init__(self, message: str = "archived content is read-only; restore it first",
                 **details: Any) -> None:
        super().__init__("ARCHIVED_SELECTION", message, details)


class DependencyUnavailableError(PromptError):
    """A cooperating domain (Profile authorisation port) is absent.

    Public-library work is never affected; only the dependent operation
    refuses (G08).
    """

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__("DEPENDENCY_UNAVAILABLE", message, details)


class NativeSemanticsUnsupportedError(PromptError):
    """A native target could not accept the requested semantics intact.

    Reserved for the Harness-facing path (T07+); declared here so the
    whole family is frozen in the pure API (G01).
    """

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__("NATIVE_SEMANTICS_UNSUPPORTED", message, details)


class IdempotencyConflictError(PromptError):
    """The same operationKey was replayed with a different payload digest."""

    def __init__(self, message: str = ("this operationKey was already used with a "
                                       "different request payload"), **details: Any) -> None:
        super().__init__("IDEMPOTENCY_CONFLICT", message, details)


class InvalidRequestError(PromptError):
    """A request was not shaped per the published method contract."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__("INVALID_REQUEST", message, details)
