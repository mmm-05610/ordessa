"""pytest entry point for the Profile suite.

The scripted Harness catalog / facet provider doubles live in
``profile_harness_doubles`` — a uniquely named module — so that test modules
can import them without colliding with any other suite's ``conftest`` in a
combined pytest session.  This file only exposes the pytest fixtures and the
deliberate counterexample hook (constitution IV).
"""
from __future__ import annotations

import pytest

from profile_harness_doubles import make_core


@pytest.fixture
def core(tmp_path):
    return make_core(tmp_path)


# Counterexample hook (constitution IV): an env var selects a deliberate
# behaviour break; the gate suite must then FAIL. Never set in normal runs.
import os as _os

if _os.environ.get("PROFILE_COUNTEREXAMPLE"):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from injections import apply_counterexample as _apply
    _apply()