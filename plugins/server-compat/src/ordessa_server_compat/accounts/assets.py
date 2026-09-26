"""Order 56: the account asset - bounded, declared files, one lock per account.

The asset is one document (the declared login-state files, base64 payloads,
JSON envelope) handed to the platform SecretStore for encryption at rest; the
control plane only ever holds the locator and the digest. Three rules are the
whole point of this module and each one has a counterexample in the tests:

* **bounded**: a single file and the whole asset have hard caps, and an
  oversized candidate is a typed refusal that keeps the previous asset;
* **declared only**: packing and unpacking both work from the deployment's
  declared name list - anything else in the working copy is invisible;
* **one lock per account, optimistic digest**: a reclaim that cannot take the
  lock, or that finds the stored digest has moved since materialisation, is a
  typed conflict instead of a silent last-writer-wins overwrite.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Mapping, Sequence

#: One declared login-state file may not exceed this many bytes; the packed
#: asset (envelope included) may not either. Subscription credential files are
#: a few kilobytes in every family observed (order 56 stage A).
MAX_ASSET_FILE_BYTES = 256 * 1024
MAX_ASSET_TOTAL_BYTES = 1024 * 1024
MAX_ASSET_FILES = 8
#: A lock older than this is reported, never stolen: stealing would be exactly
#: the silent overwrite the lock exists to prevent.
LOCK_STALE_AFTER_SECONDS = 600


class AccountAssetError(RuntimeError):
    """A typed refusal of one asset operation."""

    def __init__(self, code: str, message: str, *, name: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.name = name


def digest_of(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def pack_asset(files: Mapping[str, bytes]) -> bytes:
    """Pack the declared files into the asset document.

    Absent names are omitted (a family that never wrote that file is not an
    error); present names must be regular bytes within the bounds.
    """
    if len(files) > MAX_ASSET_FILES:
        raise AccountAssetError("ACCOUNT_ASSET_OUTSIDE_BOUNDS", "too many account files")
    envelope: dict[str, dict[str, object]] = {}
    total = 0
    for name, payload in sorted(files.items()):
        if not isinstance(payload, bytes) or not payload:
            raise AccountAssetError(
                "ACCOUNT_ASSET_OUTSIDE_BOUNDS", "an account file is empty or not bytes",
                name=name,
            )
        if len(payload) > MAX_ASSET_FILE_BYTES:
            raise AccountAssetError(
                "ACCOUNT_ASSET_OUTSIDE_BOUNDS", "an account file exceeds the cap", name=name,
            )
        total += len(payload)
        if total > MAX_ASSET_TOTAL_BYTES:
            raise AccountAssetError(
                "ACCOUNT_ASSET_OUTSIDE_BOUNDS", "the account asset exceeds the cap",
            )
        envelope[name] = {
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "content": base64.b64encode(payload).decode("ascii"),
        }
    document = json.dumps(
        {"schema_version": 1, "files": envelope},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    if len(document) > MAX_ASSET_TOTAL_BYTES:
        raise AccountAssetError(
            "ACCOUNT_ASSET_OUTSIDE_BOUNDS", "the packed account asset exceeds the cap",
        )
    return document


def unpack_asset(blob: bytes, *, declared: Sequence[str]) -> dict[str, bytes]:
    """Unpack an asset, admitting exactly the declared names.

    The declared list is the authority in both directions: a stored entry that
    the deployment no longer declares is dropped, and a missing declared name
    is simply absent - never invented, never substituted.
    """
    try:
        document = json.loads(blob.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AccountAssetError("ACCOUNT_ASSET_INVALID", "the account asset is not readable") from exc
    if (not isinstance(document, dict) or document.get("schema_version") != 1
            or not isinstance(document.get("files"), dict)):
        raise AccountAssetError("ACCOUNT_ASSET_INVALID", "the account asset shape is unknown")
    declared_set = set(declared)
    files: dict[str, bytes] = {}
    for name, entry in document["files"].items():
        if name not in declared_set:
            continue
        if (not isinstance(entry, dict) or not isinstance(entry.get("content"), str)
                or not isinstance(entry.get("sha256"), str)):
            raise AccountAssetError("ACCOUNT_ASSET_INVALID", "an account entry is malformed", name=name)
        payload = base64.b64decode(entry["content"], validate=True)
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise AccountAssetError(
                "ACCOUNT_ASSET_INVALID", "an account entry failed its digest", name=name,
            )
        if len(payload) > MAX_ASSET_FILE_BYTES:
            raise AccountAssetError(
                "ACCOUNT_ASSET_OUTSIDE_BOUNDS", "an account entry exceeds the cap", name=name,
            )
        files[name] = payload
    return files


class AccountAssetStore:
    """One account's asset, kept in the platform SecretStore.

    The store is deliberately thin: it writes a packed document through a
    0600 scratch file (the SecretStore's import takes a file), reads the
    locator back, and keeps the digest alongside. The per-account lock lives
    in the accounts root and is taken around reclaim only.
    """

    def __init__(self, *, secret_store, accounts_root: Path | str) -> None:
        self.secret_store = secret_store
        self.accounts_root = Path(accounts_root)

    def _lock_path(self, account_id: str) -> Path:
        return self.accounts_root / account_id / "reclaim.lock"

    def acquire_reclaim_lock(self, account_id: str) -> Path:
        """Take the account's reclaim lock, or refuse typed.

        O_EXCL creation: a second reclaimer never waits and never proceeds.
        A stale lock is reported with its age and still refused - stealing it
        is the silent overwrite this lock exists to prevent.
        """
        path = self._lock_path(account_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            age = None
            try:
                age = int(time.time() - path.stat().st_mtime)
            except OSError:
                pass
            raise AccountAssetError(
                "ACCOUNT_RECLAIM_BUSY",
                "another reclaim holds this account's lock"
                + (f" (age {age}s)" if age is not None and age > LOCK_STALE_AFTER_SECONDS else ""),
            ) from exc
        with os.fdopen(handle, "w") as stream:
            stream.write(f"{os.getpid()}\n")
        return path

    def release_reclaim_lock(self, lock_path: Path) -> None:
        try:
            lock_path.unlink()
        except OSError:
            pass

    def write_asset(self, *, account_id: str, files: Mapping[str, bytes], kind: str) -> tuple[str, str]:
        """Pack and store the asset; returns (locator, digest)."""
        blob = pack_asset(files)
        root = self.accounts_root / account_id
        root.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkstemp(prefix="account-asset-", dir=str(root))[1])
        try:
            os.chmod(scratch, 0o600)
            scratch.write_bytes(blob)
            locator, _digest = self.secret_store.import_file(scratch, kind)
        finally:
            try:
                scratch.unlink()
            except OSError:
                pass
        return locator, digest_of(blob)

    def read_asset(self, *, locator: str, declared: Sequence[str]) -> dict[str, bytes]:
        return unpack_asset(self.secret_store.read(locator), declared=declared)

    def reclaim(
        self, *, account_id: str, stored_digest_of, materialized_digest: str | None,
        files: Mapping[str, bytes], kind: str,
    ) -> tuple[str, str]:
        """Reclaim a turn's working copy under the lock and the digest rule.

        The stored digest is re-read *inside* the lock and must still equal
        the digest this turn materialised (``None`` on both sides when this
        turn created the asset): anything else means another writer moved the
        asset first, and the typed conflict keeps it. The new asset is written
        before the caller updates the record, so a crash between the two
        leaves the previous record pointing at a still-readable asset.
        """
        lock = self.acquire_reclaim_lock(account_id)
        try:
            if stored_digest_of() != materialized_digest:
                raise AccountAssetError(
                    "ACCOUNT_ASSET_CONFLICT",
                    "the stored asset changed while this turn was running",
                )
            return self.write_asset(account_id=account_id, files=files, kind=kind)
        finally:
            self.release_reclaim_lock(lock)
