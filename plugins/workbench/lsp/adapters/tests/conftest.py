"""Shared fixtures for the 016 LSP adapter tests."""
from __future__ import annotations

def _captured_test_pins():
    import tomllib
    from _lsp_helpers import captured_harnesses_text
    declarations = tomllib.loads(captured_harnesses_text())
    return {entry["identity"]["harness_type"]: entry["identity"]["version"]
            for entry in declarations["harness"]}


import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]          # .../plugins/workbench/lsp/adapters
_DOMAIN = _PKG.parent                               # .../plugins/workbench/lsp
for p in (str(_PKG / "src"), str(_DOMAIN / "api" / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest


@pytest.fixture(scope="session")
def repo_pins() -> dict[str, str]:
    """从 provider-own declaration fragments 捕获实测 pins。"""
    from ordessa_lsp_adapters import pinned_harness_versions
    return pinned_harness_versions(_captured_test_pins())
