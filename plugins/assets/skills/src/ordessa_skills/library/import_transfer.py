"""The bounded import session (import_transfer.py).

Ported unchanged from
`plugins/assets/src/ordessa_assets/server/import_transfer.py` @ 752f148b1b
(research-and-reuse.md 分块导入 row: 复用 begin/chunk/preview/commit 校验及漂移
反例). Protocol text: specs/003-assets-skills/contracts/import-protocol.md. Desktop
content reaches a (possibly remote) server only as digest-checked chunks; a
commit re-verifies the staged tree against the preview digest, so anything
that drifted between preview and confirm is refused, and a failure leaves the
old revision, bindings and snapshots untouched.
"""
from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from pacthold_runtime_compat.resource_contracts.runtime_artifacts import (
    runtime_artifact_tree_digest,
)

from ..api.errors import ImportError_
from ..api.identity import MAX_ASSET_BYTES, MAX_ASSET_ENTRIES
from ..formats.agent_skills.validator import file_preview, validate_skill_directory
from .records import AssetRecords
from .store import SkillRevisionStore

MAX_CHUNK_BYTES = 256 * 1024
PREVIEW_TEXT_BYTES = 256 * 1024
#: A session unclaimed for this long — typically after a server restart, since
#: the in-memory ledger dies with the process — sweeps its staging area.
SESSION_TTL_SECONDS = 3600

_PENDING = "pending"
_RECEIVED = "received"
_PREPARED = "prepared"
_COMMITTED = "committed"
_ABORTED = "aborted"


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ImportService:
    """One bounded transfer session at a time per service instance."""

    def __init__(self, root: Path | str, records: AssetRecords | None = None,
                 store: SkillRevisionStore | None = None) -> None:
        self.root = Path(root)
        self.records = records
        self.store = store if store is not None else SkillRevisionStore(self.root)
        self._sessions: dict[str, dict[str, Any]] = {}
        self._sweep_expired()

    def _sweep_expired(self) -> None:
        """Clean staging areas left behind by sessions that died with a
        previous process (contracts/import-protocol.md: bounded staging)."""
        import_root = self.root / "import"
        if not import_root.is_dir():
            return
        deadline = time.time() - SESSION_TTL_SECONDS
        for child in import_root.iterdir():
            try:
                if child.stat().st_mtime < deadline:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                continue

    def begin(self, *, request_id: str, files: list[dict[str, Any]],
              total_bytes: int) -> dict[str, Any]:
        del request_id  # the wire layer owns replay protection
        self._reject_oversize(files, total_bytes)
        declared = []
        seen: set[str] = set()
        for item in files:
            path = item.get("path")
            _reject_bad_path(path)
            if path in seen:
                raise ImportError_("IMPORT_PATH_INVALID", "duplicate declared path",
                                   detail=path)
            seen.add(path)
            declared.append({"path": path, "bytes": int(item["bytes"]),
                             "sha256": item["sha256"]})
        if total_bytes != sum(item["bytes"] for item in declared):
            raise ImportError_(
                "IMPORT_BOUNDS_EXCEEDED", "declared total does not match the files")
        import_id = f"import_{uuid.uuid4().hex}"
        staging = self._import_dir(import_id) / "payload"
        staging.mkdir(parents=True)
        self._sessions[import_id] = {
            "state": _PENDING, "declared": declared, "created": time.time(),
            "received": [False] * len(declared), "staging": staging,
            "preview": None,
        }
        return {"importId": import_id}

    def chunk(self, import_id: str, *, index: int, payload: bytes,
              sha256: str) -> dict[str, Any]:
        session = self._session(import_id, _PENDING)
        if not 0 <= index < len(session["declared"]):
            raise ImportError_("IMPORT_PATH_INVALID", f"chunk index {index} is unknown")
        declared = session["declared"][index]
        if len(payload) > MAX_CHUNK_BYTES:
            raise ImportError_("IMPORT_BOUNDS_EXCEEDED", "chunk exceeds the size bound")
        if _digest(payload) != declared["sha256"] or sha256 != declared["sha256"]:
            raise ImportError_(
                "IMPORT_DIGEST_MISMATCH",
                f"chunk {index} for {declared['path']} does not match its digest",
                detail=f"expected {declared['sha256']}")
        if len(payload) != declared["bytes"]:
            raise ImportError_("IMPORT_BOUNDS_EXCEEDED",
                               f"chunk {index} is not the declared size",
                               detail=declared["path"])
        target = session["staging"] / declared["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        session["received"][index] = True
        if all(session["received"]):
            session["state"] = _RECEIVED
        return {"importId": import_id, "receivedBytes": len(payload)}

    def prepare(self, import_id: str, *,
                source: dict[str, Any]) -> dict[str, Any]:
        """Assemble and fully validate the staged tree; produce the preview."""
        session = self._session(import_id, _RECEIVED)
        payload_root = session["staging"]
        try:
            validated = validate_skill_directory(payload_root)
        except Exception:
            self.abort(import_id)
            raise
        tree_digest = runtime_artifact_tree_digest(payload_root)
        files = [file_preview(entry, payload_root) for entry in validated.entries]
        preview = {
            "name": validated.facts.name,
            "description": validated.facts.description,
            "metadata": dict(validated.facts.metadata),
            "retainedFields": {key: value for key, value
                               in validated.facts.retained.items()},
            "files": files,
            "scripts": list(validated.scripts),
            "treeDigest": tree_digest,
            "totalBytes": validated.total_bytes,
            "source": dict(source),
        }
        session["preview"] = preview
        session["state"] = _PREPARED
        return preview

    def commit(self, import_id: str, *, asset_id: str, revision: int) -> dict[str, Any]:
        """Re-verify the staged digest, then publish atomically.

        The response says `stored` — never `loaded`: installation gives the
        user a saved, verifiable revision, nothing more.
        """
        session = self._session(import_id, _PREPARED)
        preview = session["preview"]
        payload_root = session["staging"]
        actual = runtime_artifact_tree_digest(payload_root)
        if actual != preview["treeDigest"]:
            self.abort(import_id)
            raise ImportError_(
                "IMPORT_CONTENT_DRIFTED",
                "the staged content changed after the preview was shown",
                detail=f"preview {preview['treeDigest']} vs staged {actual}")
        try:
            facts = self.store.install(payload_root, asset_id=asset_id,
                                       revision=revision,
                                       source_ref=f"transfer:{import_id}")
        except Exception:
            self.abort(import_id)
            raise
        self._finish(import_id, _COMMITTED)
        if self.records is not None:
            published = self.records.publish(
                kind="skill", name=facts["name"], revision=revision,
                digest=facts["tree_digest"], description=facts["description"],
                source=f"transfer:{import_id}", asset_id=asset_id)[1]
            from .records import asset_view

            body = asset_view({**published, "id": published["asset_id"]})
        else:
            body = {
                "assetId": facts["asset_id"], "kind": "skill", "name": facts["name"],
                "description": facts["description"], "latestRevision": revision,
                "digest": facts["tree_digest"], "source": facts["source"],
            }
        return {"asset": body, "effect": "stored"}

    def abort(self, import_id: str) -> None:
        """Idempotent cleanup of one session's staging area."""
        session = self._sessions.get(import_id)
        if session is None:
            return
        shutil.rmtree(self._import_dir(import_id), ignore_errors=True)
        session["state"] = _ABORTED

    def preview(self, import_id: str | None = None) -> dict[str, Any]:
        """The preview of the (only) prepared session, for the caller's flow."""
        if import_id is None:
            prepared = [key for key, session in self._sessions.items()
                        if session["state"] == _PREPARED]
            if len(prepared) != 1:
                raise ImportError_("IMPORT_SESSION_INVALID",
                                   "no single prepared import session")
            import_id = prepared[0]
        session = self._session(import_id, _PREPARED)
        return session["preview"]

    # -- internals -----------------------------------------------------------

    def _import_dir(self, import_id: str) -> Path:
        return self.root / "import" / import_id

    def _session(self, import_id: str, expected_state: str) -> dict[str, Any]:
        session = self._sessions.get(import_id)
        if session is None or session["state"] != expected_state:
            raise ImportError_("IMPORT_SESSION_INVALID",
                               f"import {import_id} is not {expected_state}")
        return session

    def _finish(self, import_id: str, state: str) -> None:
        shutil.rmtree(self._import_dir(import_id), ignore_errors=True)
        self._sessions[import_id]["state"] = state

    @staticmethod
    def _reject_oversize(files: list[dict[str, Any]], total_bytes: int) -> None:
        if len(files) > MAX_ASSET_ENTRIES or total_bytes > MAX_ASSET_BYTES:
            raise ImportError_(
                "IMPORT_BOUNDS_EXCEEDED",
                f"a transfer may carry {MAX_ASSET_ENTRIES} files and "
                f"{MAX_ASSET_BYTES} bytes at most")


def _reject_bad_path(path: Any) -> None:
    if not isinstance(path, str) or not path or path.startswith("/") \
            or ".." in Path(path).parts or "\x00" in path:
        raise ImportError_("IMPORT_PATH_INVALID", "declared path must stay inside the payload",
                           detail=str(path))
