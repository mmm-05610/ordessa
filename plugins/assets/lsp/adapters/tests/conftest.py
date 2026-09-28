"""Shared fixtures for the 016 LSP adapter tests."""
from __future__ import annotations

import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]          # .../plugins/assets/lsp/adapters
_DOMAIN = _PKG.parent                               # .../plugins/assets/lsp
for p in (str(_PKG / "src"), str(_DOMAIN / "api" / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest


@pytest.fixture(scope="session")
def repo_pins() -> dict[str, str]:
    """实测仓内 harnesses.toml（file-relative；换树不串）。"""
    from ordessa_lsp_adapters import pinned_harness_versions
    return pinned_harness_versions()
