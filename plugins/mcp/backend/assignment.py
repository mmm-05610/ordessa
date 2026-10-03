"""Scope assignments: user-default / project / profile / session decisions.

Storage is the domain's own plugin data root (per the T00 decision: no
pacthold central schema change request): a single JSON table
``<root>/assignments/assignments.json`` keyed by
``(server_scope, scope_kind, scope_id, harness, definition_id)`` plus an
operation journal. Concurrency policy matches the definition store: an
exclusive ``fcntl.flock`` around each read-modify-write, ``os.replace``
commit, and ``rowVersion`` CAS on every mutation.

Principal isolation is load-bearing: every row records its owning principal,
and any read or mutation whose principal/serverScope does not match the row
is refused before the row content is revealed (``MCP_OWNER_CONFLICT`` /
``MCP_ASSET_MISSING`` - a foreign caller never learns the row exists).
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, Tuple

from .definition import definition_digest
from .definition_store import McpDefinitionStore
from .errors import (
    MCP_ASSET_MISSING,
    MCP_ASSIGNMENT_INVALID,
    MCP_CAS_CONFLICT,
    MCP_CATALOG_MISSING,
    MCP_DEFINITION_ARCHIVED,
    MCP_OPERATION_CONFLICT,
    MCP_OWNER_CONFLICT,
    MCP_REVISION_NOT_APPROVED,
    MCP_TOOL_NOT_OBSERVED,
    McpError,
)

SCOPE_KINDS = ("user-default", "project", "profile", "session")
_DECISIONS = ("enable", "disable", "inherit")
_HARNESS_ANY = "any"
_SELECTION_MODES = ("allowNames", "allObserved")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ToolSelection:
    mode: str  # "allowNames" | "allObserved"
    names: Tuple[str, ...]
    catalog_digest: str


@dataclass(frozen=True)
class McpAssignment:
    server_scope: str
    principal: str
    scope_kind: str
    scope_id: str
    harness: str  # harness id or "any"
    definition_id: str
    decision: str  # "enable" | "disable"
    approved_revision: Optional[int]
    tool_selection: Optional[ToolSelection]
    row_version: int
    updated_at: str

    @property
    def key(self) -> tuple:
        return (self.server_scope, self.scope_kind, self.scope_id, self.harness,
                self.definition_id)


def assignment_key(*, server_scope: str, scope_kind: str, scope_id: str,
                   harness: str, definition_id: str) -> tuple:
    return (server_scope, scope_kind, scope_id, harness or _HARNESS_ANY, definition_id)


def _normalise_selection(selection: Mapping[str, Any]) -> ToolSelection:
    if not isinstance(selection, Mapping):
        raise McpError(MCP_ASSIGNMENT_INVALID, "toolSelection must be an object")
    mode = selection.get("mode")
    if mode not in _SELECTION_MODES:
        raise McpError(
            MCP_ASSIGNMENT_INVALID, f"toolSelection mode must be one of {_SELECTION_MODES}")
    catalog_digest = selection.get("catalogDigest")
    if not isinstance(catalog_digest, str) or not catalog_digest:
        raise McpError(MCP_ASSIGNMENT_INVALID, "toolSelection must bind a catalogDigest")
    if mode == "allObserved":
        names = selection.get("names")
        if names is None:
            raise McpError(
                MCP_ASSIGNMENT_INVALID, "allObserved must freeze the observed names")
        names = tuple(names)
    else:
        names = selection.get("names")
        if (not isinstance(names, (list, tuple)) or not names
                or any(not isinstance(n, str) or not n for n in names)):
            raise McpError(MCP_ASSIGNMENT_INVALID, "allowNames needs a non-empty name list")
        names = tuple(names)
    return ToolSelection(mode=mode, names=names, catalog_digest=catalog_digest)


def _check_names_against_catalog(names: Tuple[str, ...], observed) -> None:
    if observed is None:
        raise McpError(
            MCP_CATALOG_MISSING,
            "a catalog observation must be supplied for tool selection at assign time",
        )
    for name in names:
        if name not in observed:
            raise McpError(
                MCP_TOOL_NOT_OBSERVED,
                f"tool {name!r} is not in the approved revision's observed catalog",
            )


class McpAssignmentStore:
    """Assign enable/disable decisions per scope with rowVersion CAS."""

    def __init__(self, root: Path | str, definitions: McpDefinitionStore) -> None:
        self.root = Path(root)
        self.definitions = definitions

    # -- plumbing -----------------------------------------------------------------

    @contextmanager
    def _lock(self) -> Iterator[None]:
        (self.root / "assignments").mkdir(parents=True, exist_ok=True)
        with open(self.root / "assignments" / ".lock", "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _table_path(self) -> Path:
        return self.root / "assignments" / "assignments.json"

    def _load(self) -> dict:
        path = self._table_path()
        if not path.is_file():
            return {"version": 1, "rows": {}, "operations": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _commit(self, table: dict) -> None:
        path = self._table_path()
        staging = Path(tempfile.mkdtemp(prefix="mcp-assign-", dir=str(path.parent)))
        try:
            tmp = staging / "assignments.json"
            tmp.write_text(
                json.dumps(table, sort_keys=True, separators=(",", ":"), indent=1),
                encoding="utf-8")
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _row_model(row: Mapping[str, Any]) -> McpAssignment:
        selection = row.get("tool_selection")
        return McpAssignment(
            server_scope=row["server_scope"], principal=row["principal"],
            scope_kind=row["scope_kind"], scope_id=row["scope_id"],
            harness=row["harness"], definition_id=row["definition_id"],
            decision=row["decision"], approved_revision=row.get("approved_revision"),
            tool_selection=(
                ToolSelection(mode=selection["mode"], names=tuple(selection["names"]),
                              catalog_digest=selection["catalog_digest"])
                if selection else None),
            row_version=int(row["row_version"]), updated_at=row.get("updated_at", ""),
        )

    @staticmethod
    def _row_payload(row: Mapping[str, Any]) -> dict:
        return json.loads(json.dumps(row, sort_keys=True))

    # -- reads ----------------------------------------------------------------------

    def get(self, *, server_scope: str, principal: str, scope_kind: str, scope_id: str,
            harness: str, definition_id: str) -> McpAssignment:
        key = assignment_key(server_scope=server_scope, scope_kind=scope_kind,
                             scope_id=scope_id, harness=harness, definition_id=definition_id)
        with self._lock():
            row = self._load()["rows"].get(json.dumps(key, sort_keys=True))
        if row is None:
            raise McpError(MCP_ASSET_MISSING, "no assignment record for that target")
        if row.get("principal") != principal:
            raise McpError(
                MCP_OWNER_CONFLICT,
                "this assignment belongs to another principal and cannot be read",
            )
        return self._row_model(row)

    def list_for(self, *, server_scope: str, principal: str) -> list:
        with self._lock():
            rows = self._load()["rows"]
        return [
            self._row_model(row)
            for key in sorted(rows)
            if (row := rows[key])["server_scope"] == server_scope
            and row["principal"] == principal
        ]

    # -- writes -----------------------------------------------------------------------

    def _replay(self, table: dict, operation_key: str, request_digest: str) -> Optional[dict]:
        entry = table.get("operations", {}).get(operation_key)
        if entry is None:
            return None
        if entry["request_digest"] != request_digest:
            raise McpError(
                MCP_OPERATION_CONFLICT,
                f"operation key {operation_key!r} was already used with different content",
            )
        result = dict(entry["result"])
        result["replayed"] = True
        return result

    def assign(
        self, *, server_scope: str, principal: str, scope_kind: str, scope_id: str,
        harness: Optional[str], definition_id: str, decision: str,
        approved_revision: Optional[int] = None,
        tool_selection: Optional[Mapping[str, Any]] = None,
        observed_catalog: Optional[Mapping[str, Any]] = None,
        expected_row_version: int, operation_key: str,
    ) -> dict:
        """CAS-write one assignment row; ``inherit`` deletes the record.

        ``observed_catalog`` is the catalog injected for this (revision,
        target) pair - ``{"catalogDigest": str, "toolNames": [...]}``. Before
        T03 the caller injects it; a selection can never name tools the
        approved revision's observation did not contain.
        """
        if scope_kind not in SCOPE_KINDS:
            raise McpError(
                MCP_ASSIGNMENT_INVALID, f"scopeKind must be one of {SCOPE_KINDS}")
        if decision not in _DECISIONS:
            raise McpError(MCP_ASSIGNMENT_INVALID, f"decision must be one of {_DECISIONS}")
        if decision == "inherit":
            return self.unassign(
                server_scope=server_scope, principal=principal, scope_kind=scope_kind,
                scope_id=scope_id, harness=harness, definition_id=definition_id,
                expected_row_version=expected_row_version, operation_key=operation_key)
        selection = _normalise_selection(tool_selection) if tool_selection else None
        request_digest = definition_digest({
            "server_scope": server_scope, "principal": principal, "scope_kind": scope_kind,
            "scope_id": scope_id, "harness": harness or _HARNESS_ANY,
            "definition_id": definition_id, "decision": decision,
            "approved_revision": approved_revision,
            "tool_selection": dict(selection.__dict__) if selection else None,
            "observed_catalog": dict(observed_catalog) if observed_catalog else None,
            "expected_row_version": expected_row_version, "operation_key": operation_key,
        })
        key_json = json.dumps(assignment_key(
            server_scope=server_scope, scope_kind=scope_kind, scope_id=scope_id,
            harness=harness, definition_id=definition_id), sort_keys=True)
        with self._lock():
            table = self._load()
            replayed = self._replay(table, operation_key, request_digest)
            if replayed is not None:
                return replayed
            existing = table["rows"].get(key_json)
            if existing is not None and existing.get("principal") != principal:
                raise McpError(
                    MCP_OWNER_CONFLICT,
                    "another principal already owns this assignment target",
                )
            current_version = int(existing["row_version"]) if existing else 0
            if current_version != expected_row_version:
                raise McpError(
                    MCP_CAS_CONFLICT,
                    f"expected row version {expected_row_version} but the record is at "
                    f"{current_version}",
                )
            if decision == "enable":
                self._guard_enable(
                    server_scope=server_scope, definition_id=definition_id,
                    approved_revision=approved_revision, selection=selection,
                    observed_catalog=observed_catalog,
                    existing_selection=(
                        self._row_model(existing).tool_selection if existing else None),
                )
            elif selection is not None or observed_catalog is not None:
                raise McpError(
                    MCP_ASSIGNMENT_INVALID, "only enable carries a revision or tool selection")
            row = {
                "server_scope": server_scope, "principal": principal,
                "scope_kind": scope_kind, "scope_id": scope_id,
                "harness": (harness or _HARNESS_ANY) if scope_kind in ("user-default", "project")
                else _HARNESS_ANY,
                "definition_id": definition_id, "decision": decision,
                "approved_revision": approved_revision if decision == "enable" else None,
                "tool_selection": (
                    {"mode": selection.mode, "names": list(selection.names),
                     "catalog_digest": selection.catalog_digest}
                    if decision == "enable" and selection else None),
                "row_version": current_version + 1,
                "updated_at": _now(),
            }
            table["rows"][key_json] = row
            result = {
                "assignment": {
                    "scope_kind": row["scope_kind"], "scope_id": row["scope_id"],
                    "harness": row["harness"], "definition_id": row["definition_id"],
                    "decision": row["decision"], "approved_revision": row["approved_revision"],
                    "row_version": row["row_version"],
                },
                "replayed": False,
            }
            table.setdefault("operations", {})[operation_key] = {
                "request_digest": request_digest, "result": self._row_payload(result),
            }
            self._commit(table)
        return result

    def _guard_enable(self, *, server_scope: str, definition_id: str,
                      approved_revision, selection, observed_catalog,
                      existing_selection) -> None:
        if approved_revision is None:
            raise McpError(
                MCP_ASSIGNMENT_INVALID,
                "enable must name the approved revision it binds to",
            )
        definition = self.definitions.get_definition(
            server_scope=server_scope, definition_id=definition_id)
        if definition.archived:
            raise McpError(
                MCP_DEFINITION_ARCHIVED,
                f"definition {definition_id} is archived and blocks new assignments",
            )
        revision = self.definitions.read_revision(
            server_scope=server_scope, definition_id=definition_id,
            revision=int(approved_revision))
        if revision.approval is None:
            raise McpError(
                MCP_REVISION_NOT_APPROVED,
                f"revision {approved_revision} of {definition_id} has no approval record",
            )
        if selection is None:
            raise McpError(
                MCP_ASSIGNMENT_INVALID,
                "enable must freeze a tool selection alongside the revision",
            )
        observed_names = None
        observed_digest = None
        if observed_catalog is not None:
            observed_names = set(observed_catalog.get("toolNames", ()))
            observed_digest = observed_catalog.get("catalogDigest")
        if selection.mode == "allObserved":
            if observed_catalog is None:
                raise McpError(
                    MCP_CATALOG_MISSING,
                    "allObserved must bind the current catalog observation",
                )
            if selection.catalog_digest != observed_digest:
                raise McpError(
                    MCP_CATALOG_MISSING,
                    "allObserved must bind the digest of the supplied catalog observation",
                )
            if set(selection.names) != observed_names:
                raise McpError(
                    MCP_TOOL_NOT_OBSERVED,
                    "allObserved must freeze exactly the tools of the bound catalog",
                )
        else:
            if observed_catalog is None:
                raise McpError(
                    MCP_CATALOG_MISSING,
                    "allowNames must be checked against a supplied catalog observation",
                )
            if selection.catalog_digest != observed_digest:
                raise McpError(
                    MCP_CATALOG_MISSING,
                    "allowNames must bind the digest of the supplied catalog observation",
                )
            _check_names_against_catalog(selection.names, observed_names)

    def unassign(self, *, server_scope: str, principal: str, scope_kind: str, scope_id: str,
                 harness: Optional[str], definition_id: str, expected_row_version: int,
                 operation_key: str) -> dict:
        """``inherit`` = delete the record so resolution falls through."""
        request_digest = definition_digest({
            "op": "unassign", "server_scope": server_scope, "principal": principal,
            "scope_kind": scope_kind, "scope_id": scope_id,
            "harness": harness or _HARNESS_ANY, "definition_id": definition_id,
            "expected_row_version": expected_row_version, "operation_key": operation_key,
        })
        key_json = json.dumps(assignment_key(
            server_scope=server_scope, scope_kind=scope_kind, scope_id=scope_id,
            harness=harness, definition_id=definition_id), sort_keys=True)
        with self._lock():
            table = self._load()
            replayed = self._replay(table, operation_key, request_digest)
            if replayed is not None:
                return replayed
            existing = table["rows"].get(key_json)
            if existing is not None and existing.get("principal") != principal:
                raise McpError(
                    MCP_OWNER_CONFLICT,
                    "this assignment belongs to another principal and cannot be changed",
                )
            current_version = int(existing["row_version"]) if existing else 0
            if current_version != expected_row_version:
                raise McpError(
                    MCP_CAS_CONFLICT,
                    f"expected row version {expected_row_version} but the record is at "
                    f"{current_version}",
                )
            if existing is not None:
                del table["rows"][key_json]
            result = {
                "scope_kind": scope_kind, "scope_id": scope_id,
                "harness": harness or _HARNESS_ANY, "definition_id": definition_id,
                "decision": "inherit", "removed": existing is not None, "replayed": False,
            }
            table.setdefault("operations", {})[operation_key] = {
                "request_digest": request_digest, "result": self._row_payload(result),
            }
            self._commit(table)
        return result
