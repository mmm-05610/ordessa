"""Typed domain failures. Every refusal is a code, never prose (contracts.md).

The stable error family mirrors ``docs/design/command-templates/contracts.md``:
an unknown condition is never collapsed into "unsupported", and a list error is
never silently turned into an empty list. Callers branch on ``code``.
"""
from __future__ import annotations


class CommandTemplateError(RuntimeError):
    """Base for every refusal the command-templates domain makes."""

    code = "COMMAND_TEMPLATE_ERROR"

    def __init__(self, message: str, *, detail: "object | None" = None) -> None:
        super().__init__(f"{self.code}: {message}")
        self.message = message
        self.detail = detail


class InvalidIdentifierError(CommandTemplateError):
    """A template id or slug violates the restricted grammar (FR-01)."""

    code = "IDENTIFIER_INVALID"


class InvalidDocumentError(CommandTemplateError):
    """A body/schema document is not valid UTF-8, is oversize or malformed."""

    code = "DOCUMENT_INVALID"


class UnauthorizedTargetError(CommandTemplateError):
    """The authenticated principal may not reach the requested target (FR-11)."""

    code = "UNAUTHORIZED_TARGET"


class ContentMissingError(CommandTemplateError):
    """A referenced template or revision genuinely does not exist (FR-08)."""

    code = "CONTENT_MISSING"


class RevisionUnapprovedError(CommandTemplateError):
    """An enable/pin references a revision that has not been approved (FR-04)."""

    code = "REVISION_UNAPPROVED"


class ParameterInvalidError(CommandTemplateError):
    """A supplied argument fails its declared type/range/length check (FR-05)."""

    code = "PARAMETER_INVALID"


class UnknownParameterError(CommandTemplateError):
    """The body references a placeholder with no declaration, or vice versa."""

    code = "PARAMETER_UNKNOWN"


class UnresolvedParameterError(CommandTemplateError):
    """A ``project-ref`` could not be resolved through the authorized port."""

    code = "PROJECT_REF_UNRESOLVED"


class OutputLimitError(CommandTemplateError):
    """The rendered output exceeds the frozen byte bound (FR-05)."""

    code = "OUTPUT_LIMIT"


class NameConflictError(CommandTemplateError):
    """Two distinct ids collide on a display slug and cannot both be shown.

    The conflict is reported, never resolved by silently dropping one layer.
    """

    code = "NAME_CONFLICT"


class StalePreviewError(CommandTemplateError):
    """A preview/receipt no longer matches the current target or revision.

    The caller must refresh; a late result is never written into a new context.
    """

    code = "STALE_PREVIEW"


class CasConflictError(CommandTemplateError):
    """``expectedVersion`` does not match the stored entity version (FR-11)."""

    code = "CAS_CONFLICT"

    def __init__(self, message: str, *, current_version: "int | None" = None) -> None:
        super().__init__(message)
        self.current_version = current_version


class IdempotencyConflictError(CommandTemplateError):
    """The same ``operationKey`` was replayed with a different payload (G04)."""

    code = "IDEMPOTENCY_CONFLICT"


class ContributorGoneError(CommandTemplateError):
    """The provider backing a pending insert was unmounted (FR-12)."""

    code = "CONTRIBUTOR_GONE"


class NativeUnsupportedError(CommandTemplateError):
    """A brand adapter proves native projection is not equivalent (FR-10)."""

    code = "NATIVE_UNSUPPORTED"


class CapabilityUnknownError(CommandTemplateError):
    """Native capability is unproven for this pin — reported as unknown.

    Unknown is never upgraded to supported nor downgraded to a false "absent".
    """

    code = "CAPABILITY_UNKNOWN"


class ProjectionRefusedError(CommandTemplateError):
    """A native import/projection cannot be proven lossless, so it is refused."""

    code = "PROJECTION_REFUSED"
