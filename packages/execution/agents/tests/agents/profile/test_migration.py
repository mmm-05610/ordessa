"""Legacy Profile import is retired and cannot touch its source or target."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3

import pytest


ROOT = Path(__file__).resolve().parents[6]
SPEC = importlib.util.spec_from_file_location(
    "import_legacy_server_profiles",
    ROOT / "tooling/migrations/import_legacy_server_profiles.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_retired_importer_refuses_before_opening_or_changing_source(tmp_path):
    source = tmp_path / "historical-server-profiles.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE server_profiles(id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO server_profiles VALUES('preserve-me')")
    before = source.read_bytes()

    with pytest.raises(MODULE.LegacyProfileImportRetired, match="no current import destination"):
        MODULE.import_legacy(source, target=object())

    assert source.read_bytes() == before


def test_retired_importer_does_not_create_a_missing_source(tmp_path):
    source = tmp_path / "must-not-be-created.sqlite"
    with pytest.raises(MODULE.LegacyProfileImportRetired, match="retired"):
        MODULE.import_legacy(source, target=object())
    assert not source.exists()
