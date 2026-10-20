"""Explicit local state layout for the CLI; one directory per user request.

Owner files keep their original names and identity schemes. A fresh empty state
is initialized here; an existing user root is never adopted or migrated.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


class StateRefused(RuntimeError):
    code = 'INVALID_INPUT'


@dataclass(frozen=True)
class LocalState:
    root: Path

    @property
    def work(self) -> Path:
        return self.root / 'work'

    @property
    def environments_store(self) -> Path:
        return self.root / 'environments.sqlite'

    @property
    def aliases(self) -> Path:
        return self.root / 'aliases.json'

    @property
    def profiles_store(self) -> Path:
        return self.root / 'profiles.sqlite'

    @property
    def agent_directory(self) -> Path:
        return self.root / 'agent-owner'

    @property
    def agent_store(self) -> Path:
        return self.agent_directory / 'agent-instances.sqlite'

    @property
    def decisions_root(self) -> Path:
        return self.root / 'decisions'

    @property
    def openshell_config(self) -> Path:
        return self.root / 'openshell.json'

    @property
    def fingerprint_key(self) -> Path:
        return self.root / 'profile-fingerprint.key'

    @classmethod
    def open(cls, path) -> 'LocalState':
        if type(path) is not str or not path:
            raise StateRefused('explicit --state directory required')
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            raise StateRefused('--state must be an absolute path')
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            info = None
        if info is not None:
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise StateRefused('--state must be a real directory')
            if info.st_mode & 0o077:
                raise StateRefused('--state directory must not be group/other accessible')
        else:
            candidate.mkdir(mode=0o700, parents=True)
        state = cls(candidate)
        for directory in (state.work, state.agent_directory, state.decisions_root):
            directory.mkdir(mode=0o700, exist_ok=True)
        for name in ('config', 'data', 'state', 'cache', 'tmp', 'home'):
            (state.work / name).mkdir(mode=0o700, exist_ok=True)
        return state


def ensure_private_key(path: Path) -> bytes:
    """Load or create the local fingerprint key exactly once, 32 bytes, 0600.

    The key is provisioned in the explicit state directory; it is not a fixture
    constant and is never printed, logged or accepted from configuration.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        fd = None
    except OSError:
        raise StateRefused('profile fingerprint key is unreadable') from None
    if fd is None:
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            return ensure_private_key(path)
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
            raise StateRefused('profile fingerprint key must be a private regular file')
        material = os.read(fd, 33)
        if len(material) != 32:
            raise StateRefused('profile fingerprint key has an unexpected size')
        return material
    finally:
        os.close(fd)
