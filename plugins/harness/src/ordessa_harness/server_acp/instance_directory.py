"""Private running-instance configuration directories, never Profile homes.

Allocation is explicit. Content is retained after process exit for recovery;
this module neither copies global configuration nor deletes session state.
"""
from pathlib import Path
import os
import tempfile


def _private(directory: Path) -> None:
    info = directory.lstat()
    if (not directory.is_dir() or directory.is_symlink()
            or directory.resolve() != directory or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise ValueError("instance allocation root must be private, owned and symlink-free")


def allocate_instance_directory(data_root: Path | str) -> Path:
    root = Path(data_root)
    if not root.is_absolute() or str(root) != os.path.normpath(str(root)):
        raise ValueError("data root must be canonical and absolute")
    # The runtime owns and creates its data root before allocating a process.
    if root.resolve() != root or root.is_symlink() or not root.is_dir():
        raise ValueError("data root must already exist without symlink ancestors")
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o022:
        raise ValueError("data root must be user-owned and not writable by others")
    parent = root / "harness-instances"
    parent.mkdir(mode=0o700, exist_ok=True)
    _private(parent)
    allocated = Path(tempfile.mkdtemp(prefix="pi-", dir=parent))
    _private(allocated)
    return allocated
