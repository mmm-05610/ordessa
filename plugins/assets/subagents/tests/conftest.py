"""Shared fixtures and builders for this domain's tests."""
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[2]

for _root in (
    PLUGIN_ROOT / "src",
    REPO_ROOT / "packages" / "pacthold" / "src",
):
    if _root.is_dir() and str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import pytest  # noqa: E402

from ordessa_assets_subagents import dto  # noqa: E402
from ordessa_assets_subagents.digest import (
    bytes_digest,
    canonical_json,
    revision_digest,
)  # noqa: E402
from ordessa_assets_subagents.store import DefinitionStore  # noqa: E402
from ordessa_assets_subagents.service import DefinitionService  # noqa: E402

PRINCIPAL = "u:tester"
OTHER_PRINCIPAL = "u:other"
SERVER_SCOPE = "server:local"
APPROVED_AT = "2026-09-28T10:00:00+00:00"


class FakeAuthority:
    """The service's auth context: who a principal is and what it may declare."""

    def __init__(self, *, principals=(PRINCIPAL, OTHER_PRINCIPAL),
                 ceiling=("read-only",)) -> None:
        self.principals = set(principals)
        self.ceiling = frozenset(ceiling)

    def verify_principal(self, principal: str, *, server_scope: str) -> bool:
        return principal in self.principals

    def permission_ceiling(self, principal: str, server_scope: str) -> frozenset[str]:
        return self.ceiling if principal in self.principals else frozenset()


@pytest.fixture
def store(tmp_path: Path) -> DefinitionStore:
    return DefinitionStore(tmp_path / "store-root")


@pytest.fixture
def authority() -> FakeAuthority:
    return FakeAuthority()


@pytest.fixture
def service(store: DefinitionStore, authority: FakeAuthority) -> DefinitionService:
    return DefinitionService(store, authority=authority)


@pytest.fixture
def import_root(tmp_path: Path) -> Path:
    root = tmp_path / "approved-imports"
    root.mkdir()
    return root


@pytest.fixture
def definition(service: DefinitionService) -> dto.AgentDefinition:
    return service.create_definition(
        PRINCIPAL, server_scope=SERVER_SCOPE, slug="code-reviewer",
        display_name="Code reviewer", description="Read-only code reviewer.",
        origin_scope="public", origin_owner="local", operation_key="u:op-create",
    )


def approval(**overrides) -> dto.SourceApproval:
    fields = {
        "origin": "user-upload",
        "origin_ref": f"upload/{PRINCIPAL}",
        "content_digest": "sha256:" + "a" * 64,
        "approved_by_principal": PRINCIPAL,
        "approved_at": APPROVED_AT,
    }
    fields.update(overrides)
    return dto.SourceApproval(**fields)


def make_revision(definition_id: str, revision: int = 1, **overrides) -> dto.DefinitionRevision:
    fields: dict = {
        "definition_id": definition_id,
        "revision": revision,
        "content_digest": "sha256:" + "0" * 64,
        "role_body": overrides.pop("role_body", "You review code read-only and cite findings."),
        "declared_model_ref": overrides.pop("declared_model_ref", None),
        "tool_refs": overrides.pop("tool_refs", ()),
        "mcp_refs": overrides.pop("mcp_refs", ()),
        "skill_refs": overrides.pop("skill_refs", ()),
        "requested_permission": overrides.pop("requested_permission", None),
        "isolation": overrides.pop("isolation", {}),
        "limits": overrides.pop("limits", {}),
        "source": overrides.pop("source", approval()),
        "retained_native_fields": overrides.pop("retained_native_fields", {}),
    }
    fields.update(overrides)
    fields["content_digest"] = "sha256:" + "0" * 64
    source = fields["source"]
    if isinstance(source, dto.SourceApproval):
        # A hand-written revision is approved over its own body (see
        # DefinitionService._check_source_is_witnessed).
        fields["source"] = dto.SourceApproval(
            **{**vars(source),
               "content_digest": bytes_digest(fields["role_body"].encode("utf-8"))}
        )
    provisional = dto.DefinitionRevision(**fields)
    return dto.DefinitionRevision(
        **{**fields, "content_digest": revision_digest(provisional)}
    )


def publish(service: DefinitionService, definition: dto.AgentDefinition, revision: int = 1,
            *, operation_key: str | None = None, **overrides) -> dto.DefinitionRevision:
    return service.save_revision(
        PRINCIPAL,
        make_revision(definition.definition_id, revision, **overrides),
        server_scope=definition.server_scope,
        operation_key=operation_key or f"u:publish-{definition.slug}-{revision}",
        expected_row_version=1 if revision == 1 else revision,
    )


def revision_mapping(**overrides) -> dict:
    """A stored-shaped revision mapping; unknown keys arrive as native extras."""
    base: dict = {
        "definition_id": "def_shape000000000000000000",
        "revision": 1,
        "content_digest": "sha256:" + "0" * 64,
        "role_body": "Review read-only.",
        "declared_model_ref": None,
        "tool_refs": (), "mcp_refs": (), "skill_refs": (),
        "requested_permission": None,
        "isolation": {}, "limits": {},
        "source": approval(),
        "retained_native_fields": {},
    }
    extras = {key: value for key, value in overrides.items() if key not in base}
    base.update({key: value for key, value in overrides.items() if key in base})
    body, source = base["role_body"], base["source"]
    if isinstance(source, dto.SourceApproval) and isinstance(body, str):
        try:
            approved = bytes_digest(body.encode("utf-8"))
        except UnicodeEncodeError:
            approved = source.content_digest
        base["source"] = dto.SourceApproval(**{**vars(source), "content_digest": approved})
    for key in ("declared_model_ref", "tool_refs", "mcp_refs", "skill_refs"):
        base[key] = _canonical_refs(base[key])
    retained = _safe_retained(dict(base["retained_native_fields"] or {}), extras)
    provisional = dto.DefinitionRevision(**{**base, "retained_native_fields": retained})
    try:
        content = revision_digest(provisional)
    except UnicodeEncodeError:
        content = "sha256:" + "0" * 64
    return {**base, **extras, "retained_native_fields": retained, "content_digest": content}


def _canonical_refs(value):
    """A reference mapping without a revision means an unpinned declaration."""
    if value is None or isinstance(value, (str, int, dto.ModelRef, dto.ToolRef,
                                           dto.McpRef, dto.SkillRef)):
        return value
    if isinstance(value, dict):
        return {**value, "revision": value.get("revision")} if "owner_id" in value else value
    if isinstance(value, (list, tuple)):
        return [_canonical_refs(entry) for entry in value]
    return value


def _safe_retained(retained: dict, extras: dict) -> dict:
    """Keep the digest honest when an extra fragment cannot be canonicalised."""
    merged = {**retained, **extras}
    try:
        canonical_json(merged)
    except (TypeError, ValueError):
        return retained
    return merged


def document(name: str = "code-reviewer", description: str = "Reviews code read-only.",
             body: str = "Cite file and line for every finding.",
             extra: str = "", tools: str | None = None) -> str:
    front = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if tools:
        front.append(f"tools: {tools}")
    if extra:
        front.append(extra)
    front += ["---", body, ""]
    return "\n".join(front)
