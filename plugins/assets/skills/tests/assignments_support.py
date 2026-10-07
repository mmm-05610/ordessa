"""Shared fixtures for the assignments-domain tests (new in the skills
slice; only test-support code, no product behaviour).

Everything is built on `tmp_path` with the pinned `.venv/bin/python`; the
database is constructed exactly the way tests/test_library_kind_isolation.py
does (pacthold Database over a temp data root), so the new domain-owned
tables live in the same product SQLite file the library uses.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from pacthold_runtime_compat.storage import Database

from ordessa_skills.assignments.authorization import AssetAuthorization
from ordessa_skills.assignments.store import AssignmentScope, AssignmentStore
from ordessa_skills.library.records import AssetRecords
from ordessa_skills.library.revisions import RevisionApprovalStore
from ordessa_skills.library.store import SkillRevisionStore

SERVER_SCOPE = "srv-test"
PRINCIPAL = "user-1"


def make_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "data")
    database.initialize()
    return database


def make_skill(tmp_path: Path, *, database: Database, asset_id: str,
               revision: int, approve: bool = True,
               name: str | None = None, description: str = "A demo skill.",
               source: str | None = None,
               nested: bool = False) -> dict[str, Any]:
    """Install (+ optionally approve) one skill revision and register its
    catalogue row — the exact three facts the data model separates:
    installed, approved, referenced (README §内容修订与使用修订).

    ``nested`` puts the payload under an extra directory level: used to
    prove the resolver's order is a pure function of the assignment layers
    and cannot be moved by native folder depth (FR06).
    """
    root = tmp_path / "assets"
    store = SkillRevisionStore(root)
    staging = tmp_path / "src" / asset_id / str(revision)
    manifest = (f"---\nname: {name or asset_id}\n"
                f"description: {description}\n---\n\nBody r{revision}.\n")
    if nested:
        (staging / "resources" / "deep").mkdir(parents=True, exist_ok=True)
        (staging / "SKILL.md").write_text(manifest, encoding="utf-8")
        (staging / "resources" / "deep" / "note.md").write_text(
            "nested payload\n", encoding="utf-8")
    else:
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "SKILL.md").write_text(manifest, encoding="utf-8")
    facts = store.install(staging, asset_id=asset_id, revision=revision)
    records = AssetRecords(database)
    records.publish(kind="skill", name=facts["name"], revision=revision,
                    digest=facts["tree_digest"], description=facts["description"],
                    source=source, asset_id=asset_id)
    approvals = RevisionApprovalStore(root, store=store)
    if approve:
        approvals.approve(asset_id=asset_id, revision=revision,
                          approved_by="tester")
    return {"facts": facts, "store": store, "approvals": approvals,
            "records": records}


def make_store(database: Database, *, approvals: Any = None,
               server_scope: str = SERVER_SCOPE,
               principal: str = PRINCIPAL) -> AssignmentStore:
    store = AssignmentStore(database, scope=AssignmentScope(
        server_scope=server_scope, principal=principal), approvals=approvals)
    store.ensure_schema()
    return store


def make_authorization(*, workspaces: Sequence[str] | None = None,
                       server_scope: str = SERVER_SCOPE) -> AssetAuthorization:
    """AssetAuthorization wired to a fake WorkspaceLookup: only the listed
    projectIds exist in this data domain (api-requests.md §G5 独立路径 —
    existence check through the injected registry, no host import)."""
    lookup = FakeWorkspaceLookup(workspaces or ())
    return AssetAuthorization(workspace_lookup=lookup, server_scope=server_scope)


class FakeWorkspaceLookup:
    def __init__(self, ids: Sequence[str]) -> None:
        self._ids = set(ids)

    def get(self, workspace_id: str) -> Mapping[str, Any] | None:
        if workspace_id not in self._ids:
            return None
        return {"id": workspace_id, "archived_at": None}


class FakeProfileLayer:
    """Stand-in for Z1's `assets.skills` facet (api-requests.md G3)."""

    def __init__(self, *, harness: str | None = "pi",
                 entries: Sequence[Any] = (),
                 revision_identity: Mapping[str, Any] | None = None) -> None:
        self.harness = harness
        self.entries = list(entries)
        self._revision_identity = dict(revision_identity or {
            "configRevision": 1,
            "configObjectDigest": "sha256:" + "1" * 64})

    def skill_entries(self, profile_id: str) -> list[Any]:
        return list(self.entries)

    def harness_id(self, profile_id: str) -> str | None:
        return self.harness

    def revision_identity(self, profile_id: str) -> Mapping[str, Any]:
        return dict(self._revision_identity, profileId=profile_id)


class FakeMandatoryPolicy:
    """Stand-in for the admin/permissions layer (verification.md G06 管理员
    强制规则; awaiting the real permissions-api)."""

    def __init__(self, rules: Sequence[Any] = ()) -> None:
        self.ruleset = list(rules)

    def rules(self, *, principal: str, project_id: str | None,
              harness_id: str | None) -> list[Any]:
        return list(self.ruleset)
