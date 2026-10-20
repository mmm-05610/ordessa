"""Shared fixtures for the T03 adapters tests.

Pinned versions are captured from the actual provider-owned declaration fragments,
never hardcoded, so a pin change moves the tests with it instead of silently
diverging. The plain helper factories the tests use live next to this file in
`_permissions_adapters_helpers`, not here, so importing them by name cannot
collide with another package's `conftest.py`.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _permissions_adapters_helpers import captured_harnesses_text  # noqa: E402


@pytest.fixture(scope="session")
def families() -> dict[str, dict[str, Any]]:
    """Execution-declared provider families, keyed by harness_type."""
    data = tomllib.loads(captured_harnesses_text())
    return {item["identity"]["harness_type"]: item for item in data["harness"]}


@pytest.fixture(scope="session")
def pinned_versions(families) -> dict[str, str]:
    """Identity version of record for each harness_type in the tree."""
    return {name: item["identity"]["version"] for name, item in families.items()}
