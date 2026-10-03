"""Synthetic LEGACY data built entirely with the real legacy pieces.

No fake interfaces: the mini database is created by pacthold's
``Database`` (full migration chain to the current product schema, including
the 12→13 DDL that owns ``server_assets``/``server_profile_assets``), the
rows are written by ``ordessa_server_compat.assets.records.AssetRecords``
(``publish``/``bind``), and the revision files are installed by
``ordessa_server_compat.assets.mcp.McpAssetStore.install`` — the same code
path the old server used. Everything lives under ``tmp_path``; the repo's
real data roots are never touched (AGENTS rule 7).
"""
from __future__ import annotations

import gc
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.assets import mcp as legacy_mcp
from ordessa_server_compat.assets.records import AssetRecords
from pacthold_runtime_compat.storage import Database

# -- the three transport shapes, one sample each --------------------------------

STDIO_PLAIN = {
    "name": "fs-local",
    "transport": {"stdio": {"command": "/usr/local/bin/fake-mcp", "args": ["--stdio"]}},
}
STDIO_ENV_REF = {
    "name": "env-ref-srv",
    "transport": {"stdio": {
        "command": "/opt/bin/env-srv", "args": ["-v"],
        "env": {"API_TOKEN": {"credentialRef": "cred-token-1"}},
    }},
}
REMOTE_HTTPS = {
    "name": "remote-weather",
    "transport": {"remote": {
        "url": "https://mcp.example.test/weather",
        "headers": {"Authorization": {"credentialRef": "cred-oauth-2"}},
    }},
}
STDIO_REV2 = {
    "name": "fs-local",
    "transport": {"stdio": {
        "command": "/usr/local/bin/fake-mcp", "args": ["--stdio", "--tag", "r2"]}},
}

PROFILES = ("p-alpha", "p-beta")


def settle() -> None:
    """Force the legacy ``Database`` bookkeeping to quiesce.

    ``pacthold_runtime_compat.storage.Database.initialize()`` keeps its
    connection in a ``with sqlite3.connect(...) as conn`` scope that never
    closes it explicitly; whenever the garbage collector eventually reclaims
    it, SQLite runs its final WAL checkpoint - rewriting the main database
    file and deleting ``-wal``/``-shm``. That is the legacy server's own
    churn, not the migration's, but it would make any before/after byte
    snapshot race against GC. Collecting here settles it deterministically.
    """
    gc.collect()


@dataclass
class LegacyDataset:
    """Paths plus the live legacy record layer of one synthetic old server."""
    data_root: Path
    db_path: Path
    assets_root: Path
    records: AssetRecords
    database: Database
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def binding_view(self, profile_id: str) -> list[dict[str, Any]]:
        return self.records.bindings(profile_id)

    def mutate_rows(self, sql: str, params: tuple = ()) -> None:
        """Direct row surgery for counterexample construction (still through
        the real Database transaction scope)."""
        with self.database.transaction() as conn:
            conn.execute(sql, params)


def _insert_profile(database: Database, profile_id: str) -> None:
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_profiles(id, name, harness_type, config_revision,"
            " config_object_digest, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (profile_id, f"profile {profile_id}", "acp", 1, "sha256:" + "0" * 64,
             "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
        )


def build_legacy_dataset(root: Path | str) -> LegacyDataset:
    """A mini legacy server: two profiles, stdio/env-ref/remote assets plus a
    second revision on ``fs-local`` (so a binding can point at an unattested
    revision, exactly as the old wire allowed), and the enabled/disabled
    bindings the composition layer used to read."""
    root = Path(root)
    data_root = root / "legacy-data"
    assets_root = root / "legacy-assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    database = Database(data_root)
    database.initialize()
    records = AssetRecords(database, IdempotentRecords(database))
    store = legacy_mcp.McpAssetStore(assets_root)

    dataset = LegacyDataset(
        data_root=data_root, db_path=database.path, assets_root=assets_root,
        records=records, database=database)
    for profile_id in PROFILES:
        _insert_profile(database, profile_id)

    def publish(definition: dict, asset_id: str, revision: int) -> dict:
        facts = store.install(definition, asset_id=asset_id, revision=revision)
        records.publish(
            key=f"publish:{asset_id}:{revision}", request_digest=facts["digest"],
            kind="mcp", name=facts["name"], revision=facts["revision"],
            digest=facts["digest"], source="t09-sample", asset_id=asset_id)
        dataset.facts[f"{asset_id}@{revision}"] = facts
        return facts

    publish(STDIO_PLAIN, "fs-local", 1)
    publish(STDIO_ENV_REF, "env-ref-srv", 1)
    publish(REMOTE_HTTPS, "remote-weather", 1)
    # bindings taken while rev1 was latest...
    records.bind(profile_id="p-alpha", asset_id="fs-local", revision=1, enabled=True)
    records.bind(profile_id="p-alpha", asset_id="env-ref-srv", enabled=True)
    records.bind(profile_id="p-beta", asset_id="fs-local", revision=1, enabled=True)
    records.bind(profile_id="p-beta", asset_id="remote-weather", enabled=True)
    records.bind(profile_id="p-beta", asset_id="env-ref-srv", revision=1, enabled=False)
    # ...then a newer revision lands: the row digest moves to rev2 while the
    # existing bindings keep referencing rev1 (legacy view quirk preserved).
    publish(STDIO_REV2, "fs-local", 2)
    settle()
    return dataset


def build_dangling_binding_dataset(root: Path | str) -> LegacyDataset:
    """Same as :func:`build_legacy_dataset`, then the revision file a live
    binding references (``fs-local@1``) is removed from disk: the binding
    dangles while the asset row itself stays attested through revision 2."""
    dataset = build_legacy_dataset(root)
    shutil.rmtree(dataset.assets_root / "mcp" / "fs-local" / "1")
    settle()
    return dataset


def build_digest_mismatch_dataset(root: Path | str) -> LegacyDataset:
    """A healthy install whose ``server_assets.digest`` column is then moved
    off the file digest by row surgery: scan must report the mismatch,
    migrate must refuse adoption (and bindings must not be invented)."""
    dataset = build_legacy_dataset(root)
    dataset.mutate_rows(
        "UPDATE server_assets SET digest=? WHERE id=?",
        ("sha256:" + "0" * 64, "remote-weather"))
    settle()
    return dataset
