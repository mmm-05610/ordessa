"""Explicit test helpers for Server-owned Harness integration tests.

Owner packages are resolved by the invoking test environment. Source-mode
checks must select their roots in the outer command; this conftest must not
silently shadow installed owner distributions.
"""
from __future__ import annotations
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[5]
SUPPORT = REPO_ROOT / "packages/execution/agents/tests/support"
if SUPPORT.is_dir() and str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
