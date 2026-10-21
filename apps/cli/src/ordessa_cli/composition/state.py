"""Explicit local state layout for the CLI; one directory per user request.

Owner files keep their original names and identity schemes. A fresh empty state
is initialized here; an existing user root is never adopted or migrated.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from ordessa_infrastructure.security.keys import (
    KeyMaterialError, ensure_private_key as _ensure_private_key,
)


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

    The file discipline lives in `ordessa_infrastructure.security.keys`, shared
    with every other owner that provisions private material; this wrapper keeps
    the CLI's typed refusal.
    """
    try:
        return _ensure_private_key(path)
    except KeyMaterialError as error:
        raise StateRefused(str(error)) from None
