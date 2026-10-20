"""The retired Profile v2 facet has no callable Subagents consumer."""
from __future__ import annotations

import importlib.util
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src" / "ordessa_assets_subagents"


def test_profile_facet_module_is_absent():
    assert not (SRC / "profile_facet.py").exists()
    assert importlib.util.find_spec("ordessa_assets_subagents.profile_facet") is None
