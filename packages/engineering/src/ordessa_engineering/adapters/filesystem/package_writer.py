from __future__ import annotations
from typing import Any
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
import os
import stat
from pathlib import Path

from ordessa_infrastructure.filesystem import (
    DirectoryReplacedError,
    FileAlreadyExistsError,
    PlatformUnsupportedError,
    UnsafeFileTypeError,
    UnsafePathError,
    create_exclusive_at,
    open_directory_nofollow as _infra_open_directory_nofollow,
    open_regular_at,
)

_EXCLUSIVE_FILE_MODE = 0o600
_EXPORT_DIRECTORY_MODE = 0o700


def _open_directory_nofollow(path: Path) -> int:
    """Open ``path`` as a directory through the shared filesystem mechanism.

    The mechanism owns the ``O_DIRECTORY | O_NOFOLLOW`` open, the symlink
    refusal, the identity check and the platform-guarantee refusal; this owner
    keeps its own business error codes and its policy of comparing the
    pre-open ``lstat`` identity with the post-open ``fstat``.
    """
    try:
        return _infra_open_directory_nofollow(path)
    except DirectoryReplacedError as exc:
        raise EngineeringError('package_directory_replaced') from exc
    except (UnsafeFileTypeError, PlatformUnsupportedError) as exc:
        raise EngineeringError('package_directory_unsafe') from exc


def _read_regular_at(directory_fd: int, name: str) -> bytes:
    if '/' in name or name in {'', '.', '..'}:
        raise EngineeringError('package_filename_unsafe')
    try:
        descriptor = open_regular_at(directory_fd, name)
    except UnsafePathError as exc:
        raise EngineeringError('package_filename_unsafe') from exc
    except UnsafeFileTypeError as exc:
        raise EngineeringError('package_file_unsafe') from exc
    try:
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def _validate_export_directory(raw: Any) -> Path:
    if type(raw) is not str or not raw:
        raise EngineeringError('export_path_missing')
    target = Path(raw)
    if not target.is_absolute():
        raise EngineeringError('export_path_must_be_absolute')
    if target.exists() or target.is_symlink():
        raise EngineeringError('export_target_exists_or_unknown')
    for parent in (target.parent, *target.parent.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise EngineeringError('export_parent_unsafe')
    return target


class PackageFiles:
    validate_export_directory = staticmethod(_validate_export_directory)
    open_directory = staticmethod(_open_directory_nofollow)
    read_regular = staticmethod(_read_regular_at)
    names = staticmethod(os.listdir)
    close = staticmethod(os.close)
    path = staticmethod(Path)

    def write_outputs(self, target, outputs):
        """Write each output as a new file, then make files and dirs durable.

        The stage order is fixed: per-file bytes are fsynced, then the target
        directory, then its parent. Directory publication policy (refuse a
        pre-existing target, validate parents, treat a partial export as
        query-only uncertainty) stays with this owner.
        """
        target.mkdir(mode=_EXPORT_DIRECTORY_MODE)
        directory_fd = _open_directory_nofollow(target)
        try:
            for name, payload in outputs.items():
                try:
                    descriptor = create_exclusive_at(directory_fd, name, mode=_EXCLUSIVE_FILE_MODE)
                except FileAlreadyExistsError as exc:
                    raise FileExistsError(name) from exc
                except UnsafePathError as exc:
                    raise EngineeringError('package_filename_unsafe') from exc
                except UnsafeFileTypeError as exc:
                    raise EngineeringError('package_file_unsafe') from exc
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.fsync(directory_fd)
            parent_fd = _open_directory_nofollow(target.parent)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        finally:
            os.close(directory_fd)
