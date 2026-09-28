"""Run with a fresh interpreter containing only host wheels and dependencies.

Example: ``/tmp/<bare-venv>/bin/python check_bare_host_wheel.py``. The script
intentionally does not alter sys.path or fake absent modules.
"""

from __future__ import annotations

import importlib
from importlib import metadata
import pkgutil
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import ordessa_server
from ordessa_server.bootstrap import (
    LegacyMigrationProviderMissingError, StorageProviderMissingError, build_runtime,
)


class NeutralDatabase:
    """Only the host's server identity table for this wheel smoke test."""

    def __init__(self, root: Path) -> None:
        self.path = root / "state" / "agentbox.sqlite"

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS server_bootstrap ("
                "singleton INTEGER PRIMARY KEY, server_id TEXT NOT NULL, "
                "created_at TEXT NOT NULL)"
            )

    @contextmanager
    def transaction(self):
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    @contextmanager
    def read(self):
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            yield conn


def main() -> None:
    installed = {distribution.metadata["Name"].lower() for distribution in metadata.distributions()}
    assert "pacthold-runtime-compat" not in installed, installed
    assert "ordessa-server-product" not in installed, installed
    assert {"pacthold", "ordessa-server-plugin-api", "ordessa-server"} <= installed
    modules = tuple(pkgutil.walk_packages(ordessa_server.__path__, "ordessa_server."))
    for module in modules:
        importlib.import_module(module.name)

    with TemporaryDirectory(prefix="ordessa-s5-") as temporary:
        root = Path(temporary) / "data"
        try:
            build_runtime(root)
        except RuntimeError as refusal:
            assert "SERVER_PRODUCT_MISSING" in str(refusal), refusal
        else:
            raise AssertionError("missing product was accepted")
        assert not root.exists(), "product refusal wrote the data root"

        try:
            build_runtime(root, server_plugins=())
        except StorageProviderMissingError as refusal:
            assert refusal.code == "SERVER_STORAGE_PROVIDER_MISSING"
        else:
            raise AssertionError("missing storage provider was accepted")
        assert not root.exists(), "storage refusal wrote the data root"

        runtime = build_runtime(root, server_plugins=(), database_factory=NeutralDatabase)
        try:
            runtime.start()
            answer = runtime.wire.hello({
                "clientVersions": ["wire/1"], "clientPresentationSupports": [],
            })
            assert answer["serverId"].startswith("server_")
            assert [item["id"] for item in answer["capabilities"]] == ["server.hello"]
            assert runtime.plugin_host.active_ids() == ()
        finally:
            runtime.stop()

        historical = Path(temporary) / "historical"
        (historical / "state").mkdir(parents=True)
        database_path = historical / "state" / "agentbox.sqlite"
        with sqlite3.connect(database_path) as conn:
            conn.execute("CREATE TABLE schema_versions (version INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO schema_versions VALUES (5)")
        before = database_path.read_bytes()
        try:
            build_runtime(historical, server_plugins=(), database_factory=NeutralDatabase)
        except LegacyMigrationProviderMissingError as refusal:
            assert refusal.code == "LEGACY_MIGRATION_PROVIDER_MISSING"
        else:
            raise AssertionError("missing legacy migration provider was accepted")
        assert database_path.read_bytes() == before
        assert not (historical / ".agentbox-server-root").exists()
        assert not (historical / "server.lock").exists()

    print(f"BARE_HOST_WHEEL_OK imported={len(modules)} distributions=host-only")


if __name__ == "__main__":
    main()
