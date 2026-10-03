"""The monorepo rename is a real rename: pins for what changed and what stands.

What this pins, from the outside:

* the project ships the distribution `pacthold` and its import path is
  `pacthold`; the historical `agent-box*` console-script aliases and the
  `agent_box` import path were retired with the old repository layout
  (monorepo baseline, 2026-09-25);
* the compatibility surfaces that survive the rename are untouched: the
  plugin entry-point group `agent_box.plugins`, the resource-contract ids,
  the `AGENT_BOX_HOME` variable prefix and the data-directory facts.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_the_distribution_is_named_pacthold_and_the_entry_point_is_new():
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    assert pyproject["project"]["name"] == "pacthold"
    assert scripts == {"pacthold": "pacthold.cli:main"}


def test_the_version_lookup_answers_for_a_pacthold_install():
    import pacthold

    assert pacthold.__version__ and pacthold.__version__ != "0.0.0"
    source = (REPO / "src" / "pacthold" / "__init__.py").read_text(encoding="utf-8")
    assert 'version("pacthold")' in source


def test_the_plugin_entry_point_group_keeps_its_historical_spelling():
    loader = (REPO / "src" / "pacthold" / "extensions" / "loader.py").read_text(encoding="utf-8")
    assert 'ENTRY_POINT_GROUP = "agent_box.plugins"' in loader


def test_the_environment_and_data_directory_surfaces_stand():
    runtime = (REPO / "src" / "pacthold" / "work_core" / "runtime.py").read_text(encoding="utf-8")
    assert 'AGENT_BOX_HOME_ENV = "AGENT_BOX_HOME"' in runtime
    assert '"agent-box.db"' in runtime
