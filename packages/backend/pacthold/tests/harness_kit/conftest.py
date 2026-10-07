"""Make the package sources importable without an editable install.

The monorepo layout keeps the core at `packages/pacthold/src`; when the test
session runs from a plain checkout (nothing pip-installed) these paths are
added so the pins can state their assumption instead of relying on the caller.
Only paths are added; nothing here reorders or replaces already-importable
packages.
"""
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[5] / 'plugins' / 'harness'
REPO_ROOT = PLUGIN_ROOT.parents[3]

for _root in (
    PLUGIN_ROOT / "src",
    REPO_ROOT / "packages" / "pacthold" / "src",
):
    if _root.is_dir() and str(_root) not in sys.path:
        sys.path.append(str(_root))
