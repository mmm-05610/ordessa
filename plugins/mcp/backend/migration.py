"""Q4 T09 (FR-12): the legacy ``server_assets``/``server_profile_assets`` →
MCP-domain migration surface.

This module is the migration side only: the compat deletion execution
belongs to C0 (integration-request item 4). It moves nothing it cannot
verify and rewrites nothing it inherits:

* every legacy revision file is copied **byte-for-byte** from the old assets
  root to the same relative path (``mcp/<asset_id>/<revision>/server.json``)
  under the new target root, then registered via
  :meth:`McpDefinitionStore.adopt_legacy_revision` **under the old digest**
  (no recompute, no normalisation on disk);
* ``server_profile_assets`` bindings become :class:`McpAssignment` rows
  (``decision=enable`` for enabled bindings with ``approvedRevision`` = the
  bound revision and an ``allObserved`` tool selection bound to the legacy
  joined digest; ``decision=disable`` for disabled bindings - a disable row
  carries no revision by model, the legacy reference is masked, never
  silently enabled);
* anything that does not verify is refused and listed honestly in the
  report's ``refusals`` - a digest mismatch between the ``server_assets``
  digest column and the legacy ``definition_digest`` of the revision file on
  disk, a binding whose file is gone, a colliding revision directory in the
  target root (reported as ``unknown`` and never overwritten), or an
  assignment row already owned by someone else. No data is invented for them.

Rollback safety is structural: the legacy database is only ever read through
a private temporary copy of the SQLite file (plus its -wal/-shm siblings),
and the target root must be a different root from the legacy assets root.
The legacy tables and files are never written, so the old server keeps
serving until C0 retires its write paths.

The digest function is the domain port of the legacy one
(``backend/definition.py``; V01 mutual proof in
``tests/test_definition_legacy_bytes.py`` pins the two as byte-identical),
so ``scan`` verifies exactly what ``McpAssetStore.verify`` used to.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional

from .assignment import McpAssignmentStore, assignment_key
from .definition import definition_digest
from .definition_store import McpDefinitionStore
from .errors import McpError

#: The server scope migrated rows are registered under when the caller does
#: not name one. ``serverScope`` distinguishes backend instances (data-model
#: §实体); the legacy database was single-instance, so one scope absorbs it.
LEGACY_SERVER_SCOPE = "legacy"

#: Provenance recorded on adopted revisions and approvals so a migrated row
#: is always recognisable as such.
MIGRATION_SOURCE = "q4-t09-legacy-migration"
MIGRATION_APPROVER = "q4-t09-legacy-migration"


def profile_principal(profile_id: str) -> str:
    """The migration principal for a Profile-scope assignment: the profile
    scope itself owns the row (``principal=profile scope``)."""
    return f"profile:{profile_id}"


def binding_operation_key(server_scope: str, profile_id: str, asset_id: str) -> str:
    """Deterministic operation key so a replayed migration replays, never
    double-writes."""
    return f"q4-t09:{server_scope}:{profile_id}:{asset_id}"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def snapshot_tree(root: Path | str) -> dict[str, str]:
    """sha256 of every file under ``root`` keyed by relative path. Used to
    prove the legacy side is byte-unchanged and the target side is
    change-free on a re-run."""
    base = Path(root)
    if not base.exists():
        return {}
    out: dict[str, str] = {}
    if base.is_file():
        out[base.name] = _sha256_bytes(base.read_bytes())
        return out
    for path in sorted(base.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(base))] = _sha256_bytes(path.read_bytes())
    return out


# -- read-only legacy database access ------------------------------------------


@contextlib.contextmanager
def _readonly_database(db_path: Path | str):
    """Yield a connection over a PRIVATE COPY of the legacy database file.

    Copying is what makes "the legacy DB never changes" structural rather
    than best-effort: SQLite's WAL bookkeeping may touch ``-wal``/``-shm``
    even for a read-only open, and a private copy means the migration can
    never alter the user's bytes (AGENTS rule 7 applies to real data roots;
    this function must be pointed at one by the operator, never at repo
    fixtures).
    """
    source = Path(db_path)
    if not source.is_file():
        raise ValueError(f"legacy database file not found: {source}")
    staging = Path(tempfile.mkdtemp(prefix="mcp-legacy-db-"))
    try:
        for suffix in ("", "-wal", "-shm"):
            sibling = Path(str(source) + suffix)
            if sibling.is_file():
                shutil.copy2(sibling, staging / sibling.name)
        conn = sqlite3.connect(str(staging / source.name))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        try:
            yield conn
        finally:
            conn.close()
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _asset_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, kind, name, description, latest_revision, digest, source,"
        " created_at, updated_at FROM server_assets WHERE kind='mcp' ORDER BY id"
    ).fetchall()
    return [dict(row) for row in rows]


def _binding_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The exact join ``AssetRecords.bindings`` performs (binding row plus
    the asset's kind/name/digest columns), restricted to mcp assets."""
    rows = conn.execute(
        "SELECT b.profile_id, b.asset_id, b.revision, b.enabled, a.kind, a.name,"
        " a.digest, a.latest_revision FROM server_profile_assets b"
        " JOIN server_assets a ON a.id = b.asset_id WHERE a.kind='mcp'"
        " ORDER BY b.profile_id, b.asset_id"
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["revision"] = int(item["revision"])
        item["latest_revision"] = int(item["latest_revision"])
        out.append(item)
    return out


# -- revision file scan ----------------------------------------------------------


def _revision_entries(assets_root: Path, asset_id: str) -> tuple[list[dict], list[str]]:
    base = assets_root / "mcp" / asset_id
    entries: list[dict[str, Any]] = []
    extras: list[str] = []
    if not base.is_dir():
        return entries, extras
    for child in sorted(base.iterdir(), key=lambda p: (p.name.isdigit(), p.name)):
        if not child.is_dir() or not child.name.isdigit():
            extras.append(child.name)
            continue
        revision = int(child.name)
        path = child / "server.json"
        entry: dict[str, Any] = {"revision": revision, "path": str(path), "name": None}
        if path.is_file():
            raw = path.read_bytes()
            try:
                canonical = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                entry.update(readable=False, status="unreadable", file_digest=None)
            else:
                entry.update(
                    readable=True,
                    file_digest=definition_digest(canonical),
                    name=canonical.get("name") if isinstance(canonical, Mapping) else None,
                    status="readable",
                )
        else:
            entry.update(readable=False, status="missing", file_digest=None)
        entries.append(entry)
    return entries, extras


def _classify_asset(row: Mapping[str, Any], revisions: list[dict], extras: list[str]) -> dict:
    """One inventory entry per legacy mcp asset row, with the digest-column
    cross-check against the revision file it attests (``latest_revision``).

    A file whose digest differs from the column is a ``digest-mismatch``; a
    missing/unreadable attestation file is reported under the same refusal
    group with its own reason. Revisions other than ``latest_revision`` are
    ``unattested`` (the column only ever digests the latest), recorded but
    not blamed.
    """
    latest = int(row["latest_revision"])
    latest_entry = next((e for e in revisions if e["revision"] == latest), None)
    status = "attested"
    reason = None
    if latest_entry is None:
        status = "digest-mismatch"
        reason = "attestation-file-missing"
    elif not latest_entry["readable"]:
        status = "digest-mismatch"
        reason = (
            "attestation-file-unreadable"
            if latest_entry["status"] == "unreadable" else "attestation-file-missing")
    elif latest_entry["file_digest"] != row["digest"]:
        status = "digest-mismatch"
        reason = "digest-column-differs-from-file"
    elif latest_entry["name"] != row["name"]:
        status = "name-mismatch"
        reason = "asset-name-differs-from-file"
    if latest_entry is not None and latest_entry["readable"] and status == "attested":
        latest_entry["status"] = "attested"
    elif latest_entry is not None and status == "digest-mismatch":
        latest_entry["status"] = "digest-mismatch"
    for entry in revisions:
        if entry is latest_entry:
            continue
        if entry["readable"]:
            entry["status"] = "unattested"
    return {
        "asset_id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "latest_revision": latest,
        "digest": row["digest"],
        "source": row.get("source"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "revisions": revisions,
        "unexpected_entries": extras,
        "status": status,
        "refusal_reason": reason,
    }


def scan_legacy(db_path: Path | str, assets_root: Path | str) -> dict[str, Any]:
    """Inventory the legacy MCP surface: ``server_assets`` rows of kind
    ``mcp``, their revision files under ``<assets_root>/mcp/<id>/<rev>/
    server.json``, and the ``server_profile_assets`` bindings.

    Nothing is fixed here - a digest-column mismatch or a binding whose file
    is gone is listed under ``refusals`` exactly as found, and the legacy
    side is only ever read (through a temporary copy, see
    :func:`_readonly_database`).
    """
    assets_root = Path(assets_root)
    with _readonly_database(db_path) as conn:
        rows = _asset_rows(conn)
        bindings = _binding_rows(conn)
    assets = []
    digest_mismatch = []
    for row in rows:
        revisions, extras = _revision_entries(assets_root, row["id"])
        asset = _classify_asset(row, revisions, extras)
        assets.append(asset)
        if asset["status"] != "attested":
            digest_mismatch.append({
                "asset_id": asset["asset_id"],
                "reason": asset["refusal_reason"],
                "column_digest": asset["digest"],
                "latest_revision": asset["latest_revision"],
                "file_digest": next(
                    (e["file_digest"] for e in asset["revisions"]
                     if e["revision"] == asset["latest_revision"]), None),
            })
    revision_index = {
        (a["asset_id"], e["revision"]): e for a in assets for e in a["revisions"]
    }
    dangling = []
    for binding in bindings:
        entry = revision_index.get((binding["asset_id"], binding["revision"]))
        present = bool(entry and entry["readable"])
        binding["file_status"] = "present" if present else "missing"
        if not present:
            dangling.append({
                "profile_id": binding["profile_id"],
                "asset_id": binding["asset_id"],
                "revision": binding["revision"],
                "reason": "revision-file-missing-or-unreadable",
            })
    return {
        "db_path": str(db_path),
        "assets_root": str(assets_root),
        "assets": assets,
        "bindings": bindings,
        "profiles": sorted({b["profile_id"] for b in bindings}),
        "refusals": {
            "digest-mismatch": digest_mismatch,
            "dangling-binding": dangling,
        },
    }


# -- migration ---------------------------------------------------------------------


def _assignment_lookup(assignments: McpAssignmentStore, *, server_scope: str,
                       profile_id: str, asset_id: str) -> Optional[dict]:
    key_json = json.dumps(assignment_key(
        server_scope=server_scope, scope_kind="profile", scope_id=profile_id,
        harness=None, definition_id=asset_id), sort_keys=True)
    return assignments._load()["rows"].get(key_json)


def migrate(
    db_path: Path | str,
    assets_root: Path | str,
    target_root: Path | str,
    *,
    dry_run: bool = False,
    server_scope: str = LEGACY_SERVER_SCOPE,
) -> dict[str, Any]:
    """Register every legacy (asset_id, revision) in a new MCP domain store
    under its OLD digest and turn every profile binding into an
    :class:`McpAssignment` row, idempotently.

    ``target_root`` is the new plugin data root (definitions land at
    ``<target_root>/mcp/<id>/<rev>/server.json``, assignments at
    ``<target_root>/assignments/assignments.json``) and must differ from the
    legacy assets root. ``dry_run=True`` returns the complete diff plan with
    zero writes anywhere. The report shape::

        {
          "dry_run": bool, "server_scope": str, "changed": int,
          "actions": [ {"op", "status", ...} ],   # planned|applied|unchanged|refused
          "refusals": {
             "digest-mismatch": [...], "dangling-binding": [...],
             "unknown": [...],            # target-side conflicts, never overwritten
             "assignment-conflict": [...], "blocked-asset": [...],
          },
          "inventory": scan_legacy result,
        }
    """
    assets_root = Path(assets_root)
    target_root = Path(target_root)
    if target_root.resolve() == assets_root.resolve():
        raise ValueError(
            "target_root must be independent of the legacy assets root "
            "(rollback safety: the legacy root is never the migration target)")
    inventory = scan_legacy(db_path, assets_root)
    definitions = McpDefinitionStore(target_root)
    assignments = McpAssignmentStore(target_root, definitions)

    actions: list[dict[str, Any]] = []
    refusals: dict[str, list[dict[str, Any]]] = {
        "digest-mismatch": [], "dangling-binding": [], "unknown": [],
        "assignment-conflict": [], "blocked-asset": [],
    }
    refused_assets = {
        item["asset_id"] for item in inventory["refusals"]["digest-mismatch"]
    }
    for asset in inventory["assets"]:
        if asset["status"] == "name-mismatch":
            refused_assets.add(asset["asset_id"])
            refusals["unknown"].append({
                "reason": "name-column-differs-from-file", "asset_id": asset["asset_id"],
            })
    for item in inventory["refusals"]["digest-mismatch"]:
        refusals["digest-mismatch"].append(item)

    # -- phase A: byte copy + adopt under the old digest ------------------------
    adopted: dict[tuple[str, int], dict[str, Any]] = {}
    for asset in inventory["assets"]:
        asset_id = asset["asset_id"]
        if asset["asset_id"] in refused_assets:
            actions.append({
                "op": "skip-asset", "asset_id": asset_id, "status": "refused",
                "reason": asset["refusal_reason"] or asset["status"],
            })
            continue
        for entry in asset["revisions"]:
            revision = entry["revision"]
            locator = {"asset_id": asset_id, "revision": revision}
            src = Path(entry["path"])
            if not entry["readable"]:
                refusals["unknown"].append({
                    **locator, "reason": f"revision-file-{entry['status']}"})
                continue
            source_bytes = src.read_bytes()
            dest = definitions.revision_dir(asset_id, revision) / "server.json"
            if dest.is_file():
                if dest.read_bytes() != source_bytes:
                    # A colliding target revision directory is unknown
                    # territory: report it, never overwrite it.
                    refusals["unknown"].append({
                        **locator, "reason": "target-revision-directory-conflict",
                        "overwritten": False,
                    })
                    continue
                actions.append({**locator, "op": "copy-revision", "status": "unchanged"})
            else:
                if not dry_run:
                    # Byte-faithful write through the store's staging+rename
                    # path, payload taken verbatim from the legacy file.
                    definitions._write_revision_file(asset_id, revision, source_bytes)
                actions.append({**locator, "op": "copy-revision",
                                "status": "planned" if dry_run else "applied"})
            record = definitions._load_index()["definitions"].get(asset_id)
            if record is not None and record.get("server_scope") != server_scope:
                refusals["unknown"].append({
                    **locator, "reason": "server-scope-conflict",
                    "record_scope": record.get("server_scope")})
                continue
            index_entry = (record or {}).get("revisions", {}).get(str(revision))
            if index_entry is not None:
                if index_entry["digest"] != entry["file_digest"]:
                    refusals["unknown"].append({
                        **locator, "reason": "index-digest-conflict",
                        "index_digest": index_entry["digest"],
                        "file_digest": entry["file_digest"]})
                    continue
                actions.append({**locator, "op": "adopt", "status": "unchanged",
                                "digest": index_entry["digest"]})
                adopted[(asset_id, revision)] = {"digest": index_entry["digest"]}
                continue
            if not dry_run:
                adopted_view = definitions.adopt_legacy_revision(
                    server_scope=server_scope, definition_id=asset_id, revision=revision,
                    source=MIGRATION_SOURCE, created_at=asset["created_at"])
                digest = adopted_view.canonical_digest
            else:
                digest = entry["file_digest"]
            actions.append({**locator, "op": "adopt",
                            "status": "planned" if dry_run else "applied",
                            "digest": digest})
            adopted[(asset_id, revision)] = {"digest": digest}

    # -- phase B: bindings -> McpAssignment --------------------------------------
    dangling_keys = {
        (item["profile_id"], item["asset_id"])
        for item in inventory["refusals"]["dangling-binding"]
    }
    approved_in_run: set[tuple[str, int]] = set()
    for binding in inventory["bindings"]:
        profile_id = binding["profile_id"]
        asset_id = binding["asset_id"]
        revision = binding["revision"]
        principal = profile_principal(profile_id)
        locator = {"profile_id": profile_id, "asset_id": asset_id, "revision": revision}
        if (profile_id, asset_id) in dangling_keys:
            refusals["dangling-binding"].append({**locator, "enabled": binding["enabled"],
                                                 "reason": "revision-file-missing"})
            actions.append({**locator, "op": "assign", "status": "refused",
                            "reason": "dangling-binding"})
            continue
        if asset_id in refused_assets:
            refusals["blocked-asset"].append({**locator, "reason": "asset-refused"})
            actions.append({**locator, "op": "assign", "status": "refused",
                            "reason": "blocked-by-asset-refusal"})
            continue
        if (asset_id, revision) not in adopted:
            refusals["unknown"].append({**locator, "reason": "revision-not-adopted"})
            actions.append({**locator, "op": "assign", "status": "refused",
                            "reason": "revision-not-adopted"})
            continue
        enabled = binding["enabled"]
        decision = "enable" if enabled else "disable"
        selection = ({"mode": "allObserved", "names": [], "catalogDigest": binding["digest"]}
                     if enabled else None)
        observed = {"catalogDigest": binding["digest"], "toolNames": []} if enabled else None
        expected = {
            "principal": principal, "decision": decision,
            "approved_revision": revision if enabled else None,
            "tool_selection": ({"mode": "allObserved", "names": [],
                                "catalog_digest": binding["digest"]} if enabled else None),
        }
        existing = _assignment_lookup(assignments, server_scope=server_scope,
                                      profile_id=profile_id, asset_id=asset_id)
        if existing is not None:
            if existing.get("principal") != principal:
                refusals["assignment-conflict"].append({
                    **locator, "reason": "row-owned-by-another-principal",
                    "owner": existing.get("principal")})
                actions.append({**locator, "op": "assign", "status": "refused",
                                "reason": "assignment-conflict"})
                continue
            if all(existing.get(field) == value for field, value in expected.items()):
                actions.append({**locator, "op": "assign", "status": "unchanged",
                                "decision": decision})
                continue
            refusals["assignment-conflict"].append({
                **locator, "reason": "existing-row-differs-from-legacy-binding"})
            actions.append({**locator, "op": "assign", "status": "refused",
                            "reason": "assignment-conflict"})
            continue
        if enabled and (asset_id, revision) not in approved_in_run:
            record = definitions._load_index()["definitions"].get(asset_id) or {}
            entry = record.get("revisions", {}).get(str(revision)) or {}
            if entry.get("approval") is None:
                if not dry_run:
                    definitions.approve_revision(
                        server_scope=server_scope, definition_id=asset_id,
                        revision=revision, actor=MIGRATION_APPROVER)
                actions.append({"op": "approve", **locator,
                                "status": "planned" if dry_run else "applied",
                                "actor": MIGRATION_APPROVER})
            else:
                actions.append({"op": "approve", **locator, "status": "unchanged",
                                "actor": entry["approval"]["actor"]})
            approved_in_run.add((asset_id, revision))
        try:
            if not dry_run:
                assignments.assign(
                    server_scope=server_scope, principal=principal, scope_kind="profile",
                    scope_id=profile_id, harness=None, definition_id=asset_id,
                    decision=decision, approved_revision=revision if enabled else None,
                    tool_selection=selection, observed_catalog=observed,
                    expected_row_version=0,
                    operation_key=binding_operation_key(server_scope, profile_id, asset_id))
            actions.append({**locator, "op": "assign",
                            "status": "planned" if dry_run else "applied",
                            "decision": decision, "principal": principal})
        except McpError as error:
            refusals["unknown"].append({**locator, "reason": "assign-refused",
                                        "code": error.code, "message": error.message})
            actions.append({**locator, "op": "assign", "status": "refused",
                            "reason": f"assign-refused:{error.code}"})

    changed = sum(1 for a in actions
                  if a["status"] == ("planned" if dry_run else "applied"))
    return {
        "dry_run": dry_run,
        "server_scope": server_scope,
        "target_root": str(target_root),
        "changed": changed,
        "actions": actions,
        "refusals": refusals,
        "inventory": inventory,
    }


# -- query equivalence ------------------------------------------------------------


def assignment_equivalence(bindings: list[dict[str, Any]], *, target_root: Path | str,
                           server_scope: str, profile_id: str) -> list[dict[str, Any]]:
    """Field-by-field mapping table between one Profile's legacy
    ``AssetRecords.bindings(profile_id)`` rows and the migrated assignment
    view read from the new stores.

    Field names differ by design; the values, ids and digests must be equal
    (``True`` per field). For a disabled binding the new model masks the
    revision/digest (a disable row is a mask without an approved revision),
    which is reported as ``"masked"`` rather than pretended equal.
    """
    definitions = McpDefinitionStore(target_root)
    assignments = McpAssignmentStore(target_root, definitions)
    principal = profile_principal(profile_id)
    rows: list[dict[str, Any]] = []
    for binding in bindings:
        view: dict[str, Any] = {"legacy": dict(binding)}
        try:
            assignment = assignments.get(
                server_scope=server_scope, principal=principal, scope_kind="profile",
                scope_id=profile_id, harness="any", definition_id=binding["assetId"])
            definition = definitions.get_definition(
                server_scope=server_scope, definition_id=binding["assetId"])
        except McpError as error:
            view["present"] = False
            view["error"] = error.code
            view["equal"] = False
            rows.append(view)
            continue
        enabled = binding["enabled"]
        migrated = {
            "definition_id": assignment.definition_id,
            "native_name": definition.native_name,
            "transport": definition.transport,
            "decision": assignment.decision,
            "approved_revision": assignment.approved_revision,
            "tool_selection": (None if assignment.tool_selection is None else {
                "mode": assignment.tool_selection.mode,
                "names": list(assignment.tool_selection.names),
                "catalog_digest": assignment.tool_selection.catalog_digest}),
            "principal": assignment.principal,
            "scope_id": assignment.scope_id,
        }
        equal = {
            "assetId==definition_id": binding["assetId"] == assignment.definition_id,
            "kind==mcp-definition-exists": (binding["kind"] == "mcp"
                                            and definition.archived is False),
            "name==native_name": binding["name"] == definition.native_name,
            "enabled==decision": enabled == (assignment.decision == "enable"),
            "revision==approved_revision": (
                binding["revision"] == assignment.approved_revision
                if enabled else "masked"),
            "digest==toolSelection.catalogDigest": (
                bool(assignment.tool_selection)
                and binding["digest"] == assignment.tool_selection.catalog_digest
                if enabled else "masked"),
        }
        view.update({"present": True, "migrated": migrated, "equal": equal})
        rows.append(view)
    return rows


def verify_migrated_digests(bindings: list[dict[str, Any]], *, target_root: Path | str,
                            server_scope: str, profile_id: str) -> list[dict[str, Any]]:
    """Cross-check each migrated enabled binding against the migrated bytes:
    ``verify_revision_digest`` (legacy ``McpAssetStore.verify`` semantics)
    over the file now living under the target root."""
    definitions = McpDefinitionStore(target_root)
    principal = profile_principal(profile_id)
    out = []
    for binding in bindings:
        if not binding["enabled"]:
            continue
        try:
            verified = definitions.verify_revision_digest(
                server_scope=server_scope, definition_id=binding["assetId"],
                revision=int(binding["revision"]), expected_digest=binding["digest"])
        except McpError as error:
            out.append({"asset_id": binding["assetId"], "revision": binding["revision"],
                        "verified": False, "error": error.code})
            continue
        out.append({"asset_id": binding["assetId"], "revision": binding["revision"],
                    "column_digest": binding["digest"], "verified": verified})
    return out
