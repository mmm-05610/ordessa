"""Read exact, explicitly pinned project-file SourceRefs without scanning.

Construction is a trusted local-composition decision for one Scope and a fixed
set of SourceRefs. It is not a default product ACL or a historical version
archive: the configured upstream version is declared to refer to the current
file bytes and must continue to match their captured digest and length.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
from threading import Lock

from ...application.contracts.errors import ApplicationError
from ...application.contracts.commands import CommandContext
from ...application.contracts.transactions import UoWFactory
from ...domain.artifacts.provenance import SourceRef, VersionCapture
from ...domain.common.models.identity import Scope
from ...domain.common.models.selection import MAX_CONTENT_BYTES


_PROVIDER = "project-files"
_OPEN_DIRECTORY = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _document_parts(ref: SourceRef) -> tuple[str, ...]:
    locator = ref.locator
    if (ref.kind != "document" or locator.kind != "document"
            or locator.provider != _PROVIDER or type(locator.document_id) is not str):
        raise ApplicationError("SOURCE_UNAVAILABLE")
    value = locator.document_id
    if (not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value)
            or "\\" in value or "\x00" in value
            or any(ord(char) < 32 for char in value)):
        raise ApplicationError("SOURCE_UNAVAILABLE")
    parts = tuple(value.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise ApplicationError("SOURCE_UNAVAILABLE")
    # Path parsing also rejects platform-specific absolute forms on platforms
    # where pathlib recognizes them; the explicit checks above are POSIX-safe.
    path = PurePosixPath(value)
    if path.is_absolute() or tuple(path.parts) != parts:
        raise ApplicationError("SOURCE_UNAVAILABLE")
    return parts


def _mapped_parts(value: str) -> tuple[str, ...]:
    """Validate an explicitly configured, project-relative file path."""
    if (type(value) is not str or not value or value.startswith("/") or ":" in value
            or "\\" in value or "\x00" in value
            or any(ord(char) < 32 for char in value)):
        raise ApplicationError("SOURCE_UNAVAILABLE")
    parts = tuple(value.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise ApplicationError("SOURCE_UNAVAILABLE")
    return parts


class ProjectSourceMaterials:
    """A read-only SourceMaterialPort for explicitly pinned local files.

    The trusted local composition supplies one exact scope, root and nonempty
    tuple of exact SourceRef-to-path pins. Only those exact references can be read. The adapter
    neither grants product permissions nor searches for a source/version.
    """

    def __init__(self, factory: UoWFactory, *, scope: Scope, root: str | os.PathLike[str],
                 source_mappings: tuple[tuple[SourceRef, str], ...]):
        if (factory is None or type(scope) is not Scope or type(source_mappings) is not tuple
                or not source_mappings or any(type(pair) is not tuple or len(pair) != 2
                    or type(pair[0]) is not SourceRef or type(pair[0].capture) is not VersionCapture
                    or type(pair[1]) is not str for pair in source_mappings)
                or len({ref for ref, _ in source_mappings}) != len(source_mappings) or not _NOFOLLOW):
            raise ApplicationError("SOURCE_UNAVAILABLE")
        mapped = []
        for ref, relative_path in source_mappings:
            _document_parts(ref)
            mapped.append((ref, _mapped_parts(relative_path)))
        # Historical versions of one logical document cannot share a mutable path.
        for index, (ref, path) in enumerate(mapped):
            for other_ref, other_path in mapped[index + 1:]:
                same_document = ref.locator == other_ref.locator
                same_version = ref.capture.upstream_version == other_ref.capture.upstream_version
                if (same_document and same_version
                        and (ref.capture.content_digest != other_ref.capture.content_digest
                             or ref.byte_length != other_ref.byte_length)):
                    raise ApplicationError("SOURCE_UNAVAILABLE")
                if (same_document and not same_version and path == other_path):
                    raise ApplicationError("SOURCE_UNAVAILABLE")
        try:
            configured_root = Path(root)
            if not configured_root.is_absolute() or configured_root.is_symlink():
                raise ValueError("project root must be absolute and not a symlink")
            resolved_root = configured_root.resolve(strict=True)
            flags = _OPEN_DIRECTORY | _NOFOLLOW
            root_fd = os.open(resolved_root, flags)
            if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                os.close(root_fd)
                raise ValueError("project root is not a directory")
        except (OSError, TypeError, ValueError) as exc:
            raise ApplicationError("SOURCE_UNAVAILABLE") from exc
        self.factory = factory
        self.scope = scope
        self.root = resolved_root
        self.source_mappings = tuple(mapped)
        self._root_fd = root_fd
        self._closed = False
        self._lock = Lock()

    def close(self) -> None:
        """Release the pinned read-only project-root descriptor."""
        with self._lock:
            if not self._closed:
                os.close(self._root_fd)
                self._closed = True

    def _open_pinned_file(self, parts: tuple[str, ...]) -> int:
        with self._lock:
            if self._closed:
                raise ApplicationError("SOURCE_UNAVAILABLE")
            directory_fd = os.dup(self._root_fd)
        try:
            for component in parts[:-1]:
                next_fd = os.open(component, _OPEN_DIRECTORY | _NOFOLLOW, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | _NOFOLLOW
            # O_NONBLOCK prevents a substituted FIFO from blocking before the
            # regular-file check; it has no effect on ordinary files.
            file_flags |= getattr(os, "O_NONBLOCK", 0)
            return os.open(parts[-1], file_flags, dir_fd=directory_fd)
        except OSError as exc:
            raise ApplicationError("SOURCE_UNAVAILABLE") from exc
        finally:
            os.close(directory_fd)

    @staticmethod
    def _stable_identity(info):
        # Times are used only to detect an in-place concurrent mutation during
        # this read. They never identify or infer an upstream immutable version.
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def read(self, context: CommandContext, ref: SourceRef) -> bytes:
        if type(context) is not CommandContext or context.scope != self.scope:
            raise ApplicationError("SOURCE_UNAVAILABLE")
        if type(ref) is not SourceRef:
            raise ApplicationError("SOURCE_UNAVAILABLE")
        mapping = next((parts for item, parts in self.source_mappings if item == ref), None)
        if mapping is None:
            same_source = any(item.source_id == ref.source_id and item.locator == ref.locator
                              for item, _ in self.source_mappings)
            if same_source:
                raise ApplicationError("SOURCE_VERSION_MISMATCH")
            raise ApplicationError("SOURCE_UNAVAILABLE")
        _document_parts(ref)
        fd = self._open_pinned_file(mapping)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_size != ref.byte_length
                    or before.st_size > MAX_CONTENT_BYTES):
                raise ApplicationError("SOURCE_CONTENT_MISMATCH")
            chunks = []
            remaining = ref.byte_length + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(fd)
            if self._stable_identity(before) != self._stable_identity(after):
                raise ApplicationError("SOURCE_CONTENT_MISMATCH")
            if (len(raw) != ref.byte_length or hashlib.sha256(raw).hexdigest()
                    != ref.capture.content_digest.hex):
                raise ApplicationError("SOURCE_CONTENT_MISMATCH")
            return raw
        except OSError as exc:
            raise ApplicationError("SOURCE_UNAVAILABLE") from exc
        finally:
            os.close(fd)


__all__ = ["ProjectSourceMaterials"]
