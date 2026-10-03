"""Shared fixtures for the T05 sandbox-adapter tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _sandbox_adapters_helpers import pinned_versions  # noqa: E402


@pytest.fixture(scope="session")
def pinned() -> dict[str, str]:
    return pinned_versions()
