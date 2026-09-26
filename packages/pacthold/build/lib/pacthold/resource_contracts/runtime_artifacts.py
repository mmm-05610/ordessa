"""Immutable runtime artifact directory authorization (provider-neutral).

A deployment declares an immutable runtime artifact directory — a reviewed Node
module tree, an isolated Python package closure, or any other digest-pinned
runtime dependency directory — as a canonical WSL absolute ``source``, a
restricted guest ``target`` under ``/runtime/artifacts/<name>`` and a stable
``treeDigest``.  The Server only validates that declaration's shape and passes
it through; the Worker re-derives the digest inside WSL and only then is bwrap
allowed to read-only bind the directory.

This module is the reference implementation of ``treeDigest``.  The Worker
implements the same algorithm in Rust (``workers/agent-box-worker/src/artifacts.rs``)
and the two must agree byte for byte; ``protocols/worker/golden/`` holds the
fixtures both sides assert against.

Canonical encoding, version 1::

    encoding := "agentbox-runtime-artifact-tree-v1\\n" || u64be(entry_count) || entry*
    entry    := kind_byte || u32be(path_bytes) || path || file_payload?
    kind_byte := b"d" (directory) | b"f" (regular file)
    file_payload := u64be(size) || sha256(content)      # 32 raw bytes
    digest   := "sha256:" || lowercase_hex(sha256(encoding))

``entry*`` is ordered ascending by ``path`` as unsigned bytes.  The encoding
therefore pins the entry set, each entry's relative path, its type, and for
files the size and content digest — never the absolute root path, so moving a
verified tree does not change its identity.  Modes, owners and timestamps are
deliberately outside the identity: the projection is read-only.

Rejected shapes are typed and fail closed:

- a root that is a symlink or is not a directory,
- any symlink, FIFO, socket, device, or other non-regular/non-directory entry,
- an entry path that is not printable ASCII (0x21-0x7E plus ``/`` separators),
  so Unicode normalization/casefold ambiguity cannot enter the identity,
- a duplicate or ASCII-case-colliding entry path,
- more than :data:`MAX_RUNTIME_ARTIFACT_ENTRIES` entries, more than
  :data:`MAX_RUNTIME_ARTIFACT_BYTES` bytes of file content, or a path longer
  than :data:`MAX_RUNTIME_ARTIFACT_PATH_BYTES`.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Iterator

from pacthold.extensions.runtime_composition import ProjectionRejected

RUNTIME_ARTIFACT_DOMAIN = b"agentbox-runtime-artifact-tree-v1\n"

#: Order-of-magnitude ceiling the work order allows for ordinary files.  The
#: same budget is charged for directories, so a directory bomb cannot grow the
#: entry count past it; this is the stricter of the two readings.
MAX_RUNTIME_ARTIFACT_ENTRIES = 32_768
#: Total file content bound (1 GiB), charged before a file is hashed.
MAX_RUNTIME_ARTIFACT_BYTES = 1024 * 1024 * 1024
MAX_RUNTIME_ARTIFACT_PATH_BYTES = 4096
#: Declarations one bootstrap may carry.
MAX_RUNTIME_ARTIFACT_TREES = 8

_HASH_CHUNK = 64 * 1024
_PORTABLE_PATH = re.compile(rb"[\x21-\x7e]+")
#: A stable mount name: never leading dot or dash, so an adapter that joins it
#: into its own arguments cannot have it read as a flag or a hidden path.
RUNTIME_ARTIFACT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
RUNTIME_ARTIFACT_TARGET = re.compile(
    r"/runtime/artifacts/[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z",
)
_TARGET_PREFIX = "/runtime/artifacts/"


class RuntimeArtifactRejected(ProjectionRejected):
    """A typed refusal of one runtime artifact declaration or directory.

    It is a `ProjectionRejected`, so a caller that already refuses rejected
    projections refuses this too, while `code` still names the exact rule.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def runtime_artifact_name(target: str) -> str:
    """Return the stable name of a restricted guest target."""
    validate_runtime_artifact_target(target)
    return target[len(_TARGET_PREFIX):]


def validate_runtime_artifact_target(target: object) -> str:
    """Accept only ``/runtime/artifacts/<stable-name>`` and nothing else."""
    if not isinstance(target, str) or RUNTIME_ARTIFACT_TARGET.match(target) is None:
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_TARGET_INVALID",
            "runtime artifact target must be /runtime/artifacts/<stable-name>",
        )
    return target


def runtime_artifact_tree_digest(
    path: Path | str, *,
    max_entries: int = MAX_RUNTIME_ARTIFACT_ENTRIES,
    max_bytes: int = MAX_RUNTIME_ARTIFACT_BYTES,
) -> str:
    """Return the stable digest of one real directory tree."""
    encoding, _entries, _total = _encode(Path(path), max_entries, max_bytes)
    return "sha256:" + hashlib.sha256(encoding).hexdigest()


def runtime_artifact_tree_summary(
    path: Path | str, *,
    max_entries: int = MAX_RUNTIME_ARTIFACT_ENTRIES,
    max_bytes: int = MAX_RUNTIME_ARTIFACT_BYTES,
) -> dict[str, object]:
    """Return non-secret identity metadata: digest, entry count and bytes."""
    encoding, entries, total = _encode(Path(path), max_entries, max_bytes)
    return {
        "digest": "sha256:" + hashlib.sha256(encoding).hexdigest(),
        "entries": entries,
        "bytes": total,
    }


def _encode(path: Path, max_entries: int, max_bytes: int) -> tuple[bytes, int, int]:
    entries = list(_walk(path, max_entries, max_bytes))
    entries.sort(key=lambda item: item[1])
    buffer = bytearray(RUNTIME_ARTIFACT_DOMAIN)
    buffer += len(entries).to_bytes(8, "big")
    total = 0
    for kind, relative, size, content in entries:
        buffer += kind
        buffer += len(relative).to_bytes(4, "big")
        buffer += relative
        if kind == b"f":
            buffer += size.to_bytes(8, "big")
            buffer += content
            total += size
    return bytes(buffer), len(entries), total


def _walk(root: Path, max_entries: int, max_bytes: int) -> Iterator[tuple[bytes, bytes, int, bytes]]:
    """Walk one real directory without following links, bounded and fail closed."""
    try:
        metadata = os.lstat(root)
    except OSError:
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_ROOT_INVALID", "runtime artifact root is unavailable",
        ) from None
    if stat.S_ISLNK(metadata.st_mode):
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_ROOT_INVALID", "runtime artifact root must not be a symlink",
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_ROOT_INVALID", "runtime artifact root must be a real directory",
        )
    seen: set[bytes] = set()
    total = 0
    pending: list[tuple[Path, bytes]] = [(root, b"")]
    while pending:
        directory, prefix = pending.pop()
        for name, location, shape, size in _children(directory):
            relative = prefix + b"/" + name if prefix else name
            _validate_relative(relative)
            key = relative.lower()
            if key in seen:
                raise RuntimeArtifactRejected(
                    "RUNTIME_ARTIFACT_PATH_COLLISION",
                    "runtime artifact has a duplicate or case-colliding path",
                )
            if len(seen) >= max_entries:
                raise RuntimeArtifactRejected(
                    "RUNTIME_ARTIFACT_OUTSIDE_BOUNDS",
                    "runtime artifact exceeds the entry bound",
                )
            seen.add(key)
            if shape == "symlink":
                raise RuntimeArtifactRejected(
                    "RUNTIME_ARTIFACT_ENTRY_INVALID",
                    "runtime artifact contains a symlink",
                )
            if shape == "directory":
                yield b"d", relative, 0, b""
                pending.append((location, relative))
                continue
            if shape != "file":
                raise RuntimeArtifactRejected(
                    "RUNTIME_ARTIFACT_ENTRY_INVALID",
                    "runtime artifact contains a special file",
                )
            if total + size > max_bytes:
                raise RuntimeArtifactRejected(
                    "RUNTIME_ARTIFACT_OUTSIDE_BOUNDS",
                    "runtime artifact exceeds the content bound",
                )
            total += size
            yield b"f", relative, size, _file_digest(location)


def _children(directory: Path) -> list[tuple[bytes, Path, str, int]]:
    """Describe one directory's children without following any link."""
    try:
        with os.scandir(directory) as scan:
            described = [
                (
                    os.fsencode(entry.name), Path(entry.path),
                    _shape(entry),
                    entry.stat(follow_symlinks=False).st_size,
                )
                for entry in scan
            ]
    except OSError:
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_ENTRY_INVALID", "runtime artifact entry is unreadable",
        ) from None
    described.sort(key=lambda item: item[0])
    return described


def _shape(entry: os.DirEntry) -> str:
    if entry.is_symlink():
        return "symlink"
    if entry.is_dir(follow_symlinks=False):
        return "directory"
    if entry.is_file(follow_symlinks=False):
        return "file"
    return "special"


def _validate_relative(relative: bytes) -> None:
    if len(relative) > MAX_RUNTIME_ARTIFACT_PATH_BYTES:
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_PATH_INVALID", "runtime artifact path exceeds the bound",
        )
    if _PORTABLE_PATH.fullmatch(relative) is None:
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_PATH_INVALID",
            "runtime artifact path must be printable ASCII without spaces",
        )
    if any(component in {b"", b".", b".."} for component in relative.split(b"/")):
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_PATH_INVALID", "runtime artifact path is not canonical",
        )


def _file_digest(path: Path) -> bytes:
    hasher = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_ENTRY_INVALID", "runtime artifact file is unreadable",
        ) from None
    try:
        with os.fdopen(descriptor, "rb") as stream:
            while True:
                chunk = stream.read(_HASH_CHUNK)
                if not chunk:
                    break
                hasher.update(chunk)
    except OSError:
        raise RuntimeArtifactRejected(
            "RUNTIME_ARTIFACT_ENTRY_INVALID", "runtime artifact file is unreadable",
        ) from None
    return hasher.digest()
