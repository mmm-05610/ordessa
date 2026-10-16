"""Old in-place Profile store upgrades have no current runtime owner."""
from __future__ import annotations

import importlib
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


def test_old_store_schema_is_preserved_as_bytes_without_automatic_upgrade(tmp_path):
    old_store = tmp_path / "old-profile-store.sqlite"
    with sqlite3.connect(old_store) as connection:
        connection.execute("CREATE TABLE profile_profiles(profile_id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO profile_profiles VALUES('historical-id')")
    before = old_store.read_bytes()

    with pytest.raises(MODULE.LegacyProfileImportRetired, match="retired"):
        MODULE.import_legacy(old_store, target=object())

    assert old_store.read_bytes() == before
    with sqlite3.connect(old_store) as connection:
        assert connection.execute(
            "SELECT profile_id FROM profile_profiles").fetchone()[0] == "historical-id"


def test_profile_store_upgrade_implementation_is_not_a_runtime_import():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ordessa_persistence_sqlite.profile_store")
