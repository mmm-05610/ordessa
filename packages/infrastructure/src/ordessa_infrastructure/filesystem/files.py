"""Restricted file open and exclusive creation relative to a directory fd.

Every open is made relative to a trusted directory descriptor with
``O_NOFOLLOW`` so a symlink cannot redirect the operation. Names must be single
safe components (see :func:`ordessa_infrastructure.filesystem.directories.is_safe_component`).

Ownership rules:

* The borrowed ``directory_fd`` is never closed here.
* A returned file descriptor is owned by the caller.
* ``O_NOFOLLOW`` is mandatory. Where the platform lacks it the call refuses
  with :class:`PlatformUnsupportedError`; it never pretends ``0`` is safe.
* Permission bits are always passed in by the caller; this module never
  forces one business mode onto every file.
"""
from __future__ import annotations

import errno
import os
import stat

from .directories import is_safe_component, require_nofollow
from .errors import (
    FileAlreadyExistsError,
    PlatformUnsupportedError,
    UnsafeFileTypeError,
    UnsafePathError,
)

__all__ = [
    "open_file_at",
    "open_regular_at",
    "read_regular_at",
    "create_exclusive_at",
    "sync_directory",
]


def _base_flags() -> int:
    # ``O_NONBLOCK`` is added so opening a FIFO/device never blocks before the
    # post-open type check can reject it. For a regular file it has no effect
    # on reads/writes.
    return require_nofollow() | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)


def _check_component(name: str) -> None:
    if not is_safe_component(name):
        raise UnsafePathError(f"unsafe file component: {name!r}")


def open_file_at(
    directory_fd: int,
    name: str,
    flags: int,
    *,
    mode: int = 0o600,
    expected_mode: int | None = None,
) -> int:
    """Open ``name`` under ``directory_fd`` and return a caller-owned fd.

    ``O_NOFOLLOW`` is always added. A non-regular resulting file is refused and
    the fd closed. When ``expected_mode`` is given the opened inode's
    permission bits must match exactly.
    """
    _check_component(name)
    try:
        fd = os.open(name, flags | _base_flags(), mode, dir_fd=directory_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise UnsafeFileTypeError(f"symlink refused: {name!r}") from exc
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeFileTypeError(f"not a regular file: {name!r}")
        if expected_mode is not None and stat.S_IMODE(info.st_mode) != expected_mode:
            raise UnsafeFileTypeError(f"unexpected file mode for {name!r}")
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_regular_at(directory_fd: int, name: str, *, expected_mode: int | None = None) -> int:
    """Read-only regular-file open under ``directory_fd``."""
    return open_file_at(directory_fd, name, os.O_RDONLY, mode=0, expected_mode=expected_mode)


def read_regular_at(directory_fd: int, name: str, *, limit: int | None = None) -> bytes:
    """Read the bytes of a regular file under ``directory_fd``.

    ``limit`` bounds the accepted size in bytes. The bound is enforced twice:
    once on the opened size and again on the accumulated bytes actually read,
    so a file that grows after the open cannot slip past the limit. A file that
    exceeds the limit raises :class:`UnsafeFileTypeError` rather than returning
    partial data.
    """
    fd = open_regular_at(directory_fd, name)
    try:
        if limit is not None and os.fstat(fd).st_size > limit:
            raise UnsafeFileTypeError(f"file exceeds limit: {name!r}")
        chunks: list[bytes] = []
        size = 0
        while True:
            want = 1 << 16
            if limit is not None:
                want = min(want, limit + 1 - size)
                if want <= 0:
                    raise UnsafeFileTypeError(f"file exceeds limit: {name!r}")
            chunk = os.read(fd, want)
            if not chunk:
                break
            size += len(chunk)
            if limit is not None and size > limit:
                raise UnsafeFileTypeError(f"file exceeds limit: {name!r}")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def create_exclusive_at(directory_fd: int, name: str, *, mode: int, flags: int = 0) -> int:
    """Exclusively create a new regular file and return a caller-owned fd.

    Combines ``O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW`` with any extra
    ``flags`` (for example ``O_APPEND``). ``mode`` is required and used
    verbatim. An existing name is reported as :class:`FileAlreadyExistsError`.
    """
    _check_component(name)
    open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | flags | _base_flags()
    try:
        fd = os.open(name, open_flags, mode, dir_fd=directory_fd)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise FileAlreadyExistsError(f"already exists: {name!r}") from exc
        if exc.errno == errno.ELOOP:
            raise UnsafeFileTypeError(f"symlink refused: {name!r}") from exc
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise UnsafeFileTypeError(f"not a regular file: {name!r}")
    except BaseException:
        os.close(fd)
        raise
    return fd


def sync_directory(directory_fd: int) -> None:
    """Flush a directory's entries; the caller decides when this is required."""
    os.fsync(directory_fd)
