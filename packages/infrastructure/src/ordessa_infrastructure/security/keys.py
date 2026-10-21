"""Private key-material provisioning for local owners (0600, no symlinks).

The material is provisioned once in an explicit, owner-controlled directory. It
is never a fixture constant, never accepted from configuration and never
printed, logged or returned through an operation result. Callers do the
placement; this module only owns the file discipline.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat


class KeyMaterialError(RuntimeError):
    """The private key file is missing, unreadable, unsafe or the wrong size."""

    code = "KEY_MATERIAL_UNAVAILABLE"


def ensure_private_key(path: Path) -> bytes:
    """Load or create the 32-byte key at ``path`` exactly once, mode 0600.

    A symlink, a non-regular file, a group/other-accessible mode or an
    unexpected size is refused rather than "repaired": silently replacing key
    material would change the identities that depend on it.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        fd = None
    except OSError:
        raise KeyMaterialError("private key material is unreadable") from None
    if fd is None:
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            return ensure_private_key(path)
        except OSError:
            raise KeyMaterialError("private key material cannot be created") from None
        try:
            material = os.urandom(32)
            os.write(fd, material)
            os.fsync(fd)
            return material
        finally:
            os.close(fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise KeyMaterialError("private key material must be a private regular file")
        material = os.read(fd, 33)
        if len(material) != 32:
            raise KeyMaterialError("private key material has an unexpected size")
        return material
    finally:
        os.close(fd)


__all__ = ["KeyMaterialError", "ensure_private_key"]
