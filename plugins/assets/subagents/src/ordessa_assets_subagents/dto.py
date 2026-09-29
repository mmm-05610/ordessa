"""The domain's pure DTOs; field names are the data model's (data-model.md).

A resource reference is an owner/version *declaration*, never an executable
path and never a credential; every value is validated in `decoder.py` before
it can reach the store.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any, Mapping

ORIGIN_SCOPES: tuple[str, ...] = ("public", "project", "profile")
SOURCE_ORIGINS: tuple[str, ...] = ("user-upload", "git-revision")


def new_definition_id() -> str:
    """Opaque and never derived from a name or slug."""
    return "def_" + secrets.token_hex(12)


def new_preview_id() -> str:
    return "imp_" + secrets.token_hex(12)


@dataclass(frozen=True)
class ModelRef:
    owner_id: str
    revision: str | None = None


@dataclass(frozen=True)
class ToolRef:
    owner_id: str
    revision: str | None = None


@dataclass(frozen=True)
class McpRef:
    owner_id: str
    revision: str | None = None


@dataclass(frozen=True)
class SkillRef:
    owner_id: str
    revision: str | None = None


@dataclass(frozen=True)
class SourceApproval:
    """Where one revision's content came from and who approved that digest."""

    origin: str
    origin_ref: str
    content_digest: str
    approved_by_principal: str
    approved_at: str


@dataclass(frozen=True)
class DefinitionRevision:
    definition_id: str
    revision: int
    content_digest: str
    role_body: str
    declared_model_ref: ModelRef | None = None
    tool_refs: tuple[ToolRef, ...] = ()
    mcp_refs: tuple[McpRef, ...] = ()
    skill_refs: tuple[SkillRef, ...] = ()
    requested_permission: str | None = None
    isolation: Mapping[str, Any] = field(default_factory=dict)
    limits: Mapping[str, Any] = field(default_factory=dict)
    source: SourceApproval | None = None
    retained_native_fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentDefinition:
    server_scope: str
    definition_id: str
    slug: str
    display_name: str
    description: str
    origin_scope: str
    origin_owner: str
    latest_revision: int = 0
    archived: bool = False
    row_version: int = 0


@dataclass(frozen=True)
class ImportFile:
    """One candidate file in a preview: a digest, a format verdict, nothing more."""

    relative_path: str
    size_bytes: int
    content_digest: str
    diagnostics: tuple[str, ...] = ()
    selectable: bool = True
    declared_slug: str | None = None
    declared_description: str | None = None


@dataclass(frozen=True)
class ImportPreview:
    """A read-only verdict over a caller-selected source; preview writes nothing."""

    preview_id: str
    source_name: str
    source_path: str
    source_digest: str
    files: tuple[ImportFile, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportPlan:
    """What one approval step would persist, computed but never written."""

    preview_id: str
    definition: AgentDefinition
    revision: DefinitionRevision
