"""Directory-descriptor traversal relative to a trusted root descriptor.

Capabilities:

* :func:`open_directory_relative` opens one child directory of a trusted
  directory fd, refusing absolute names, separators and ``..``.
* :func:`open_directory_absolute` walks an absolute path one component at a
  time from ``/``, so no intermediate name is resolved through a symlink it
  should not follow.
* :func:`open_directory_nofollow` opens a directory path without following a
  final symlink and refuses when the directory identity (device/inode) changed
  between the ``lstat`` check and the open.

Ownership rules, stated once and relied on everywhere:

* A *borrowed* descriptor (the trusted parent/root fd passed in) is never
  closed here.
* Every descriptor this module opens is returned to the caller, who owns it.
  If an internal step fails, the newly opened descriptor is closed before the
  exception propagates, so a failure never leaks an fd.
* ``O_NOFOLLOW`` (and ``O_DIRECTORY`` for directory opens) is required. Where
  the platform cannot supply the guarantee the call refuses with
  :class:`PlatformUnsupportedError`; it never substitutes ``0``.
"""
from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

from .errors import (
    DirectoryReplacedError,
    PlatformUnsupportedError,
    UnsafeFileTypeError,
    UnsafePathError,
)

__all__ = [
    "open_directory_relative",
    "open_directory_absolute",
    "open_directory_nofollow",
    "is_safe_component",
]


def is_safe_component(name: str) -> bool:
    """True when ``name`` is a single, non-traversing path component."""
    return (
        isinstance(name, str)
        and name not in {"", ".", ".."}
        and "\x00" not in name
        and "/" not in name
        and "\\" not in name
        and os.sep not in name
        and not os.path.isabs(name)
    )


def require_nofollow() -> int:
    """Return ``O_NOFOLLOW`` or refuse; never fall back to ``0``."""
    flag = getattr(os, "O_NOFOLLOW", None)
    if not flag:
        raise PlatformUnsupportedError(
            "O_NOFOLLOW is unavailable; refusing to open without the symlink guarantee"
        )
    return flag


def _directory_flags() -> int:
    nofollow = require_nofollow()
    directory = getattr(os, "O_DIRECTORY", None)
    if not directory:
        raise PlatformUnsupportedError(
            "O_DIRECTORY is unavailable; refusing to open without the directory guarantee"
        )
    return os.O_RDONLY | directory | nofollow | getattr(os, "O_CLOEXEC", 0)


def open_directory_relative(parent_fd: int, name: str) -> int:
    """Open directory ``name`` under a trusted ``parent_fd`` and return the fd.

    ``parent_fd`` is borrowed and not closed. The returned fd is newly opened
    and owned by the caller.
    """
    if not is_safe_component(name):
        raise UnsafePathError(f"unsafe directory component: {name!r}")
    flags = _directory_flags()
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise UnsafeFileTypeError(f"symlink refused: {name!r}") from exc
        raise
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise UnsafeFileTypeError(f"not a directory: {name!r}")
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_directory_absolute(path: str | Path) -> int:
    """Open an absolute directory by walking it from ``/`` component by component.

    Refuses ``..`` components and separator-bearing names. ``path`` is made
    absolute lexically; each component is opened with ``O_NOFOLLOW`` relative
    to the previously opened directory. The caller owns the returned fd.
    """
    absolute = Path(path).absolute()
    parts = absolute.parts
    if not absolute.is_absolute() or not parts or parts[0] != os.sep:
        raise UnsafePathError(f"path is not absolute: {path!r}")
    flags = _directory_flags()
    fd = os.open(os.sep, flags)
    try:
        for part in parts[1:]:
            if not is_safe_component(part):
                raise UnsafePathError(f"unsafe directory component: {part!r}")
            try:
                nxt = os.open(part, flags, dir_fd=fd)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise UnsafeFileTypeError(f"symlink refused: {part!r}") from exc
                raise
            os.close(fd)
            fd = nxt
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise UnsafeFileTypeError(f"not a directory: {part!r}")
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_directory_nofollow(path: str | Path) -> int:
    """Open directory ``path`` refusing a symlink and a replaced identity.

    The pre-open ``lstat`` establishes the expected ``(st_dev, st_ino)``; the
    post-open ``fstat`` must match, otherwise the directory was replaced
    between check and open and :class:`DirectoryReplacedError` is raised. The
    caller owns the returned fd.
    """
    target = Path(path)
    info = target.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise UnsafeFileTypeError(f"unsafe directory: {path!r}")
    fd = os.open(target, _directory_flags())
    try:
        actual = os.fstat(fd)
        if not stat.S_ISDIR(actual.st_mode) or (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
            raise DirectoryReplacedError(f"directory was replaced: {path!r}")
    except BaseException:
        os.close(fd)
        raise
    return fd
