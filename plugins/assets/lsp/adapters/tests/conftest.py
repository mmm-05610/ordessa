"""Shared fixtures for the 016 LSP adapter tests."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
for p in (str(_SRC), str(_SRC.parent.parent.parent / "api" / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest


@pytest.fixture(scope="session")
def repo_pins() -> dict[str, str]:
    """实测仓内 harnesses.toml（file-relative；换树不串）。"""
    from ordessa_lsp_adapters import pinned_harness_versions
    return pinned_harness_versions()
