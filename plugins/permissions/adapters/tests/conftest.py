"""Shared fixtures for the T03 adapters tests.

Pinned versions are *parsed from the repository* (`harnesses.toml`), never
hardcoded, so a pin change moves the tests with it instead of silently
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

from _permissions_adapters_helpers import HARNESSES_TOML  # noqa: E402


@pytest.fixture(scope="session")
def families() -> dict[str, dict[str, Any]]:
    """The real registry families, keyed by harness_type."""
    data = tomllib.loads(HARNESSES_TOML.read_text(encoding="utf-8"))
    return {item["identity"]["harness_type"]: item for item in data["harness"]}


@pytest.fixture(scope="session")
def pinned_versions(families) -> dict[str, str]:
    """Identity version of record for each harness_type in the tree."""
    return {name: item["identity"]["version"] for name, item in families.items()}
