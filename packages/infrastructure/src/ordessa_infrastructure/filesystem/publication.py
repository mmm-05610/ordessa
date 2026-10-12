"""Staged single-file publication with honest durability accounting.

A publication runs four explicit stages:

1. ``write``           — create the temporary file exclusively and write bytes.
2. ``file_fsync``      — ``fsync`` the temporary file's bytes.
3. ``replace``         — atomically rename the temporary file onto the target.
4. ``directory_fsync`` — ``fsync`` the parent directory so the rename is durable.

Semantics: the target is **replaced atomically** (POSIX ``rename`` overwrites).
There is no "do not overwrite" mode; if a caller needs no-clobber it must prove
absence itself, because a portable, race-free no-clobber publication is not what
this primitive offers.

The stage boundary matters. Once the replace succeeds the target has *already
changed*; if the directory ``fsync`` then fails, persistence is unknown. This
module therefore:

* does **not** roll back the replace,
* does **not** delete the final target,
* reports :class:`PublicationError` with ``stage='directory_fsync'`` and
  ``target_may_have_changed=True``.

Before the replace, a failure leaves the target untouched and closes the owned
file descriptor, but does not unlink the temporary name. A pathname identity
check followed by unlink cannot safely exclude a concurrent replacement. The
temporary may therefore remain complete, partial or empty; callers own its
cleanup under conditions that exclude concurrent namespace changes. This
function never deletes a replacement file or performs an implicit retry.

Success still uses a pathname rename. Callers must control ``temp_name`` until
the rename completes; this primitive does not fence another actor replacing the
source name or attest that the renamed inode is the one opened for writing.

Complete-directory publication, business validation, identity-change cleanup,
``wal``/``shm`` cleanup and record-format specific commits stay with their
owners; this is deliberately a single-file primitive.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from .directories import is_safe_component
from .errors import PublicationError, UnsafePathError
from .files import create_exclusive_at, sync_directory

__all__ = ["PublicationStage", "PublishedFile", "publish_file"]


class PublicationStage(str, Enum):
    WRITE = "write"
    FILE_FSYNC = "file_fsync"
    REPLACE = "replace"
    DIRECTORY_FSYNC = "directory_fsync"


@dataclass(frozen=True)
class PublishedFile:
    """Outcome of a completed publication (all four stages succeeded)."""

    target: str
    temp: str


def _validate_names(target_name: str, temp_name: str) -> None:
    """Reject unsafe or ambiguous names before any create/write happens."""
    if not is_safe_component(target_name):
        raise UnsafePathError(f"unsafe target name: {target_name!r}")
    if not is_safe_component(temp_name):
        raise UnsafePathError(f"unsafe temp name: {temp_name!r}")
    if target_name == temp_name:
        raise ValueError("temp_name must differ from target_name")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if not written:
            # A zero-byte write must never spin forever.
            raise OSError("short write while publishing")
        view = view[written:]


def publish_file(
    directory_fd: int,
    target_name: str,
    data: bytes,
    *,
    temp_name: str,
    mode: int = 0o600,
) -> PublishedFile:
    """Publish ``data`` as ``target_name`` inside ``directory_fd``.

    ``target_name`` and ``temp_name`` must be distinct safe components; both are
    validated before any file is created. ``mode`` is the caller's explicit
    permission for the new file (the target keeps the temporary's mode).
    Before replacement, failures may leave ``temp_name`` behind. This function
    closes its fd but never removes that name; safe cleanup is the caller's
    responsibility. Retrying the same name will refuse while it remains present.
    """
    _validate_names(target_name, temp_name)

    fd = None
    try:
        try:
            fd = create_exclusive_at(directory_fd, temp_name, mode=mode)
        except Exception as exc:  # noqa: BLE001 - re-raised as a staged error
            raise PublicationError(PublicationStage.WRITE.value, f"temp create failed: {temp_name!r}") from exc
        try:
            _write_all(fd, data)
        except BaseException as exc:
            raise PublicationError(PublicationStage.WRITE.value, "writing temp failed") from exc
        try:
            os.fsync(fd)
        except BaseException as exc:
            raise PublicationError(PublicationStage.FILE_FSYNC.value, "file fsync failed") from exc
    finally:
        if fd is not None:
            os.close(fd)

    try:
        os.rename(temp_name, target_name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    except BaseException as exc:
        # Replace did not happen: the previous target is intact.
        raise PublicationError(PublicationStage.REPLACE.value, "atomic replace failed") from exc

    try:
        sync_directory(directory_fd)
    except BaseException as exc:
        # The target has already changed. Durability is unknown. No rollback,
        # no deletion of the final file.
        raise PublicationError(
            PublicationStage.DIRECTORY_FSYNC.value,
            "directory fsync failed after replace; target may have changed",
            target_may_have_changed=True,
        ) from exc

    return PublishedFile(target=target_name, temp=temp_name)
