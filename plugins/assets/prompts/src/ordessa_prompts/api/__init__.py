"""The Prompts public API: DTOs, content rules and the typed error family.

This package is deliberately pure: importing it performs no registration,
opens no database and reads no files (G01). The backend, the Server
plugin surface and the tests all validate against these same objects.
"""
from __future__ import annotations

from .dto import (
    BODY_MAX_BYTES,
    DESCRIPTION_MAX_CODEPOINTS,
    IMPORT_MAX_BYTES,
    KINDS,
    MAX_INSTRUCTIONS_PER_SELECTION,
    SCOPES,
    SNAPSHOT_MAX_TOTAL_BODY_BYTES,
    TITLE_MAX_CODEPOINTS,
    PromptRecord,
    PromptRef,
    PromptRevision,
    PromptScope,
    PromptSelection,
    PromptSnapshot,
    ResolvedPrompt,
    body_digest,
    validate_body_bytes,
    validate_description,
    validate_kind,
    validate_operation_key,
    validate_prompt_id,
    validate_title,
)
from .errors import (
    ArchivedSelectionError,
    DependencyUnavailableError,
    IdempotencyConflictError,
    InvalidContentError,
    InvalidRequestError,
    LimitExceededError,
    NativeSemanticsUnsupportedError,
    NotFoundError,
    PROMPT_ERROR_CODES,
    PromptError,
    RefKindMismatchError,
    RevisionConflictError,
    ScopeRefusedError,
)
from .ports import PromptProfileAuthorization

__all__ = [
    "BODY_MAX_BYTES", "DESCRIPTION_MAX_CODEPOINTS", "IMPORT_MAX_BYTES",
    "KINDS", "MAX_INSTRUCTIONS_PER_SELECTION", "SCOPES",
    "SNAPSHOT_MAX_TOTAL_BODY_BYTES", "TITLE_MAX_CODEPOINTS",
    "PromptRecord", "PromptRef", "PromptRevision", "PromptScope",
    "PromptSelection", "PromptSnapshot", "ResolvedPrompt",
    "body_digest", "validate_body_bytes", "validate_description",
    "validate_kind", "validate_operation_key", "validate_prompt_id", "validate_title",
    "PROMPT_ERROR_CODES", "PromptError", "NotFoundError", "RevisionConflictError",
    "InvalidContentError", "LimitExceededError", "RefKindMismatchError",
    "ScopeRefusedError", "ArchivedSelectionError", "DependencyUnavailableError",
    "NativeSemanticsUnsupportedError", "IdempotencyConflictError",
    "InvalidRequestError", "PromptProfileAuthorization",
]
