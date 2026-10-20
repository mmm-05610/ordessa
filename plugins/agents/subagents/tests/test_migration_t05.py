"""T05 — the dry-run import of provably-pure legacy rows (FR13/FR14, gate G10).

Everything here reads *row shapes*: the legacy tables are reproduced as
synthetic mappings under `tmp_path` and no real database, data root or user
HOME is ever opened. The gate has two halves, and this file drives both: the
positive half (a dry run and a restore keep bytes and IDs identical) and the
negative half (the old authorization edges and dispatcher logic cannot be
carried into this domain — not by a decision, and not by a code path either).
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from conftest import APPROVED_AT, PRINCIPAL, SERVER_SCOPE, FakeAuthority, document

from ordessa_assets_subagents import digest, dto, errors, migration
from ordessa_assets_subagents.service import DefinitionService
from ordessa_assets_subagents.store import DefinitionStore

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PY = PLUGIN_ROOT / "src" / "ordessa_assets_subagents" / "migration.py"
DIGEST_RE = digest.DIGEST_RE

CEILING = "read-only"
TOO_HIGH_CEILING = "shell"
GIT_PIN = "0f1e2d3c4b5a69788796a5b4c3d2e1f001234567"

#: The legacy dispatcher's own vocabulary: this domain must never carry it.
BANNED_LEGACY_SYMBOLS = (
    "run_subagent", "list_subagents", "resolve_roster", "check_cycle",
    "grant_edges", "has_delegation", "tool_definitions",
    "validate_run_arguments", "inline_available", "agentbox-subagents",
    "subagent-bridge", "DelegationError",
)
#: Nothing in this module may read a database or a legacy module.
BANNED_DB_MODULES = (
    "pacthold", "ordessa_server_compat", "sqlite3", "sqlalchemy",
    "subprocess", "socket", "http", "urllib", "requests",
)
BANNED_DB_ATTRIBUTES = (
    "connect", "execute", "executescript", "executemany", "cursor",
    "fetchall", "fetchone", "commit", "rollback", "expanduser",
)


# -- synthetic legacy fixtures ----------------------------------------------


def digest_of(body: str) -> str:
    """What the legacy publish path recorded: a digest of the raw bytes."""
    return digest.bytes_digest(body.encode("utf-8"))


_MISSING = object()


def asset_row(**overrides) -> dict[str, Any]:
    """One `server_assets` row: id, kind, name, digest, revision, and its body.

    `content=None` means the caller could not supply the digest-referenced
    body; a `digest=None` means the row recorded none.
    """
    body = overrides.pop("content", _MISSING)
    if body is _MISSING:
        body = document(name="code-reviewer", description="Reviews code read-only.")
    recorded = overrides.pop("digest", _MISSING)
    if recorded is _MISSING:
        recorded = digest_of(
            body if isinstance(body, str)
            else document(name="code-reviewer", description="Reviews code read-only.")
        )
    row: dict[str, Any] = {
        "table": "server_assets",
        "id": "asset-1",
        "kind": "subagent",
        "name": "Code Reviewer",
        "description": "Reviews code read-only.",
        "latest_revision": 3,
        "revision": 3,
        "digest": recorded,
        "source": "user-upload",
        "content": body,
    }
    row.update(overrides)
    return row


def grant_row(**overrides) -> dict[str, Any]:
    """One row of the old delegation grant table: an authorization edge."""
    row = {
        "table": "server_subagent_grants",
        "parent_profile_id": "profile-a",
        "child_profile_id": "profile-b",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def profile_row(**overrides) -> dict[str, Any]:
    """One `server_profiles` row shown as the old roster projection showed it."""
    row = {
        "table": "server_profiles",
        "id": "profile-b",
        "name": "Reviewer Role",
        "harness_type": "claude",
        "config_revision": 4,
        "config_object_digest": digest_of('{"harness":"claude"}'),
        "credential_id": None,
    }
    row.update(overrides)
    return row


def binding_row(**overrides) -> dict[str, Any]:
    """One `server_profile_assets` binding: a pinned revision plus an enabled flag."""
    row = {
        "table": "server_profile_assets",
        "profile_id": "profile-a",
        "asset_id": "asset-1",
        "revision": 3,
        "enabled": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def tool_schema_row(**overrides) -> dict[str, Any]:
    row = {
        "table": "synthesized_tools", "function_name": "run_" + "subagent",
        "input_schema": {"type": "object"}, "description": "runs a delegate",
    }
    row.update(overrides)
    return row


def roster_row(**overrides) -> dict[str, Any]:
    row = {
        "table": "synthesized_tools",
        "roster": [{"profileId": "profile-b", "name": "Reviewer Role"}],
        "availability": {"profile-b": None},
    }
    row.update(overrides)
    return row


def policy_row(**overrides) -> dict[str, Any]:
    row = {
        "table": "delegation_policy", "profile_id": "profile-a",
        "max_turns": 4, "timeout_seconds": 600, "cycle_chain": ["a", "b"],
    }
    row.update(overrides)
    return row


def history_row(**overrides) -> dict[str, Any]:
    row = {
        "table": "server_turns", "id": "turn-9", "parent_turn_id": "turn-1",
        "run_state": "completed",
    }
    row.update(overrides)
    return row


def mcp_entry_row(**overrides) -> dict[str, Any]:
    row = {
        "table": "composition", "id": "mcp-1",
        "mcp_server_name": "agentbox-" + "subagents",
    }
    row.update(overrides)
    return row


def skill_row(**overrides) -> dict[str, Any]:
    body = document(name="deployer", description="Deploys the build.")
    row = {
        "table": "server_assets", "id": "asset-skill", "kind": "skill",
        "name": "Deployer", "description": "Deploys the build.",
        "latest_revision": 1, "revision": 1, "digest": digest_of(body),
        "content": body,
    }
    row.update(overrides)
    return row


def _role_row(key: str, slug: str, name: str, revision: int) -> dict[str, Any]:
    body = document(
        name=slug,
        description=f"{name} role body, reviewed and approved.",
        body=f"You are the {name}. Cite file and line for every finding.",
    )
    return asset_row(
        legacy_key=key, id=key.rsplit(":", 1)[-1], name=name,
        latest_revision=revision, revision=revision, content=body,
    )


def _aggregate_row(key: str) -> dict[str, Any]:
    """A legacy *projection*: a role body bundled with a delegation grant."""
    body = document(name="aggregated", description="A projection, not a definition.")
    return asset_row(
        legacy_key=key, name="Aggregated Row", latest_revision=5, revision=5,
        content=body, parent_profile_id="profile-a",
    )


def _credential_row(key: str) -> dict[str, Any]:
    body = document(
        name="leaky", description="Carries a credential in its body.",
        body="api_key = " + "sk-" + "supersecretvalue123456",
    )
    return asset_row(legacy_key=key, name="Leaky Row", content=body)


def _include_row(key: str) -> dict[str, Any]:
    body = document(
        name="reaching", description="Includes another file.",
        body="Read ![[other-role.md]] before you start.",
    )
    return asset_row(legacy_key=key, name="Reaching Row", content=body)


def git_row(key: str) -> dict[str, Any]:
    """A catalogue row whose source is a pinned git revision (matrix M-07)."""
    body = document(name="git-reviewer", description="Pinned in a git revision.")
    return asset_row(
        legacy_key=f"{key}@{GIT_PIN}", name="Git Reviewer",
        latest_revision=1, revision=1, source="git-revision", content=body,
    )


def _named_rows() -> dict[str, dict[str, Any]]:
    """One row per legacy fact in §3, each with a stable key of its own."""
    return {
        "grant": grant_row(legacy_key="server_subagent_grants:profile-a/profile-b"),
        "tool": tool_schema_row(legacy_key="synthesized_tools:runner"),
        "roster": roster_row(legacy_key="synthesized_tools:roster"),
        "policy": policy_row(legacy_key="delegation_policy:profile-a"),
        "history": history_row(legacy_key="server_turns:turn-9"),
        "mcp": mcp_entry_row(legacy_key="composition:mcp-1"),
        "profile": profile_row(legacy_key="server_profiles:profile-b"),
        "binding": binding_row(legacy_key="server_profile_assets:profile-a/asset-1"),
        "skill": skill_row(legacy_key="server_assets:asset-skill"),
        "bodyless": asset_row(
            legacy_key="server_assets:asset-nobody", content=None,
            digest=digest_of("nothing supplies this body"),
        ),
        "credential": _credential_row("server_assets:asset-credential"),
        "include": _include_row("server_assets:asset-include"),
        "aggregate": _aggregate_row("server_assets:asset-aggregate"),
        "role-v1": _role_row("server_assets:asset-role-v1", "code-reviewer",
                             "Code Reviewer", 3),
        "role-v2": _role_row("server_assets:asset-role-v2", "agent", "SRE", 2),
    }


def named_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_named_rows().values())


# -- store / service doubles ------------------------------------------------


_WRITE_METHODS = (
    "create_definition", "replace_definition", "write_revision", "write_receipt",
)


class RecordingStore(DefinitionStore):
    """A real store that keeps a log of every write method that ran."""

    def __init__(self, root: Path | str) -> None:
        super().__init__(root)
        self.writes: list[str] = []

    def create_definition(self, definition: dto.AgentDefinition) -> None:
        self.writes.append("create_definition")
        super().create_definition(definition)

    def replace_definition(self, definition: dto.AgentDefinition,
                           *, expected_row_version: int) -> None:
        self.writes.append("replace_definition")
        super().replace_definition(definition, expected_row_version=expected_row_version)

    def write_revision(self, revision: dto.DefinitionRevision) -> None:
        self.writes.append("write_revision")
        super().write_revision(revision)

    def write_receipt(self, **kwargs: Any) -> None:
        self.writes.append("write_receipt")
        super().write_receipt(**kwargs)


class Hub:
    """One isolated store, service, recorder and importer per test."""

    def __init__(self, tmp_path: Path, name: str = "store") -> None:
        self.root = tmp_path / name
        self.store = RecordingStore(self.root)
        self.service = DefinitionService(self.store, authority=FakeAuthority())
        self.importer = migration.LegacyImporter(self.service)

    def snapshot(self) -> dict[str, str]:
        return snapshot_tree(self.root)

    def dry(
        self, rows: Any
    ) -> tuple[migration.MigrationManifestItem, ...]:
        return self.importer.dry_run(rows).items

    def apply(
        self,
        manifest: migration.MigrationManifest,
        rows: Any,
        approvals: Any,
        *,
        operation_key: str,
        **overrides: Any,
    ) -> migration.ImportResult:
        """Apply with this domain's default caller: a recognised principal, a
        fresh row expectation, one server scope."""
        params: dict[str, Any] = {
            "principal": PRINCIPAL, "expected_row_version": 0,
            "operation_key": operation_key, "server_scope": SERVER_SCOPE,
        }
        params.update(overrides)
        return self.importer.apply_import(
            manifest, rows=rows, approvals=approvals, **params,
        )


def hub(tmp_path: Path, name: str = "store") -> Hub:
    return Hub(tmp_path, name)


def approvals_for(
    source: Any,
    *,
    principal: str = PRINCIPAL,
    origin: str = "user-upload",
) -> dict[str, dto.SourceApproval]:
    """Approve exactly the migrate candidates of a dry run or of a row set.

    Each approval names its own row: `origin_ref` is that row's legacy key (the
    reversible mapping) and `content_digest` the digest recorded for it (G05).
    """
    if isinstance(source, migration.MigrationManifest):
        pairs = [
            (item.legacy_key, item.content_digest) for item in source.planned()
        ]
    elif isinstance(source, migration.MigrationManifestItem):
        pairs = [(source.legacy_key, source.content_digest)]
    else:
        pairs = [
            (decision.legacy_key, decision.content_digest)
            for decision in (
                migration.classify(row)
                for row in (source if isinstance(source, (list, tuple)) else list(source))
            )
            if decision.decision is migration.MigrationDecisionKind.MIGRATE_CANDIDATE
        ]
    return {
        legacy_key: dto.SourceApproval(
            origin=origin, origin_ref=str(legacy_key),
            content_digest=str(content_digest),
            approved_by_principal=principal, approved_at=APPROVED_AT,
        )
        for legacy_key, content_digest in pairs
    }


def candidates_of(*rows: Any) -> tuple[dict[str, Any], ...]:
    return tuple(
        row for row in rows
        if migration.classify(row).decision
        is migration.MigrationDecisionKind.MIGRATE_CANDIDATE
    )


def snapshot_tree(root: Path) -> dict[str, str]:
    """Every file under `root` as path -> content digest; {} when absent."""
    base = Path(root)
    if not base.exists():
        return {}
    out: dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            out[str(path.relative_to(base))] = "symlink:" + str(path.readlink())
        elif path.is_file():
            out[str(path.relative_to(base))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


# -- AST scans over migration.py itself ------------------------------------


def _migration_source() -> str:
    return MIGRATION_PY.read_text(encoding="utf-8")


def _module_tree(source: str | None = None) -> ast.Module:
    return ast.parse(_migration_source() if source is None else source)


def _docstring_constants(tree: ast.Module) -> set[int]:
    """The id() of every string constant in a docstring position."""
    docstrings: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, holders):
            body = getattr(node, "body", ())
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return docstrings


def _code_strings(tree: ast.Module) -> list[tuple[int, str]]:
    docs = _docstring_constants(tree)
    return [
        (id(node), node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docs
    ]


def _identifiers(tree: ast.Module) -> list[str]:
    out = [
        getattr(node, "id", None) or getattr(node, "attr", "")
        for node in ast.walk(tree)
        if isinstance(node, (ast.Name, ast.Attribute))
    ]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.extend(arg.arg for arg in node.args.args)
        elif isinstance(node, ast.arg):
            out.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            out.append(node.arg)
    return [str(name) for name in out if name]


def _imported_names(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend((alias.asname or alias.name.split(".")[0]) for alias in node.names)
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
            names.extend((alias.asname or alias.name) for alias in node.names)
    return names


def _legacy_identifiers(source: str) -> list[str]:
    return [
        token for token in BANNED_LEGACY_SYMBOLS
        if token in _identifiers(_module_tree(source))
    ]


def _legacy_code_strings(source: Any) -> list[str]:
    tree = _module_tree(source) if isinstance(source, str) else source
    return [
        f"{token}"
        for _node_id, value in _code_strings(tree)
        for token in BANNED_LEGACY_SYMBOLS
        if token in value
    ]


def _db_symbols(tree: ast.Module) -> list[str]:
    return [
        name for name in _identifiers(tree)
        if name in BANNED_DB_MODULES or name in BANNED_DB_ATTRIBUTES
    ]


class TestMatrixRowByRow:
    """§3's nine rows, decided one at a time, with their reason and row id."""

    def test_a_grant_edge_is_rejected_by_its_table_shape(self) -> None:
        decision = migration.classify(grant_row())
        assert decision.decision is migration.MigrationDecisionKind.REJECT
        assert decision.matrix_row == "M-01"
        assert decision.target_definition_id is None
        assert "authorization edge" in decision.reason

    def test_a_grant_edge_is_rejected_by_its_field_names_alone(self) -> None:
        # No table hint: the shape itself must be enough.
        decision = migration.classify({
            "legacy_key": "edge-without-a-table",
            "parent_profile_id": "p-a", "child_profile_id": "p-b",
        })
        assert decision.decision is migration.MigrationDecisionKind.REJECT
        assert decision.matrix_row == "M-01"

    def test_the_dispatch_tool_pair_is_rejected(self) -> None:
        decision = migration.classify(tool_schema_row(legacy_key="tools:runner"))
        assert decision.decision is migration.MigrationDecisionKind.REJECT
        assert decision.matrix_row == "M-02"
        assert "tool schema" in decision.reason

    def test_a_roster_projection_is_rejected_as_a_dispatch_surface(self) -> None:
        decision = migration.classify(roster_row(legacy_key="tools:roster"))
        assert decision.decision is migration.MigrationDecisionKind.REJECT
        assert decision.matrix_row == "M-02"

    def test_cycle_turn_and_timeout_policy_stays_with_its_owner(self) -> None:
        decision = migration.classify(policy_row(legacy_key="policy:profile-a"))
        assert decision.decision is migration.MigrationDecisionKind.KEEP_LEGACY
        assert decision.matrix_row == "M-03"
        assert decision.target_definition_id is None

    def test_call_history_stays_with_its_owner(self) -> None:
        decision = migration.classify(history_row(legacy_key="turns:turn-9"))
        assert decision.decision is migration.MigrationDecisionKind.KEEP_LEGACY
        assert decision.matrix_row == "M-04"

    def test_the_synthesized_mcp_entry_stays_with_its_owner(self) -> None:
        decision = migration.classify(mcp_entry_row(legacy_key="composition:mcp-1"))
        assert decision.decision is migration.MigrationDecisionKind.KEEP_LEGACY
        assert decision.matrix_row == "M-05"

    def test_a_profile_row_is_unknown_never_a_definition(self) -> None:
        decision = migration.classify(profile_row(legacy_key="server_profiles:profile-b"))
        assert decision.decision is migration.MigrationDecisionKind.UNKNOWN
        assert decision.matrix_row == "M-06"
        assert "projection" in decision.reason
        assert decision.target_definition_id is None

    def test_a_profile_row_stays_unknown_even_when_named_elsewhere(self) -> None:
        # `description` is not a column of the profile table; claiming one in a
        # synthetic row must not manufacture provable provenance.
        decision = migration.classify(profile_row(
            legacy_key="server_profiles:profile-c",
            source_table="server_assets", description="a claimed summary",
        ))
        assert decision.decision is migration.MigrationDecisionKind.UNKNOWN
        assert decision.matrix_row == "M-06"

    def test_an_unnamed_asset_row_is_unknown(self) -> None:
        decision = migration.classify(asset_row(legacy_key="server_assets:n", name=None))
        assert decision.decision is migration.MigrationDecisionKind.UNKNOWN
        assert "name" in decision.reason

    def test_an_asset_row_without_a_digest_is_unknown(self) -> None:
        decision = migration.classify(asset_row(
            legacy_key="server_assets:nodigest", digest=None,
        ))
        assert decision.decision is migration.MigrationDecisionKind.UNKNOWN
        assert "digest" in decision.reason

    def test_an_asset_row_without_its_body_is_unknown(self) -> None:
        decision = migration.classify(asset_row(
            legacy_key="server_assets:nobody", content=None,
        ))
        assert decision.decision is migration.MigrationDecisionKind.UNKNOWN
        assert "body" in decision.reason

    def test_a_body_that_does_not_rehash_is_unknown(self) -> None:
        decision = migration.classify(asset_row(
            legacy_key="server_assets:drift",
            digest=digest_of("other bytes entirely"),
        ))
        assert decision.decision is migration.MigrationDecisionKind.UNKNOWN
        assert "re-hash" in decision.reason

    def test_an_unpinned_revision_is_unknown(self) -> None:
        # A revision number may travel with the body; `latest_revision` alone
        # does not prove which revision was digested.
        decision = migration.classify(asset_row(
            legacy_key="server_assets:unpinned", revision=None, latest_revision=7,
        ))
        assert decision.decision is migration.MigrationDecisionKind.UNKNOWN
        assert "revision" in decision.reason

    def test_the_pinned_revision_travels_with_the_body(self) -> None:
        body = document(name="code-reviewer", description="Reviews code read-only.")
        decision = migration.classify(asset_row(
            legacy_key="server_assets:pinned", content=body,
            digest=digest_of(body), revision=2, latest_revision=5,
        ))
        assert decision.decision is migration.MigrationDecisionKind.MIGRATE_CANDIDATE
        assert decision.target_revision == 2

    def test_a_kind_that_is_not_role_content_is_rejected(self) -> None:
        for kind in sorted(migration.CATALOGUE_KINDS - {"skill"}):
            decision = migration.classify(asset_row(
                legacy_key=f"server_assets:{kind}", kind=kind,
            ))
            assert decision.decision is migration.MigrationDecisionKind.REJECT, kind
            assert decision.matrix_row == "M-07"
            assert decision.target_definition_id is None

    def test_skill_content_is_rejected_as_another_domains(self) -> None:
        decision = migration.classify(skill_row(legacy_key="server_assets:asset-skill"))
        assert decision.decision is migration.MigrationDecisionKind.REJECT
        assert decision.matrix_row == "M-09"
        assert "Q1" in decision.reason

    def test_a_credential_shaped_body_is_unknown(self) -> None:
        decision = migration.classify(
            _credential_row("server_assets:asset-credential")
        )
        assert decision.decision is migration.MigrationDecisionKind.UNKNOWN
        assert "credential" in decision.reason

    def test_a_body_that_reaches_out_is_rejected(self) -> None:
        decision = migration.classify(_include_row("server_assets:asset-include"))
        assert decision.decision is migration.MigrationDecisionKind.REJECT
        assert decision.matrix_row == "M-07"
        assert "reaches outside" in decision.reason
        assert "![[ directive reaches outside" in decision.reason
        assert "FR14" in decision.reason

    def test_a_binding_is_assignment_intent_never_a_definition(self) -> None:
        decision = migration.classify(
            binding_row(legacy_key="server_profile_assets:profile-a/asset-1")
        )
        assert decision.decision is migration.MigrationDecisionKind.ASSIGNMENT_INTENT
        assert decision.matrix_row == "M-08"
        assert "assignment" in decision.reason
        assert decision.target_definition_id is None

    def test_a_binding_without_enabled_is_still_intent(self) -> None:
        decision = migration.classify({
            "table": "server_profile_assets", "profile_id": "p", "asset_id": "a",
        })
        assert decision.decision is migration.MigrationDecisionKind.ASSIGNMENT_INTENT
        assert "unrecorded" in decision.reason

    def test_a_provable_role_row_is_the_only_migrate_candidate(self) -> None:
        decision = migration.classify(
            _role_row("server_assets:asset-role-v1", "code-reviewer", "Code Reviewer", 3)
        )
        assert decision.decision is migration.MigrationDecisionKind.MIGRATE_CANDIDATE
        assert decision.matrix_row == "M-07"
        assert decision.target_revision == 3
        assert decision.content is not None
        assert decision.content.role_body.startswith("---")
        assert migration.MATRIX_ROWS["M-07"] in decision.reason

    def test_every_matrix_row_of_section_3_is_reached(self) -> None:
        rows = named_rows()
        reached = {
            observation.matrix_row
            for report in migration.classify_rows(rows)
            for observation in report.observations
        }
        assert reached == set(migration.MATRIX_ROWS)

    def test_every_decision_names_its_reason_and_row(self) -> None:
        for report in migration.classify_rows(named_rows()):
            decision = report.primary
            assert decision.reason, decision
            assert decision.matrix_row in migration.MATRIX_ROWS
            assert decision.legacy_key


class TestAggregatesAreNotImportable:
    """A legacy *projection* is not a pure definition row."""

    def test_a_bundled_row_is_refused_and_reports_every_fact(self) -> None:
        report = migration.classify_rows([_aggregate_row("server_assets:agg")])[0]
        assert report.primary.decision is migration.MigrationDecisionKind.REJECT
        assert report.primary.matrix_row == "M-01"
        assert not report.importable
        assert report.primary.target_definition_id is None
        assert {item.matrix_row for item in report.observations} == {"M-01", "M-07"}
        assert "server_assets:agg" in report.primary.legacy_key

    def test_a_bundled_row_yields_no_target_line_in_a_manifest(self) -> None:
        manifest = migration.dry_run([_aggregate_row("server_assets:agg")])
        assert len(manifest.items) == 1
        item = manifest.items[0]
        assert item.decision is migration.MigrationDecisionKind.REJECT
        assert item.target_definition_id is None
        assert manifest.planned() == ()

    def test_a_candidate_primary_is_always_a_single_fact_row(self) -> None:
        # The write path has one defensive branch for "a candidate primary that
        # is not importable"; this invariant is what makes it unreachable: a
        # primary only ever says MIGRATE_CANDIDATE when the row held exactly
        # one fact, and that fact is the candidate itself.
        variants = list(named_rows()) + [
            _aggregate_row(f"server_assets:agg-{index}") for index in range(3)
        ] + [
            _role_row(f"server_assets:pure-{index}", "code-reviewer", "Reviewer", 1)
            for index in range(3)
        ] + [asset_row(legacy_key="server_assets:mcp", kind="mcp")]
        for report in migration.classify_rows(variants):
            if report.primary.decision is (
                migration.MigrationDecisionKind.MIGRATE_CANDIDATE
            ):
                assert report.importable, report.as_report()
                assert len(report.observations) == 1
                assert report.primary.target_definition_id is not None

    def test_a_pure_role_row_still_has_exactly_one_fact(self) -> None:
        report = migration.classify_rows([
            _role_row("server_assets:pure", "code-reviewer", "Code Reviewer", 1)
        ])[0]
        assert len(report.observations) == 1
        assert report.importable


class TestVocabularyScanIsNotVacuous:
    """The scans must be able to fail, or they prove nothing."""

    def test_the_scans_read_the_real_module(self) -> None:
        tree = _module_tree()
        assert MIGRATION_PY.is_file()
        assert len(_code_strings(tree)) > 40
        assert len(_identifiers(tree)) > 100

    def test_an_identifier_naming_the_legacy_dispatcher_is_caught(self) -> None:
        mutated = _migration_source() + "\n\ndef run_subagent():\n    return 1\n"
        assert _legacy_identifiers(mutated) == ["run_subagent"]

    def test_a_non_docstring_string_holding_a_legacy_tool_name_is_caught(self) -> None:
        mutated = _migration_source() + '\n\nX = "run_subagent"\n'
        assert _legacy_code_strings(mutated) == ["run_subagent"]

    def test_a_db_call_is_caught(self) -> None:
        mutated = _migration_source() + "\n\ndef f(conn):\n    return conn.execute(1)\n"
        assert "execute" in _db_symbols(_module_tree(mutated))

    def test_a_legacy_module_import_is_caught(self) -> None:
        mutated = _migration_source() + "\nimport sqlite3\n"
        assert "sqlite3" in _imported_names(_module_tree(mutated))


class TestRejectIsStructural:
    """The negative half of G10: the mechanism must not be reachable."""

    def test_migration_names_no_legacy_dispatch_symbol(self) -> None:
        source = _migration_source()
        assert _legacy_identifiers(source) == []
        assert _legacy_code_strings(_module_tree(source)) == []

    def test_migration_imports_no_database_or_legacy_module(self) -> None:
        assert sorted(set(_imported_names(_module_tree())) & set(BANNED_DB_MODULES)) == []

    def test_migration_calls_no_sql_or_home_helper(self) -> None:
        tree = _module_tree()
        assert _db_symbols(tree) == []
        assert [
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in {"home", "expanduser"}
        ] == []

    def test_a_hand_built_candidate_line_for_a_grant_row_writes_nothing(
        self, tmp_path: Path,
    ) -> None:
        # The write path re-runs the matrix over the rows it is handed, so a
        # manifest line that claims a candidate for an authorization edge is
        # refused before the first write rather than trusted.
        unit = hub(tmp_path)
        grant = grant_row(legacy_key="server_subagent_grants:p-a/p-b")
        real = migration.dry_run(named_rows()).planned()[0]
        smuggled = migration.MigrationManifestItem(
            legacy_key="server_subagent_grants:p-a/p-b",
            content_digest=real.content_digest,
            target_definition_id=real.target_definition_id,
            target_revision=real.target_revision,
            decision=migration.MigrationDecisionKind.MIGRATE_CANDIDATE,
            reason="hand-built", matrix_row="M-07",
        )
        with pytest.raises(errors.DomainError) as exc:
            unit.apply(
                migration.MigrationManifest(items=(smuggled,)), [grant],
                approvals_for(real), operation_key="op-smuggle",
            )
        assert exc.value.code == errors.ASSIGNMENT_CONFLICT
        assert unit.store.list_definitions() == []
        assert unit.store.writes == []

    def test_the_write_path_reuses_the_stores_own_writers(self) -> None:
        tree = _module_tree()
        attributes = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        assert {"create_definition", "write_revision", "replace_definition",
                "write_receipt", "read_receipt"} <= attributes

    def test_the_whole_legacy_grant_table_yields_no_plan(self) -> None:
        table = [grant_row(legacy_key=f"g:{index}") for index in range(8)]
        manifest = migration.dry_run(table)
        assert manifest.planned() == ()
        assert all(item.matrix_row == "M-01" for item in manifest.items)

    def test_applying_a_purely_refused_manifest_creates_no_agent_definition(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = [grant_row(legacy_key=f"g:{index}") for index in range(4)]
        manifest = unit.importer.dry_run(rows)
        result = unit.apply(manifest, rows, {}, operation_key="op-refused")
        assert result.imported == ()
        assert len(result.skipped) == 4
        assert unit.store.list_definitions() == []
        assert unit.store.writes == []
        assert unit.snapshot() == {}

    def test_a_manifest_carrying_only_refused_needs_no_approvals(self, tmp_path: Path) -> None:
        rows = [grant_row(legacy_key="g:1"), history_row(legacy_key="t:1"),
                policy_row(legacy_key="p:1"), profile_row(legacy_key="pr:1")]
        manifest = migration.dry_run(rows)
        assert not manifest.planned()
        assert {item.decision for item in manifest.items} == {
            migration.MigrationDecisionKind.REJECT,
            migration.MigrationDecisionKind.KEEP_LEGACY,
            migration.MigrationDecisionKind.UNKNOWN,
        }


class TestDryRunWritesNothing:
    def test_a_dry_run_leaves_the_store_bytes_untouched(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        unit.service.create_definition(
            PRINCIPAL, server_scope=SERVER_SCOPE, slug="seeded",
            display_name="Seeded", description="Seeded before the dry run.",
            origin_scope="public", origin_owner="local", operation_key="op-seed",
        )
        before, writes = unit.snapshot(), list(unit.store.writes)
        manifest = unit.importer.dry_run(named_rows())
        assert unit.snapshot() == before
        assert unit.store.writes == writes
        assert manifest.items

    def test_the_pure_report_function_takes_no_store_at_all(self) -> None:
        manifest = migration.dry_run(named_rows())
        assert isinstance(manifest, migration.MigrationManifest)
        assert manifest.manifest_digest.startswith("sha256:")

    def test_a_dry_run_reports_every_row_including_the_refused(self, tmp_path: Path) -> None:
        rows = named_rows()
        manifest = hub(tmp_path).importer.dry_run(rows)
        assert len(manifest.items) == len(rows)
        assert manifest.refused()
        assert {item.decision for item in manifest.items} > {
            migration.MigrationDecisionKind.MIGRATE_CANDIDATE,
        }

    def test_only_a_candidate_names_a_target(self, tmp_path: Path) -> None:
        manifest = hub(tmp_path).importer.dry_run(named_rows())
        for item in manifest.items:
            if item.decision is migration.MigrationDecisionKind.MIGRATE_CANDIDATE:
                assert item.target_definition_id and item.target_revision
            else:
                assert item.target_definition_id is None
                assert item.target_revision is None

    def test_the_report_is_ordered_by_a_defined_key_not_input_order(
        self, tmp_path: Path,
    ) -> None:
        rows = list(_named_rows().values())
        reversed_rows = list(reversed(rows))
        rotated = rows[5:] + rows[:5]
        first = hub(tmp_path).importer.dry_run(rows)
        assert hub(tmp_path).importer.dry_run(reversed_rows).items == first.items
        assert hub(tmp_path).importer.dry_run(rotated).manifest_digest == first.manifest_digest
        keys = [item.legacy_key for item in first.items]
        assert keys == sorted(keys)
        assert len(keys) == len(set(keys))

    def test_the_manifest_line_shape_is_the_five_reported_fields(self) -> None:
        manifest = migration.dry_run(named_rows())
        for item in manifest.items:
            assert set(item.as_mapping()) == {
                "legacy_key", "content_digest", "target_definition_id",
                "target_revision", "decision", "reason", "matrix_row",
            }
            if item.content_digest is not None:
                assert DIGEST_RE.match(item.content_digest)

    def test_a_repeated_dry_run_is_identical(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = named_rows()
        assert unit.importer.dry_run(rows).as_report() == unit.importer.dry_run(rows).as_report()
        assert unit.importer.dry_run(rows).manifest_digest == migration.dry_run(rows).manifest_digest


class TestApplyPersistsOnlyCandidates:
    def test_a_second_candidate_sharing_a_slug_still_imports(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        first = asset_row(legacy_key="server_assets:a1", name="Code Reviewer")
        second = asset_row(legacy_key="server_assets:a2", name="Code Reviewer Again")
        rows = [first, second]
        manifest = unit.importer.dry_run(rows)
        assert len(manifest.planned()) == 2
        result = unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-shared-slug", approvals=approvals_for(manifest),
            rows=rows, server_scope=SERVER_SCOPE,
        )
        assert len(result.imported) == 2
        assert len({item.definition_id for item in result.imported}) == 2

    def test_a_candidate_needs_its_own_explicit_approval(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        approvals = approvals_for(manifest)
        dropped = dict(approvals)
        dropped.pop(manifest.planned()[0].legacy_key)
        before, writes = unit.snapshot(), list(unit.store.writes)
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-missing", approvals=dropped, rows=rows,
                server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.DEFINITION_INVALID
        assert unit.snapshot() == before
        assert unit.store.writes == writes

    def test_an_approval_for_other_bytes_is_refused(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        approvals = approvals_for(manifest)
        approvals = {
            key: dto.SourceApproval(
                **{**vars(value), "content_digest": digest_of("other content")}
            )
            for key, value in approvals.items()
        }
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-other-bytes", approvals=approvals, rows=rows,
                server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.TARGET_CONFLICT
        assert unit.snapshot() == {}

    def test_an_approval_by_another_principal_is_refused(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        approvals = {
            key: dto.SourceApproval(
                **{**vars(value), "approved_by_principal": "u:someone-else"}
            )
            for key, value in approvals_for(manifest).items()
        }
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-other-principal", approvals=approvals, rows=rows,
                server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING

    def test_an_unrecognised_principal_writes_nothing(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal="u:stranger", expected_row_version=0,
                operation_key="op-stranger",
                approvals=approvals_for(manifest, principal="u:stranger"),
                rows=rows, server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert unit.store.writes == []

    def test_a_definition_may_not_raise_its_own_ceiling(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        body = document(
            name="escalating", description="Requests more than granted.",
            extra=f"permission: {TOO_HIGH_CEILING}",
        )
        rows = [asset_row(legacy_key="server_assets:esc", name="Escalating", content=body)]
        manifest = unit.importer.dry_run(rows)
        assert manifest.planned()
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-ceiling", approvals=approvals_for(manifest),
                rows=rows, server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert unit.store.writes == []

    def test_a_manifest_line_naming_a_row_its_source_does_not_carry_is_refused(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = [grant_row(legacy_key="server_subagent_grants:g1")]
        other = migration.dry_run(named_rows()).planned()[0]
        forged = migration.MigrationManifestItem(
            legacy_key=other.legacy_key, content_digest=other.content_digest,
            target_definition_id=other.target_definition_id,
            target_revision=other.target_revision,
            decision=migration.MigrationDecisionKind.MIGRATE_CANDIDATE,
            reason="hand-built", matrix_row="M-07",
        )
        with pytest.raises(errors.DomainError) as exc:
            unit.apply(
                migration.MigrationManifest(items=(*unit.dry(rows), forged)),
                rows, approvals_for(other), operation_key="op-forged",
            )
        assert exc.value.code == errors.TARGET_CONFLICT
        assert unit.store.list_definitions() == []
        assert unit.store.writes == []

    def test_a_tampered_decision_for_a_bundled_row_is_refused(
        self, tmp_path: Path,
    ) -> None:
        # The row behind this line really does carry a role body, and it really
        # also carries an authorization edge: a manifest that drops the second
        # fact and claims a candidate is refused, because the write path
        # re-runs the matrix instead of trusting the report.
        unit = hub(tmp_path)
        rows = [_aggregate_row("server_assets:asset-aggregate")]
        real = migration.classify(rows[0])
        assert real.decision is migration.MigrationDecisionKind.REJECT
        candidate_line = migration.MigrationManifestItem(
            legacy_key=real.legacy_key, content_digest=digest_of(
                _aggregate_row("server_assets:asset-aggregate")["content"]
            ),
            target_definition_id="def_imp_" + "0" * 24, target_revision=5,
            decision=migration.MigrationDecisionKind.MIGRATE_CANDIDATE,
            reason="hand-built", matrix_row="M-07",
        )
        with pytest.raises(errors.DomainError) as exc:
            unit.apply(
                migration.MigrationManifest(items=(candidate_line,)),
                rows, approvals_for(candidate_line), operation_key="op-tampered",
            )
        assert exc.value.code == errors.ASSIGNMENT_CONFLICT
        assert unit.store.list_definitions() == []
        assert unit.store.writes == []

    def test_a_refused_item_never_blocks_the_candidates(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = named_rows()
        manifest = unit.importer.dry_run(rows)
        result = unit.apply(
            manifest, rows, approvals_for(manifest), operation_key="op-mixed",
        )
        assert len(result.imported) == len(manifest.planned()) == 2
        assert len(result.skipped) == len(manifest.refused())
        assert {entry.legacy_key for entry in result.skipped}.isdisjoint(
            result.mapping_table()
        )

    def test_the_pinned_revision_and_the_body_survive_the_round_trip(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = [
            _role_row("server_assets:v3", "code-reviewer", "Code Reviewer", 3),
            _role_row("server_assets:v9", "sre", "SRE", 9),
        ]
        manifest = unit.importer.dry_run(rows)
        result = unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-pin", approvals=approvals_for(manifest),
            rows=rows, server_scope=SERVER_SCOPE,
        )
        by_key = {item.legacy_key: item for item in result.imported}
        assert by_key["server_assets:v3"].revision == 3
        assert by_key["server_assets:v9"].revision == 9
        stored = unit.store.get_revision(
            by_key["server_assets:v3"].definition_id, 3
        )
        assert digest.bytes_digest(stored.role_body.encode("utf-8")) == (
            by_key["server_assets:v3"].content_digest
        )
        assert unit.store.read_revision(
            by_key["server_assets:v9"].definition_id, 1
        ) is None
        assert unit.store.revision_numbers(
            by_key["server_assets:v9"].definition_id
        ) == [9]
        assert unit.store.get_definition(
            by_key["server_assets:v9"].definition_id
        ).latest_revision == 9

    def test_the_legacy_key_is_recorded_so_the_mapping_is_reversible(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        result = unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-ref", approvals=approvals_for(manifest),
            rows=rows, server_scope=SERVER_SCOPE,
        )
        for item in result.imported:
            stored = unit.store.get_revision(item.definition_id, item.revision)
            assert stored.source is not None
            assert stored.source.origin_ref == item.legacy_key
        assert set(result.mapping_table()) == {
            item.legacy_key for item in result.imported
        }

    def test_an_approval_naming_another_key_is_not_a_mapping(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        approvals = {
            key: dto.SourceApproval(
                **{**vars(value), "origin_ref": "server_assets:some-other-row"}
            )
            for key, value in approvals_for(manifest).items()
        }
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-wrong-ref", approvals=approvals, rows=rows,
                server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.TARGET_CONFLICT

    def test_a_git_revision_source_is_storable_through_an_approved_import(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        pin = "0123456789abcdef0123456789abcdef01234567"
        body = document(name="git-reviewer", description="Reviewed at a pinned commit.")
        rows = [asset_row(
            legacy_key=f"catalogue@{pin}", name="Git Reviewer",
            content=body, digest=digest_of(body), revision=1, latest_revision=1,
        )]
        manifest = unit.importer.dry_run(rows)
        assert len(manifest.planned()) == 1
        approvals = approvals_for(manifest, origin="git-revision")
        result = unit.apply(
            manifest, rows, approvals, operation_key="op-git",
        )
        item = result.imported[0]
        stored = unit.store.get_revision(item.definition_id, item.revision)
        assert stored.source is not None
        assert stored.source.origin == "git-revision"
        assert stored.source.origin_ref.endswith(pin)

    def test_a_floating_git_source_is_refused(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        approvals = {
            key: dto.SourceApproval(**{**vars(value), "origin": "git-revision"})
            for key, value in approvals_for(manifest).items()
        }
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-floating", approvals=approvals, rows=rows,
                server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.DEFINITION_INVALID
        assert unit.snapshot() == {}

    def test_a_missing_source_set_refuses_every_candidate(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-no-approvals", approvals={}, rows=rows,
                server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.DEFINITION_INVALID

    def test_the_source_rows_must_be_the_ones_the_manifest_covers(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-absent", approvals=approvals_for(manifest),
                rows=[grant_row(legacy_key="g:absent")], server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.TARGET_CONFLICT

    def test_a_body_that_drifted_after_the_dry_run_is_refused(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        drifted = [
            {**row, "content": row["content"] + "\nOne more line.\n"} for row in rows
        ]
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-drift", approvals=approvals_for(manifest),
                rows=drifted, server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.ASSIGNMENT_CONFLICT
        assert unit.snapshot() == {}

    def test_an_unexpected_row_version_is_stale_and_writes_nothing(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=1,
                operation_key="op-stale", approvals=approvals_for(manifest),
                rows=rows, server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.REVISION_STALE
        assert unit.snapshot() == {}
        assert unit.store.writes == []

    def test_a_duplicate_legacy_key_in_the_source_is_refused(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-dupe", approvals=approvals_for(manifest),
                rows=rows + [rows[0]], server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.TARGET_CONFLICT


class TestReplayAndIdStability:
    def test_the_same_key_and_payload_replay_the_recorded_result(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = named_rows()
        manifest = unit.importer.dry_run(rows)
        approvals = approvals_for(manifest)
        first = unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-replay", approvals=approvals, rows=rows,
            server_scope=SERVER_SCOPE,
        )
        after_first, writes = unit.snapshot(), list(unit.store.writes)
        second = unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-replay", approvals=approvals, rows=rows,
            server_scope=SERVER_SCOPE,
        )
        assert second.replayed is True
        assert first.replayed is False
        assert second.imported == first.imported
        assert unit.snapshot() == after_first
        assert unit.store.writes == writes
        for item in first.imported:
            assert unit.store.revision_numbers(item.definition_id) == [item.revision]

    def test_a_different_payload_under_the_same_key_is_refused(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = named_rows()
        manifest = unit.importer.dry_run(rows)
        approvals = approvals_for(manifest)
        unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-clash", approvals=approvals, rows=rows,
            server_scope=SERVER_SCOPE,
        )
        snapshot, writes = unit.snapshot(), list(unit.store.writes)
        moved = {
            key: dto.SourceApproval(
                **{**vars(value), "approved_at": "2026-09-29T00:00:00+00:00"}
            )
            for key, value in approvals.items()
        }
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-clash", approvals=moved, rows=rows,
                server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.ASSIGNMENT_CONFLICT
        assert unit.snapshot() == snapshot
        assert unit.store.writes == writes

    def test_re_running_the_same_key_never_adds_a_second_copy(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        approvals = approvals_for(manifest)
        unit.apply(manifest, rows, approvals, operation_key="op-first")
        again = unit.apply(manifest, rows, approvals, operation_key="op-first")
        assert again.replayed is True
        assert len(unit.store.list_definitions()) == len(manifest.planned()) == 2

    def test_a_fresh_key_over_an_imported_row_is_a_stale_cas(
        self, tmp_path: Path,
    ) -> None:
        # The target id is derived from the row, so a second import of the same
        # row cannot create a duplicate: it meets the row it already made and
        # the caller's `expected_row_version` no longer holds.
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        approvals = approvals_for(manifest)
        unit.apply(manifest, rows, approvals, operation_key="op-first")
        writes, snapshot = list(unit.store.writes), unit.snapshot()
        with pytest.raises(errors.DomainError) as exc:
            unit.apply(
                manifest, rows, approvals, operation_key="op-second",
                expected_row_version=0,
            )
        assert exc.value.code == errors.REVISION_STALE
        assert unit.store.writes == writes
        assert unit.snapshot() == snapshot
        assert len(unit.store.list_definitions()) == 2

    def test_two_roots_and_two_keys_yield_identical_manifests_and_ids(
        self, tmp_path: Path,
    ) -> None:
        rows = named_rows()
        left, right = hub(tmp_path, "left"), hub(tmp_path, "right")
        first = left.importer.dry_run(rows)
        second = right.importer.dry_run(rows)
        assert first.items == second.items
        assert first.manifest_digest == second.manifest_digest
        assert [item.target_definition_id for item in first.planned()] == [
            item.target_definition_id for item in second.planned()
        ]
        assert len({item.target_definition_id for item in first.planned()}
                   ) == len(first.planned())
        left_result = left.importer.apply_import(
            first, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-left", approvals=approvals_for(first), rows=rows,
            server_scope=SERVER_SCOPE,
        )
        right_result = right.importer.apply_import(
            second, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-right", approvals=approvals_for(second), rows=rows,
            server_scope=SERVER_SCOPE,
        )
        assert left_result.imported == right_result.imported
        assert _definitions_of(left.snapshot()) == _definitions_of(right.snapshot())

    def test_the_same_operation_into_two_roots_leaves_identical_bytes(
        self, tmp_path: Path,
    ) -> None:
        # G10's byte half: the importer is a pure function of approved input,
        # so the same manifest, the same approvals and the same operation key
        # must produce the same bytes wherever they land.
        rows = named_rows()
        left, right = hub(tmp_path, "same-left"), hub(tmp_path, "same-right")
        first = left.importer.dry_run(rows)
        second = right.importer.dry_run(rows)
        assert first.manifest_digest == second.manifest_digest
        left.apply(first, rows, approvals_for(first), operation_key="op-same")
        right.apply(second, rows, approvals_for(second), operation_key="op-same")
        assert left.snapshot() == right.snapshot()
        assert left.snapshot()

    def test_a_target_id_depends_on_the_key_and_digest_not_on_the_objects(
        self, tmp_path: Path,
    ) -> None:
        # G10 needs the same target id in another process and another store, so
        # the derivation may not see anything but these two values. Two equal
        # strings that are distinct objects are what a fresh interpreter hands
        # this function on the next run.
        key = "server_assets:role-recomputed"
        body = document(name="role-recomputed", description="Recomputed twice.")
        here = digest_of(body)
        there = digest_of(document(name="other-role", description="Other body."))
        left = bytes(key, "utf-8").decode("utf-8")
        right = bytes(key, "utf-8").decode("utf-8")
        assert left is not right, "the fixtures share one object; the probe is blind"
        assert migration.definition_id_for(left, here) == migration.definition_id_for(
            right, here
        )
        assert migration.definition_id_for(left, here) != migration.definition_id_for(
            left, there
        )
        assert migration.definition_id_for(left, here) != migration.definition_id_for(
            "server_assets:another-role", here
        )
        assert migration.definition_id_for(left, here).startswith("def_imp_")

    def test_a_target_id_needs_the_digest_it_attests(self) -> None:
        for bad in ("", "sha256:short", "md5:" + "a" * 32, "sha256:" + "A" * 64):
            with pytest.raises(errors.DomainError) as exc:
                migration.definition_id_for("server_assets:x", bad)
            assert exc.value.code == errors.DEFINITION_INVALID

    def test_target_ids_are_opaque_and_never_derived_from_a_name(
        self, tmp_path: Path,
    ) -> None:
        rows = [
            _role_row("server_assets:aaa", "zzz-name", "Zed", 1),
            _role_row("server_assets:bbb", "aaa-name", "Aye", 2),
        ]
        manifest = migration.dry_run(rows)
        for item in manifest.planned():
            assert item.target_definition_id
            assert "aaa" not in item.target_definition_id or item.legacy_key.endswith("aaa")
            assert "zzz" not in item.target_definition_id
            assert "name" not in item.target_definition_id
            assert "codereviewer" not in item.target_definition_id.lower().replace("_", "")
        assert DIGEST_RE.match(str(manifest.planned()[0].content_digest))

    def test_one_caller_key_records_one_receipt_per_item(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        result = unit.apply(
            manifest, rows, approvals_for(manifest), operation_key="op-keys",
        )
        assert len(result.imported) == 2
        expected = {
            # one receipt for the whole apply, plus the service's own receipt
            # for each created row, keyed by that item's target id
            (f"legacy_import:{PRINCIPAL}:{SERVER_SCOPE}:{manifest.manifest_digest}",
             "op-keys"),
        } | {
            (
                f"create:{PRINCIPAL}:{SERVER_SCOPE}/"
                + unit.store.get_definition(item.definition_id).slug,
                f"op-keys:{item.definition_id}",
            )
            for item in result.imported
        }
        assert set(_receipt_entries(unit.root)) == expected


def _definitions_of(snapshot: dict[str, str]) -> dict[str, str]:
    return {
        name: value for name, value in snapshot.items() if name.startswith("definitions/")
    }


def _receipt_entries(root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for scope_dir in sorted((Path(root) / "receipts").iterdir()):
        for entry in sorted(scope_dir.glob("*.json")):
            text = entry.read_text(encoding="utf-8")
            scope = text.split('"scope": "', 1)[1].split('"', 1)[0]
            key = text.split('"operation_key": "', 1)[1].split('"', 1)[0]
            out.append((scope, key))
    return out


class TestRollbackSample:
    def test_a_dry_run_produces_nothing_to_remove(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        manifest = unit.importer.dry_run(named_rows())
        sample = unit.importer.rollback_sample(manifest, unit.root)
        assert sample.mapping == ()
        assert sample.deletion_paths == ()
        assert unit.snapshot() == {}

    def test_the_sample_lists_the_mapping_table(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = named_rows()
        manifest = unit.importer.dry_run(rows)
        result = unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-sample", approvals=approvals_for(manifest),
            rows=rows, server_scope=SERVER_SCOPE,
        )
        sample = unit.importer.rollback_sample(
            manifest, unit.root, context=result.context,
        )
        assert dict(sample.mapping) == result.mapping_table()
        assert len(sample.mapping) == len(manifest.planned())
        assert set(sample.mapping_table()) == set(result.mapping_table())
        assert all(
            path.startswith("definitions/") for path in sample.deletion_paths
            if not path.startswith("receipts/")
        )
        for path in sample.deletion_paths:
            assert path.startswith("definitions/") or path.startswith("receipts/")
        assert sample.untouched_definition_ids == ()

    def test_the_sample_only_names_rows_it_verified(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = named_rows()
        manifest = unit.importer.dry_run(rows)
        result = unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-verify", approvals=approvals_for(manifest),
            rows=rows, server_scope=SERVER_SCOPE,
        )
        unrelated = unit.service.create_definition(
            PRINCIPAL, server_scope=SERVER_SCOPE, slug="unrelated",
            display_name="Unrelated", description="Seeded before the rollback.",
            origin_scope="public", origin_owner="local", operation_key="op-unrelated",
        )
        unit.service.save_revision(
            PRINCIPAL,
            _revision_for(unrelated, "An unrelated body of its own."),
            server_scope=SERVER_SCOPE, operation_key="op-unrelated-rev",
            expected_row_version=1,
        )
        before = unit.snapshot()
        sample = unit.importer.rollback_sample(
            manifest, unit.root, context=result.context,
        )
        assert not any(
            unrelated.definition_id in path for path in sample.deletion_paths
        )
        removed = unit.importer.remove_rollback_set(sample)
        assert sorted(removed) == sorted(sample.deletion_paths)
        assert unit.store.read_definition(unrelated.definition_id) is not None
        assert set(_definitions_of(unit.snapshot())) == {
            name for name in _definitions_of(before)
            if not any(name.startswith(f"definitions/{item}/")
                       for _, item in sample.mapping)
        }

    def test_a_row_the_import_did_not_create_is_left_alone(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        planned = manifest.planned()[0]
        assert planned.target_definition_id is not None
        # Something else holds that id: same id, different bytes.
        unit.service.create_definition(
            PRINCIPAL, server_scope=SERVER_SCOPE, slug="held-by-another",
            display_name="Held", description="An id collision, not our import.",
            origin_scope="public", origin_owner="local",
            operation_key="op-hold", definition_id=planned.target_definition_id,
        )
        unit.service.save_revision(
            PRINCIPAL,
            _revision_for(
                unit.store.get_definition(planned.target_definition_id),
                "A body that is not the legacy bytes.",
            ),
            server_scope=SERVER_SCOPE, operation_key="op-hold-rev",
            expected_row_version=1,
        )
        sample = unit.importer.rollback_sample(manifest, unit.root)
        assert sample.mapping == ()
        assert sample.deletion_paths == ()
        assert planned.target_definition_id in sample.untouched_definition_ids

    def test_a_hand_widened_deletion_set_is_refused(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = named_rows()
        manifest = unit.importer.dry_run(rows)
        result = unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-widened", approvals=approvals_for(manifest),
            rows=rows, server_scope=SERVER_SCOPE,
        )
        unrelated = unit.service.create_definition(
            PRINCIPAL, server_scope=SERVER_SCOPE, slug="keepme",
            display_name="Keep", description="Must survive.",
            origin_scope="public", origin_owner="local", operation_key="op-keep",
        )
        sample = unit.importer.rollback_sample(
            manifest, unit.root, context=result.context,
        )
        widended = migration.RollbackSample(
            manifest_digest=sample.manifest_digest, store_root=sample.store_root,
            mapping=sample.mapping,
            deletion_paths=sample.deletion_paths + (
                f"definitions/{unrelated.definition_id}",
            ),
            verified=sample.verified,
            untouched_definition_ids=sample.untouched_definition_ids,
            context=sample.context,
        )
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.remove_rollback_set(widended)
        assert exc.value.code == errors.TARGET_CONFLICT
        assert unit.store.read_definition(unrelated.definition_id) is not None

    def test_apply_rollback_apply_reproduces_the_same_bytes(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = named_rows()
        manifest = unit.importer.dry_run(rows)
        approvals = approvals_for(manifest)

        def apply(key: str) -> None:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key=key, approvals=approvals, rows=rows,
                server_scope=SERVER_SCOPE,
            )

        apply("op-cycle")
        first = unit.snapshot()
        assert first
        result_import = unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-cycle", approvals=approvals, rows=rows,
            server_scope=SERVER_SCOPE,
        )
        sample = unit.importer.rollback_sample(
            manifest, unit.root, context=result_import.context,
        )
        assert unit.importer.remove_rollback_set(sample) == sample.deletion_paths
        assert unit.snapshot() == {}
        apply("op-cycle")
        assert unit.snapshot() == first

    def test_rollback_removes_no_receipt_without_an_explicit_context(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-nocontext", approvals=approvals_for(manifest),
            rows=rows, server_scope=SERVER_SCOPE,
        )
        sample = unit.importer.rollback_sample(manifest, unit.root)
        assert sample.deletion_paths
        assert not any(path.startswith("receipts/") for path in sample.deletion_paths)
        unit.importer.remove_rollback_set(sample)
        assert (unit.root / "receipts").is_dir()


def _revision_for(definition: dto.AgentDefinition, body: str) -> dto.DefinitionRevision:
    """Build a valid second revision for an unrelated definition."""
    approval = dto.SourceApproval(
        origin="user-upload", origin_ref="hand-written", content_digest=digest_of(body),
        approved_by_principal=PRINCIPAL, approved_at=APPROVED_AT,
    )
    provisional = dto.DefinitionRevision(
        definition_id=definition.definition_id, revision=1,
        content_digest="sha256:" + "0" * 64, role_body=body, source=approval,
    )
    return dto.DefinitionRevision(
        **{
            **dict(vars(provisional)),
            "content_digest": digest.revision_digest(provisional),
        }
    )


class TestRowShapes:
    @dataclass(frozen=True)
    class AssetRow:
        legacy_key: str
        kind: str
        name: str
        description: str
        latest_revision: int
        digest: str
        source: str
        content: str
        revision: int

    class DbRow:
        """The shape a DB reader hands over: keys() plus column indexing."""

        def __init__(self, columns: dict[str, Any]) -> None:
            self._columns = dict(columns)

        def keys(self) -> list[str]:
            return list(self._columns)

        def __getitem__(self, name: str) -> Any:
            return self._columns[name]

    def test_a_frozen_row_dataclass_is_a_row(self) -> None:
        columns = asset_row(legacy_key="server_assets:dc")
        row = self.AssetRow(**{
            name: columns[name]
            for name in ("legacy_key", "kind", "name", "description",
                         "latest_revision", "digest", "source", "content", "revision")
        })
        decision = migration.classify(row)
        assert decision.decision is migration.MigrationDecisionKind.MIGRATE_CANDIDATE
        assert decision.legacy_key == "server_assets:dc"

    def test_a_db_row_shape_is_read_as_columns(self) -> None:
        row = self.DbRow(asset_row(legacy_key="server_assets:db"))
        assert migration.classify(row).decision is (
            migration.MigrationDecisionKind.MIGRATE_CANDIDATE
        )

    def test_a_grant_db_row_shape_is_still_rejected(self) -> None:
        row = self.DbRow(grant_row(legacy_key="server_subagent_grants:db"))
        assert migration.classify(row).decision is (
            migration.MigrationDecisionKind.REJECT
        )

    def test_an_object_that_is_not_a_row_is_refused(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            migration.classify(object())
        assert exc.value.code == errors.DEFINITION_INVALID

    def test_a_non_string_legacy_key_is_refused(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            migration.classify({"legacy_key": b"bytes-key"})
        assert exc.value.code == errors.DEFINITION_INVALID

    def test_an_overlong_legacy_key_is_refused(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            migration.classify({"legacy_key": "x" * 600})
        assert exc.value.code == errors.DEFINITION_INVALID

    def test_a_path_shaped_legacy_key_is_refused(self) -> None:
        for key in ("/etc/passwd", "~/x", "../x"):
            with pytest.raises(errors.DomainError) as exc:
                migration.classify({"legacy_key": key, "id": "1"})
            assert exc.value.code == errors.DEFINITION_INVALID

    def test_a_key_is_derived_from_the_table_and_id_when_absent(self) -> None:
        decision = migration.classify(grant_row())
        assert decision.legacy_key.startswith("server_subagent_grants:")
        unnamed = migration.classify({"something_unheard_of": 1})
        assert unnamed.decision is migration.MigrationDecisionKind.UNKNOWN
        assert unnamed.legacy_key.startswith("legacy_row:row-")

    def test_an_import_must_name_a_server_scope(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-no-scope", approvals=approvals_for(manifest),
                rows=rows,
            )
        assert exc.value.code == errors.DEFINITION_INVALID
        assert unit.store.writes == []

    def test_an_import_must_carry_its_source_rows(self, tmp_path: Path) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        with pytest.raises(errors.DomainError) as exc:
            unit.importer.apply_import(
                manifest, principal=PRINCIPAL, expected_row_version=0,
                operation_key="op-no-rows", approvals=approvals_for(manifest),
                server_scope=SERVER_SCOPE,
            )
        assert exc.value.code == errors.DEFINITION_INVALID
        assert unit.store.writes == []

    def test_the_stored_bytes_are_what_the_manifest_anchored(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        result = unit.apply(
            manifest, rows, approvals_for(manifest), operation_key="op-bytes",
        )
        by_key = manifest.by_legacy_key()
        for item in result.imported:
            line = by_key[item.legacy_key]
            stored = unit.store.get_revision(item.definition_id, item.revision)
            assert item.content_digest == line.content_digest
            assert bytes.fromhex(
                str(item.content_digest).removeprefix("sha256:")
            ) == hashlib.sha256(stored.role_body.encode("utf-8")).digest()
            assert stored.revision == line.target_revision

    def test_the_stored_revision_digest_covers_content_not_identity(
        self, tmp_path: Path,
    ) -> None:
        unit = hub(tmp_path)
        rows = list(candidates_of(*named_rows()))
        manifest = unit.importer.dry_run(rows)
        result = unit.importer.apply_import(
            manifest, principal=PRINCIPAL, expected_row_version=0,
            operation_key="op-digest", approvals=approvals_for(manifest),
            rows=rows, server_scope=SERVER_SCOPE,
        )
        assert len(result.imported) == 2
        stored = [
            unit.store.get_revision(item.definition_id, item.revision)
            for item in result.imported
        ]
        assert all(digest.is_digest(row.content_digest) for row in stored)
        assert len({row.content_digest for row in stored}) == len(stored)


