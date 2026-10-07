"""T04 native adapters: the pure-function gate is honest-by-construction.

The parent ``tests/conftest.py`` already seals ``socket`` and ``subprocess``
for every test under ``tests/``. This package adds the file-system seal: the
assess/compile/verify surface must plan from injected DTOs alone — no HOME
reads, no config probing, nothing. Any accidental ``os.open``/``os.openat``
(including pathlib/builtin ``open`` paths) fails the suite.
"""
import os

import pytest


class _BlockedFileAccess(RuntimeError):
    pass


def _blocked(*args, **kwargs):
    raise _BlockedFileAccess("native adapters must not touch the filesystem")


@pytest.fixture(autouse=True)
def no_filesystem_access(monkeypatch):
    monkeypatch.setattr(os, "open", _blocked)
    # os.openat only exists when the platform exposes it (this interpreter
    # build does not); sealing os.open already closes every path that could
    # reach it (builtin open / pathlib both funnel through os.open).
    if hasattr(os, "openat"):
        monkeypatch.setattr(os, "openat", _blocked)
