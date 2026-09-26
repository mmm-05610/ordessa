"""Pacthold: the execution governance kernel for coding agents.

The import path is `pacthold` since the monorepo baseline migration
(2026-09-25). Compatibility surfaces that outlive the rename: the
`agent_box.plugins` entry-point group, the `AGENT_BOX_HOME` /
`AGENTBOX_*` environment surface, the on-disk data directory and
database names, and the resource-contract ids.
"""

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("pacthold")
except PackageNotFoundError:
    __version__ = None
if __version__ is None:
    # Source checkout — read the single source of truth from pyproject.toml
    _pyproject = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
    _m = re.search(
        r'^version\s*=\s*"([^"]+)"',
        _pyproject.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    __version__ = _m.group(1) if _m else "0.0.0"
