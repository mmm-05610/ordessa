"""Synthetic LEGACY data for the Q4/T09 migration tests - no retired code.

The previous fixture built its rows through ``ordessa_server_compat`` (the
legacy ``McpAssetStore.install`` + ``AssetRecords.publish/bind``) on a schema
created by the retired product ``Database``. That package was deleted with
``docs/implementation/specifications/032-architecture-cleanup`` §5d, so this fixture rebuilds the same
legacy facts from scratch:

* the SQLite database carries exactly the two tables the migration tool
  SELECTs (``server_assets`` / ``server_profile_assets``; the column
  definitions mirror the live product schema, see
  ``ordessa_persistence_sqlite.product_database`` ``_migrate_12_to_13``) and is
  written with plain ``sqlite3`` - no retired Database chain, no WAL churn, no
  ``gc.collect``/``settle`` race workaround;
* revision files live at ``<assets_root>/mcp/<asset_id>/<revision>/server.json``
  and are canonicalised + digested with ``backend.definition``
  (``canonical_definition`` / ``definition_digest``), the live digest of
  record for MCP definitions. ``test_digest_agreement.py`` pins explicitly
  that the fixture digests, the tool's scan digests and the live definition
  module agree, instead of assuming the old byte-identical pin;
* :meth:`LegacyDataset.bindings` re-runs the legacy
  ``AssetRecords.bindings(profile_id)`` query verbatim (same raw SQL, same
  camelCase view) - read from the retired module before deletion - so the
  equivalence tests compare the migrated assignment view against the legacy
  join itself, not against the tool under test.

Everything lives under ``tmp_path``; the repo's real data roots are never
touched (AGENTS rule 7).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from backend.definition import canonical_definition, definition_digest

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

#: A non-mcp catalogue row plus a binding on it: the tool's SELECTs filter
#: ``kind='mcp'`` and the inventory must never include it.
SKILL_ASSET_ID = "skill-notes"

SAMPLE_SOURCE = "t09-sample"
SAMPLE_TIME = "2025-01-01T00:00:00Z"

#: The two tables the migration reads, with the live product schema's columns
#: (``persistence-sqlite`` order 58). The fixture creates only these two: the
#: retired plan/migration Database chain is gone and the tool touches nothing
#: else, so FK clauses to tables no SELECT ever reads are omitted.
_LEGACY_SCHEMA = """
CREATE TABLE server_assets (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    latest_revision INTEGER NOT NULL,
    digest TEXT NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE server_profile_assets (
    profile_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, asset_id)
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class LegacyDataset:
    """Paths plus the synthetic legacy facts of one mini old server."""
    data_root: Path
    db_path: Path
    assets_root: Path
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def bindings(self, profile_id: str, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        """The retired ``AssetRecords.bindings(profile_id)`` view, verbatim.

        Same SQL and same key map the deleted compat module used (read from
        the module before deletion), so a test can compare against the legacy
        query instead of re-implementing it inside the tool.
        """
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT b.*,a.kind,a.name,a.digest FROM server_profile_assets b "
                "JOIN server_assets a ON a.id=b.asset_id WHERE b.profile_id=? "
                + ("AND b.enabled=1 " if enabled_only else "")
                + "ORDER BY a.kind,a.name",
                (profile_id,),
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "assetId": row["asset_id"],
                "kind": row["kind"],
                "name": row["name"],
                "revision": int(row["revision"]),
                "digest": row["digest"],
                "enabled": bool(row["enabled"]),
            }
            for row in rows
        ]

    def mcp_bindings(self, profile_id: str) -> list[dict[str, Any]]:
        """The legacy view restricted to mcp rows - exactly what the tool's
        ``_binding_rows`` join hands the migration."""
        return [row for row in self.bindings(profile_id) if row["kind"] == "mcp"]

    def mutate_rows(self, sql: str, params: tuple = ()) -> None:
        """Direct row surgery for counterexample construction."""
        conn = _connect(self.db_path)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()


def _install_revision(assets_root: Path, definition: dict, asset_id: str,
                      revision: int) -> dict[str, Any]:
    """Byte-faithful stand-in for the retired ``McpAssetStore.install``: the
    canonical bytes go on disk and the digest is taken over exactly them."""
    canonical = canonical_definition(definition)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    destination = assets_root / "mcp" / asset_id / str(revision)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "server.json").write_bytes(payload)
    return {
        "asset_id": asset_id,
        "kind": "mcp",
        "revision": revision,
        "digest": definition_digest(canonical),
        "name": canonical["name"],
        "transport": next(iter(canonical["transport"])),
    }


def _publish(conn: sqlite3.Connection, dataset: LegacyDataset, definition: dict,
             asset_id: str, revision: int) -> dict[str, Any]:
    """The retired ``AssetRecords.publish`` row work, raw: install the
    revision file, then insert/update the catalogue row."""
    facts = _install_revision(dataset.assets_root, definition, asset_id, revision)
    dataset.facts[f"{asset_id}@{revision}"] = facts
    existing = conn.execute(
        "SELECT id FROM server_assets WHERE id=?", (asset_id,)).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO server_assets(id, kind, name, description, latest_revision,"
            " digest, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (asset_id, "mcp", facts["name"], None, revision, facts["digest"],
             SAMPLE_SOURCE, SAMPLE_TIME, SAMPLE_TIME),
        )
    else:
        conn.execute(
            "UPDATE server_assets SET name=?, latest_revision=?, digest=?, updated_at=?"
            " WHERE id=?",
            (facts["name"], revision, facts["digest"], SAMPLE_TIME, asset_id),
        )
    conn.commit()
    return facts


def _bind(conn: sqlite3.Connection, profile_id: str, asset_id: str, *,
          revision: Optional[int] = None, enabled: bool = True) -> None:
    """The retired ``AssetRecords.bind`` row work, raw. Like the old code, a
    binding without an explicit revision freezes the asset's current latest."""
    if revision is None:
        row = conn.execute(
            "SELECT latest_revision FROM server_assets WHERE id=?", (asset_id,)).fetchone()
        revision = int(row["latest_revision"])
    conn.execute(
        "INSERT INTO server_profile_assets(profile_id, asset_id, revision, enabled,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (profile_id, asset_id, revision, 1 if enabled else 0, SAMPLE_TIME, SAMPLE_TIME),
    )
    conn.commit()


def build_legacy_dataset(root: Path | str) -> LegacyDataset:
    """A mini legacy server: two profiles, stdio/env-ref/remote mcp assets plus
    a second revision on ``fs-local`` (so a binding can point at an unattested
    revision, exactly as the old wire allowed), the enabled/disabled bindings
    the composition layer used to read, and one non-mcp asset whose binding
    must never leak into the mcp inventory."""
    root = Path(root)
    data_root = root / "legacy-data"
    assets_root = root / "legacy-assets"
    data_root.mkdir(parents=True, exist_ok=True)
    assets_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "legacy.sqlite3"
    dataset = LegacyDataset(
        data_root=data_root, db_path=db_path, assets_root=assets_root)

    conn = _connect(db_path)
    try:
        conn.executescript(_LEGACY_SCHEMA)
        conn.commit()
        _publish(conn, dataset, STDIO_PLAIN, "fs-local", 1)
        _publish(conn, dataset, STDIO_ENV_REF, "env-ref-srv", 1)
        _publish(conn, dataset, REMOTE_HTTPS, "remote-weather", 1)
        # bindings taken while rev1 was latest...
        _bind(conn, "p-alpha", "fs-local", revision=1, enabled=True)
        _bind(conn, "p-alpha", "env-ref-srv", enabled=True)
        _bind(conn, "p-beta", "fs-local", revision=1, enabled=True)
        _bind(conn, "p-beta", "remote-weather", enabled=True)
        _bind(conn, "p-beta", "env-ref-srv", revision=1, enabled=False)
        # ...then a newer revision lands: the row digest moves to rev2 while the
        # existing bindings keep referencing rev1 (legacy view quirk preserved).
        _publish(conn, dataset, STDIO_REV2, "fs-local", 2)
        # a non-mcp row of the same shared catalogue, with a live binding
        conn.execute(
            "INSERT INTO server_assets(id, kind, name, description, latest_revision,"
            " digest, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (SKILL_ASSET_ID, "skill", SKILL_ASSET_ID, "not an mcp asset", 1,
             "sha256:" + "1" * 64, SAMPLE_SOURCE, SAMPLE_TIME, SAMPLE_TIME),
        )
        conn.execute(
            "INSERT INTO server_profile_assets(profile_id, asset_id, revision, enabled,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?)",
            ("p-alpha", SKILL_ASSET_ID, 1, 1, SAMPLE_TIME, SAMPLE_TIME),
        )
        conn.commit()
    finally:
        conn.close()
    return dataset


def build_dangling_binding_dataset(root: Path | str) -> LegacyDataset:
    """Same as :func:`build_legacy_dataset`, then the revision directory a live
    binding references (``fs-local@1``) is removed from disk: the binding
    dangles while the asset row itself stays attested through revision 2."""
    dataset = build_legacy_dataset(root)
    shutil.rmtree(dataset.assets_root / "mcp" / "fs-local" / "1")
    return dataset


def build_digest_mismatch_dataset(root: Path | str) -> LegacyDataset:
    """A healthy install whose ``server_assets.digest`` column is then moved
    off the file digest by row surgery: scan must report the mismatch,
    migrate must refuse adoption (and bindings must not be invented)."""
    dataset = build_legacy_dataset(root)
    dataset.mutate_rows(
        "UPDATE server_assets SET digest=? WHERE id=?",
        ("sha256:" + "0" * 64, "remote-weather"))
    return dataset


def build_name_mismatch_dataset(root: Path | str) -> LegacyDataset:
    """A healthy install whose ``server_assets.name`` column no longer matches
    the revision file's ``name``: another classified refusal, listed, never
    repaired."""
    dataset = build_legacy_dataset(root)
    dataset.mutate_rows(
        "UPDATE server_assets SET name=? WHERE id=?",
        ("renamed-weather", "remote-weather"))
    return dataset
