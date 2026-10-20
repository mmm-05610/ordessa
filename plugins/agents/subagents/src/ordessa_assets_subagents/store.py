"""File-backed storage: immutable revisions, CAS rows, operation receipts.

Layout under one root::

    definitions/<definition_id>/definition.json      mutable metadata row (CAS)
    definitions/<definition_id>/revisions/<n>.json   immutable, read-only
    receipts/<sha256(scope)>/<sha256(key)>.json      idempotency receipt

A revision is published by staging bytes and hard-linking them into place, so a
write over a stored revision fails instead of rewriting history; the older
revision's bytes stay what a frozen reference resolves to.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from . import decoder, limits
from .dto import AgentDefinition, DefinitionRevision
from .errors import (
    ASSIGNMENT_CONFLICT,
    DEFINITION_INVALID,
    REVISION_STALE,
    DomainError,
)

_ID_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")


class DefinitionStore:
    """Owns every byte this domain writes; nothing here reaches a native root."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- paths -------------------------------------------------------------

    def _component(self, value: str, *, item: str) -> str:
        if not value or len(value) > limits.MAX_DEFINITION_ID_CHARS:
            raise DomainError(DEFINITION_INVALID, item_id=item, detail="empty or over-long id")
        if not set(value) <= _ID_SAFE or value.startswith("."):
            raise DomainError(
                DEFINITION_INVALID, item_id=item,
                detail="an id may not name a path or hold a separator",
            )
        return value

    def definition_dir(self, definition_id: str) -> Path:
        return self.root / "definitions" / self._component(definition_id, item="definition_id")

    def definition_path(self, definition_id: str) -> Path:
        return self.definition_dir(definition_id) / "definition.json"

    def revision_path(self, definition_id: str, revision: int) -> Path:
        number = self._component(str(revision), item="revision")
        return self.definition_dir(definition_id) / "revisions" / f"{number}.json"

    def receipt_path(self, scope: str, operation_key: str) -> Path:
        hashed = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
        return self.root / "receipts" / hashed(scope) / f"{hashed(operation_key)}.json"

    # -- definition rows (CAS) ---------------------------------------------

    def create_definition(self, definition: AgentDefinition) -> None:
        path = self.definition_path(definition.definition_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _write_exclusive(path, _dumps(decoder.definition_mapping(definition)))
        except FileExistsError:
            raise DomainError(
                ASSIGNMENT_CONFLICT, item_id=definition.definition_id,
                detail="that definition id already holds a row",
            ) from None

    def replace_definition(self, definition: AgentDefinition, *, expected_row_version: int) -> None:
        """Compare-and-set on the row version: a stale writer changes nothing."""
        stored = self.read_definition(definition.definition_id)
        if stored is None:
            raise DomainError(
                DEFINITION_INVALID, item_id=definition.definition_id, detail="no such definition",
            )
        if int(stored["row_version"]) != expected_row_version:
            raise DomainError(
                REVISION_STALE, item_id=definition.definition_id,
                detail=(
                    f"expected row_version {expected_row_version}, the row holds "
                    f"{stored['row_version']}"
                ),
            )
        _write_atomic(
            self.definition_path(definition.definition_id),
            _dumps(decoder.definition_mapping(definition)),
        )

    def read_definition(self, definition_id: str) -> dict[str, Any] | None:
        path = self.definition_path(definition_id)
        if path.is_symlink() or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_definition(self, definition_id: str) -> AgentDefinition:
        stored = self.read_definition(definition_id)
        if stored is None:
            raise DomainError(
                DEFINITION_INVALID, item_id=definition_id, detail="no such definition",
            )
        return decoder.decode_definition(stored)

    def list_definitions(self) -> list[AgentDefinition]:
        root = self.root / "definitions"
        if not root.is_dir():
            return []
        rows = [
            self.get_definition(entry.name)
            for entry in sorted(root.iterdir(), key=lambda item: item.name)
            if entry.is_dir() and not entry.is_symlink()
            and self.definition_path(entry.name).is_file()
        ]
        return sorted(rows, key=lambda row: (row.slug, row.definition_id))

    def enabled_definitions(self) -> list[AgentDefinition]:
        return [row for row in self.list_definitions() if not row.archived]

    def enabled_description_bytes(self, *, exclude: AgentDefinition | None = None) -> int:
        """The aggregate description budget of the enabled library."""
        total = 0
        for row in self.enabled_definitions():
            if exclude is not None and row.definition_id == exclude.definition_id:
                continue
            total += len(row.description.encode("utf-8"))
        return total

    # -- immutable revisions -----------------------------------------------

    def write_revision(self, revision: DefinitionRevision) -> None:
        path = self.revision_path(revision.definition_id, revision.revision)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _write_exclusive(path, _dumps(decoder.revision_mapping(revision)), read_only=True)
        except FileExistsError:
            raise DomainError(
                REVISION_STALE, item_id=f"{revision.definition_id}@{revision.revision}",
                detail="a stored revision is never rewritten",
            ) from None

    def read_revision(self, definition_id: str, revision: int) -> DefinitionRevision | None:
        path = self.revision_path(definition_id, revision)
        if path.is_symlink() or not path.is_file():
            return None
        return decoder.decode_revision(json.loads(path.read_text(encoding="utf-8")))

    def get_revision(self, definition_id: str, revision: int) -> DefinitionRevision:
        stored = self.read_revision(definition_id, revision)
        if stored is None:
            raise DomainError(
                DEFINITION_INVALID, item_id=f"{definition_id}@{revision}",
                detail="no such revision",
            )
        return stored

    def revision_numbers(self, definition_id: str) -> list[int]:
        directory = self.definition_dir(definition_id) / "revisions"
        if not directory.is_dir():
            return []
        return sorted(
            int(entry.name[: -len(".json")])
            for entry in directory.iterdir()
            if entry.name.endswith(".json") and entry.name[: -len(".json")].isdigit()
        )

    # -- operation receipts ------------------------------------------------

    def read_receipt(self, scope: str, operation_key: str) -> dict[str, Any] | None:
        path = self.receipt_path(scope, operation_key)
        if path.is_symlink() or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_receipt(
        self,
        *,
        scope: str,
        operation_key: str,
        request_digest: str,
        result: Mapping[str, Any],
    ) -> None:
        _write_atomic(self.receipt_path(scope, operation_key), _dumps({
            "scope": scope,
            "operation_key": operation_key,
            "request_digest": request_digest,
            "result": dict(result),
        }))

    # -- guards used by the import path ------------------------------------

    def holds_path(self, path: Path | str) -> bool:
        """True when a path is inside the store root: never an import source."""
        return _contained(self.root, Path(path))


def _contained(root: Path, target: Path) -> bool:
    try:
        Path(target).resolve(strict=False).relative_to(Path(root).resolve(strict=False))
    except ValueError:
        return False
    return True


def _dumps(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, allow_nan=False,
                       indent=2, sort_keys=True) + "\n").encode("utf-8")


def _stage_file(directory: Path, payload: bytes) -> Path:
    handle, name = tempfile.mkstemp(prefix=".staged-", dir=str(directory))
    staged = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = _stage_file(path.parent, payload)
    try:
        os.chmod(staged, 0o644)
        os.replace(staged, path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def _write_exclusive(path: Path, payload: bytes, *, read_only: bool = False) -> None:
    """Publish staged bytes; refuse — never overwrite — when the target exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = _stage_file(path.parent, payload)
    try:
        os.chmod(staged, 0o444 if read_only else 0o644)
        os.link(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def is_read_only(path: Path) -> bool:
    return not (Path(path).stat().st_mode & stat.S_IWUSR)


def walk_bounded(
    root: Path | str,
    *,
    max_entries: int = limits.MAX_IMPORT_FILES,
    max_bytes: int = limits.MAX_IMPORT_TOTAL_BYTES,
    max_depth: int = limits.MAX_IMPORT_DEPTH,
) -> list[Path]:
    """Regular, link-free files under one directory, bounded and never followed."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise DomainError(
            DEFINITION_INVALID, item_id=root.name,
            detail="an import source must be a real directory",
        )
    found: list[Path] = []
    total = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        depth = len(base.relative_to(root).parts)
        if depth >= max_depth:
            raise DomainError(
                DEFINITION_INVALID, item_id="import_depth",
                detail=f"an import source may not nest deeper than {max_depth - 1}",
            )
        dirnames.sort()
        for name in dirnames:
            if (base / name).is_symlink():
                raise DomainError(
                    DEFINITION_INVALID, item_id=name,
                    detail=f"a symlinked directory ({name}) is never followed",
                )
        for name in sorted(filenames):
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise DomainError(
                    DEFINITION_INVALID, item_id=path.name,
                    detail="only regular, non-symlink files may be previewed",
                )
            total += path.stat().st_size
            found.append(path)
            if len(found) > max_entries or total > max_bytes:
                raise DomainError(
                    DEFINITION_INVALID, item_id="import_bounds",
                    detail="the import source exceeds the read bounds",
                )
    return found


def read_source_bytes(path: Path | str, *, max_bytes: int = limits.MAX_IMPORT_FILE_BYTES) -> bytes:
    """One bounded, unexecuted read of a previewed file."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise DomainError(
            DEFINITION_INVALID, item_id=path.name,
            detail="only a regular, non-symlink file may be read",
        )
    size = path.stat().st_size
    if size > max_bytes:
        raise DomainError(
            DEFINITION_INVALID, item_id=path.name,
            detail=f"exceeds {max_bytes} bytes (got {size})",
        )
    return path.read_bytes()
