"""Revision store for MCP definitions.

Disk layout is the legacy one, unchanged:
``<root>/mcp/<definition_id>/<revision>/server.json``, 0o644, written through
a staging directory and one ``os.rename`` so a reader never sees a partial
file, and an existing revision is never overwritten (``MCP_REVISION_EXISTS``).

On top of the legacy layout the store keeps one JSON index
(``<root>/mcp/index.json``) with the definition records (server scope,
archived flag, latest revision, per-revision digest/source/approval) and an
operation-key journal for CAS/idempotent replay.

Concurrency policy: every index mutation runs under an exclusive
``fcntl.flock`` on ``<root>/mcp/.lock`` covering read-modify-write of the
index; revision files themselves are immutable and renamed in, so file writes
and index commits are each atomic on their own.

Saving has zero side effects: no probe, no spawn, no network, no native
config write - it only canonicalises, digests and stores.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from .definition import (
    ApprovalRecord,
    McpDefinition,
    McpRevision,
    _NAME,
    canonical_definition,
    canonical_definition_v2,
    definition_digest,
    revision_model,
)
from .errors import (
    MCP_ASSET_MISSING,
    MCP_CAS_CONFLICT,
    MCP_DEFINITION_INVALID,
    MCP_NAME_INVALID,
    MCP_OPERATION_CONFLICT,
    MCP_REVISION_EXISTS,
    MCP_SERVER_SCOPE_CONFLICT,
    McpError,
)

_INDEX_VERSION = 1


def _validate_definition_id(definition_id: str) -> str:
    """Ids are directory names under the root: the legacy slug rule applies."""
    if not isinstance(definition_id, str) or _NAME.fullmatch(definition_id) is None:
        raise McpError(MCP_NAME_INVALID, "name must be a lowercase slug")
    return definition_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(canonical: Mapping[str, Any]) -> bytes:
    return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")


class McpDefinitionStore:
    """Install and manage MCP server definitions as immutable revisions."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- legacy-faithful file layout -------------------------------------------

    def revision_dir(self, definition_id: str, revision: int) -> Path:
        return self.root / "mcp" / definition_id / str(revision)

    def _revision_path(self, definition_id: str, revision: int) -> Path:
        return self.revision_dir(definition_id, revision) / "server.json"

    def _write_revision_file(self, definition_id: str, revision: int, payload: bytes) -> None:
        destination = self.revision_dir(definition_id, revision)
        if destination.exists():
            raise McpError(
                MCP_REVISION_EXISTS, f"revision {revision} of {definition_id} already exists",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="mcp-staging-", dir=str(destination.parent)))
        try:
            (staging / "server.json").write_bytes(payload)
            os.chmod(staging / "server.json", 0o644)
            os.rename(staging, destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    # -- index ------------------------------------------------------------------

    @contextmanager
    def _lock(self) -> Iterator[None]:
        (self.root / "mcp").mkdir(parents=True, exist_ok=True)
        with open(self.root / "mcp" / ".lock", "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _index_path(self) -> Path:
        return self.root / "mcp" / "index.json"

    def _load_index(self) -> dict:
        path = self._index_path()
        if not path.is_file():
            return {"version": _INDEX_VERSION, "definitions": {}, "operations": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def _commit_index(self, index: dict) -> None:
        path = self._index_path()
        staging = Path(tempfile.mkdtemp(prefix="mcp-index-", dir=str(path.parent)))
        try:
            payload = json.dumps(index, sort_keys=True, separators=(",", ":"), indent=1)
            tmp = staging / "index.json"
            tmp.write_text(payload, encoding="utf-8")
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _scope_guard(record: Mapping[str, Any], server_scope: str, definition_id: str) -> None:
        if record.get("server_scope") != server_scope:
            raise McpError(
                MCP_SERVER_SCOPE_CONFLICT,
                f"definition {definition_id} belongs to another server scope",
            )

    @staticmethod
    def _definition_record(index: dict, definition_id: str) -> Optional[dict]:
        return index["definitions"].get(definition_id)

    @staticmethod
    def _model(record: Mapping[str, Any]) -> McpDefinition:
        return McpDefinition(
            server_scope=record["server_scope"],
            definition_id=record["definition_id"],
            native_name=record["native_name"],
            transport=record["transport"],
            archived=bool(record["archived"]),
            latest_revision=int(record["latest_revision"]),
        )

    # -- reads -------------------------------------------------------------------

    def get_definition(self, *, server_scope: str, definition_id: str) -> McpDefinition:
        _validate_definition_id(definition_id)
        with self._lock():
            record = self._definition_record(self._load_index(), definition_id)
        if record is None:
            raise McpError(MCP_ASSET_MISSING, f"definition {definition_id} is not installed")
        if record.get("server_scope") != server_scope:
            # A foreign scope must not learn whether the id exists at all.
            raise McpError(MCP_ASSET_MISSING, f"definition {definition_id} is not installed")
        return self._model(record)

    def list_definitions(self, *, server_scope: str) -> list:
        with self._lock():
            index = self._load_index()
        return [
            self._model(record)
            for record in sorted(index["definitions"].values(), key=lambda r: r["definition_id"])
            if record.get("server_scope") == server_scope
        ]

    def read_revision(
        self, *, server_scope: str, definition_id: str, revision: int,
    ) -> McpRevision:
        """Return one revision as a v2 model; legacy files are normalised,
        verified under their stored digest, and never rewritten or re-digested."""
        _validate_definition_id(definition_id)
        with self._lock():
            record = self._definition_record(self._load_index(), definition_id)
        if record is None or record.get("server_scope") != server_scope:
            # A foreign scope must not learn whether the id exists at all.
            raise McpError(MCP_ASSET_MISSING, "the MCP revision is not installed")
        revisions = record["revisions"].get(str(revision))
        if revisions is None:
            raise McpError(MCP_ASSET_MISSING, "the MCP revision is not installed")
        path = self._revision_path(definition_id, revision)
        if not path.is_file():
            raise McpError(MCP_ASSET_MISSING, "the MCP revision is not installed")
        canonical = json.loads(path.read_text(encoding="utf-8"))
        digest = definition_digest(canonical)
        if digest != revisions["digest"]:
            raise McpError(
                MCP_DEFINITION_INVALID,
                f"revision {revision} of {definition_id} no longer matches its digest",
            )
        approval = revisions.get("approval")
        return revision_model(
            definition_id=definition_id,
            revision=revision,
            canonical=canonical,
            canonical_digest=digest,
            shape=revisions.get("shape", "legacy"),
            source=revisions.get("source"),
            created_at=revisions.get("created_at", ""),
            approval=(
                ApprovalRecord(actor=approval["actor"], approved_at=approval["approved_at"])
                if approval else None
            ),
        )

    def verify_revision_digest(
        self, *, server_scope: str, definition_id: str, revision: int, expected_digest: str,
    ) -> bool:
        """Legacy ``McpAssetStore.verify`` semantics: digest the stored file."""
        _validate_definition_id(definition_id)
        with self._lock():
            record = self._definition_record(self._load_index(), definition_id)
        if record is not None:
            self._scope_guard(record, server_scope, definition_id)
        path = self._revision_path(definition_id, revision)
        if not path.is_file():
            raise McpError(MCP_ASSET_MISSING, "the MCP revision is not installed")
        return definition_digest(json.loads(path.read_text(encoding="utf-8"))) == expected_digest

    def read_legacy_revision(self, *, definition_id: str, revision: int) -> dict:
        """Read a pre-index legacy file verbatim (migration-time access)."""
        path = self._revision_path(definition_id, revision)
        if not path.is_file():
            raise McpError(MCP_ASSET_MISSING, "the MCP revision is not installed")
        return json.loads(path.read_text(encoding="utf-8"))

    # -- writes -------------------------------------------------------------------

    def install_legacy(self, definition: Mapping[str, Any], *, asset_id: str,
                       revision: int) -> dict:
        """Byte-faithful copy of the legacy ``McpAssetStore.install``.

        Used only by the V01/V09 mutual-proof path and T09 migration; it
        writes no index record. New saves must use :meth:`save_revision`.
        """
        canonical = canonical_definition(definition)
        payload = _canonical_bytes(canonical)
        self._write_revision_file(asset_id, revision, payload)
        return {
            "asset_id": asset_id,
            "kind": "mcp",
            "revision": revision,
            "digest": definition_digest(canonical),
            "name": canonical["name"],
            "transport": next(iter(canonical["transport"])),
        }

    def adopt_legacy_revision(
        self, *, server_scope: str, definition_id: str, revision: int,
        source: Optional[str] = None, created_at: Optional[str] = None,
    ) -> McpRevision:
        """Register an on-disk legacy revision in the index under its OLD digest.

        The stored bytes are verified against the legacy digest and kept
        as-is; the model is a read-time normalisation (migration mapping),
        never a rewrite or a silent recompute.
        """
        _validate_definition_id(definition_id)
        path = self._revision_path(definition_id, revision)
        if not path.is_file():
            raise McpError(MCP_ASSET_MISSING, "the MCP revision is not installed")
        canonical = json.loads(path.read_text(encoding="utf-8"))
        digest = definition_digest(canonical)
        kind = next(iter(canonical.get("transport", {})), None)
        if kind not in ("stdio", "remote"):
            raise McpError(MCP_DEFINITION_INVALID, "stored revision is not a known transport")
        with self._lock():
            index = self._load_index()
            record = self._definition_record(index, definition_id)
            if record is None:
                record = self._new_record(
                    index, server_scope=server_scope, definition_id=definition_id,
                    native_name=canonical["name"], transport=kind,
                )
            else:
                self._scope_guard(record, server_scope, definition_id)
            key = str(revision)
            entry = record["revisions"].get(key)
            if entry is not None:
                if entry["digest"] != digest:
                    raise McpError(
                        MCP_DEFINITION_INVALID,
                        f"revision {revision} of {definition_id} no longer matches its digest",
                    )
            else:
                record["revisions"][key] = {
                    "digest": digest, "shape": "legacy", "source": source,
                    "created_at": created_at or _now(), "approval": None,
                }
                record["latest_revision"] = max(int(record["latest_revision"]), revision)
                self._commit_index(index)
        return self.read_revision(
            server_scope=server_scope, definition_id=definition_id, revision=revision)

    @staticmethod
    def _new_record(index: dict, *, server_scope: str, definition_id: str,
                    native_name: str, transport: str) -> dict:
        record = {
            "server_scope": server_scope,
            "definition_id": definition_id,
            "native_name": native_name,
            "transport": transport,
            "archived": False,
            "latest_revision": 0,
            "revisions": {},
        }
        index["definitions"][definition_id] = record
        return record

    def _replay(self, index: dict, operation_key: str, request_digest: str) -> Optional[dict]:
        entry = index.get("operations", {}).get(operation_key)
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

    @staticmethod
    def _request_digest(fields: Mapping[str, Any]) -> str:
        return definition_digest(fields)

    def _record_operation(
        self, index: dict, operation_key: str, request_digest: str, result: dict,
    ) -> None:
        stored = dict(result)
        stored.pop("replayed", None)
        index.setdefault("operations", {})[operation_key] = {
            "request_digest": request_digest, "result": stored,
        }

    def save_revision(
        self, *, server_scope: str, definition_id: str, definition: Mapping[str, Any],
        expected_version: int, operation_key: str, source: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> dict:
        """CAS save of one immutable v2 revision.

        ``expected_version`` is the caller's view of ``latest_revision`` (0 for
        a first save); the new revision number is ``expected_version + 1``.
        Same ``operation_key`` + same request replays the stored result; same
        key with different content is refused. Zero side effects beyond the
        revision file and the index.
        """
        _validate_definition_id(definition_id)
        canonical = canonical_definition_v2(definition)
        digest = definition_digest(canonical)
        kind = next(iter(canonical["transport"]))
        request_digest = self._request_digest({
            "server_scope": server_scope,
            "definition_id": definition_id,
            "expected_version": expected_version,
            "operation_key": operation_key,
            "revision_canonical": canonical,
            "source": source,
        })
        with self._lock():
            index = self._load_index()
            replayed = self._replay(index, operation_key, request_digest)
            if replayed is not None:
                return replayed
            record = self._definition_record(index, definition_id)
            if record is not None:
                self._scope_guard(record, server_scope, definition_id)
            if int((record or {}).get("latest_revision", 0)) != expected_version:
                raise McpError(
                    MCP_CAS_CONFLICT,
                    f"expected version {expected_version} but {definition_id} is at "
                    f"{(record or {}).get('latest_revision', 0)}",
                )
            revision = expected_version + 1
            self._write_revision_file(definition_id, revision, _canonical_bytes(canonical))
            if record is None:
                record = self._new_record(
                    index, server_scope=server_scope, definition_id=definition_id,
                    native_name=canonical["name"], transport=kind,
                )
            record["revisions"][str(revision)] = {
                "digest": digest, "shape": "v2", "source": source,
                "created_at": created_at or _now(), "approval": None,
            }
            record["latest_revision"] = revision
            result = {
                "server_scope": server_scope,
                "definition_id": definition_id,
                "revision": revision,
                "digest": digest,
                "transport": kind,
                "replayed": False,
            }
            self._record_operation(index, operation_key, request_digest, result)
            self._commit_index(index)
        return result

    def approve_revision(
        self, *, server_scope: str, definition_id: str, revision: int, actor: str,
        approved_at: Optional[str] = None,
    ) -> dict:
        """Record who approved which revision, at when. Approval is itself
        idempotent; it never touches the revision bytes."""
        _validate_definition_id(definition_id)
        with self._lock():
            index = self._load_index()
            record = self._definition_record(index, definition_id)
            if record is None:
                raise McpError(MCP_ASSET_MISSING, "the MCP revision is not installed")
            self._scope_guard(record, server_scope, definition_id)
            entry = record["revisions"].get(str(revision))
            if entry is None:
                raise McpError(MCP_ASSET_MISSING, "the MCP revision is not installed")
            if entry.get("approval") is None:
                entry["approval"] = {"actor": actor, "approved_at": approved_at or _now()}
                self._commit_index(index)
            return {"definition_id": definition_id, "revision": revision,
                    "approval": dict(entry["approval"])}

    def archive_definition(self, *, server_scope: str, definition_id: str) -> McpDefinition:
        """Archive only blocks NEW assignments; revisions and files stay put."""
        _validate_definition_id(definition_id)
        with self._lock():
            index = self._load_index()
            record = self._definition_record(index, definition_id)
            if record is None:
                raise McpError(MCP_ASSET_MISSING, f"definition {definition_id} is not installed")
            self._scope_guard(record, server_scope, definition_id)
            if not record["archived"]:
                record["archived"] = True
                self._commit_index(index)
            return self._model(record)
