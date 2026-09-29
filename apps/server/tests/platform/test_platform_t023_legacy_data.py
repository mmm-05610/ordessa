"""T023 (FR-011 / SC-006): historical data roots open, serve and keep their bytes.

The pre-convergence data root is synthesized by code (no historical DB bytes
are committed in this repo), from the sealed legacy chain
``001_init.sql``…``009_execution_finalization.sql`` shipped in
``pacthold_runtime_compat`` — exactly the bytes the old Server wrote, with the
``schema_versions`` ledger rows the old runner recorded.

What this file pins:
- new vs old temporary roots both open and serve, across repeated starts;
- persistent (historical) ids survive every restart unchanged;
- a SQL digest over ordered (migration filename, file-bytes sha256,
  ``schema_versions`` row) plus the ``sqlite_master`` DDL text of the
  chain-built tables is byte-identical across restarts (quickstart §Gates
  历史数据: 旧夹具 + 重复启动 + SQL 摘要);
- the REAL guards refuse a future root (``FutureSchemaError``) and a
  foreign / mis-marked root (``DATA_ROOT_UNOWNED`` / ``DATA_ROOT_MARKER_INVALID``);
- the missing-legacy-provider case refuses before marker/schema writes and
  preserves the original database bytes and ledger.

Every root here lives under ``tmp_path`` (SC-006); the guard counterexample
against a real-home leak is ``test_platform_t023_sc006_state_isolation.py``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ordessa_server.bootstrap import (
    DataRootPathUnsafeError, LegacyMigrationProviderMissingError, build_runtime,
)
from ordessa_server.bootstrap import runtime as bootstrap_runtime
from ordessa_server.transport.http import create_app
from pacthold_runtime_compat.legacy_migrations import (
    MIGRATIONS_DIR,
    register_legacy_migrations,
)
from pacthold_runtime_compat.storage import FutureSchemaError, PRODUCT_SCHEMA_VERSION
from pacthold.work_core import db as core_db

OWNER_MARKER_NAME = ".agentbox-server-root"
OWNER_MARKER_TEXT = "agentbox-server-r1\n"
DATABASE_NAME = Path("state") / "agentbox.sqlite"
HISTORICAL_WORK_ID = "work-historical-0001"
HISTORICAL_OBJECTIVE = "objective sealed before the convergence"
_CREATE_TABLE = re.compile(r"CREATE TABLE(?: IF NOT EXISTS)? (\w+)", re.IGNORECASE)


def _assert_scratch_root(root: Path, tmp_path: Path) -> Path:
    # SC-006: every root this fixture builds is under the scratch area.
    root = root.resolve()
    return root if _under(root, tmp_path) else pytest.fail(
        f"SC-006: fixture root {root} escaped the scratch area {tmp_path}")


def _under(candidate: Path, parent: Path) -> bool:
    parent = parent.resolve()
    return candidate == parent or str(candidate).startswith(str(parent) + os.sep)


def _chain_files() -> list[Path]:
    files = sorted(
        (f for f in MIGRATIONS_DIR.iterdir() if re.match(r"^\d{3}_.*\.sql$", f.name)),
        key=lambda f: f.name,
    )
    assert len(files) == 9, f"sealed chain must hold 001..009, found {[f.name for f in files]}"
    return files


def _connect(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(root / DATABASE_NAME))
    conn.row_factory = sqlite3.Row
    return conn


def synthesize_historical_root(
    tmp_path: Path, name: str, *, through_version: int, product_stamp: int | None = None,
) -> Path:
    """Build the bytes an old Server left: sealed chain 001..00N + ledger rows.

    The ``schema_versions`` table is created with exactly the shape the
    current runner accepts unchanged, and the historical id row is seeded
    into ``core_works`` (chain-built since 003) so survival is observable.
    ``product_stamp=None`` means no product marker table at all — the true
    pre-host shape; any integer writes an ``agentbox_product_schema`` row.
    """
    root = _assert_scratch_root(tmp_path / name, tmp_path)
    (root / "state").mkdir(parents=True)
    (root / OWNER_MARKER_NAME).write_text(OWNER_MARKER_TEXT, encoding="utf-8")
    conn = _connect(root)
    conn.execute(
        "CREATE TABLE schema_versions "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    for path in _chain_files():
        version = int(path.name[:3])
        if version <= through_version:
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_versions (version) VALUES (?)", (version,))
    conn.execute(
        "INSERT INTO core_works (id, objective, lifecycle, created_at, updated_at) "
        "VALUES (?, ?, 'active', '2026-01-01 00:00:00', '2026-01-01 00:00:00')",
        (HISTORICAL_WORK_ID, HISTORICAL_OBJECTIVE),
    )
    if product_stamp is not None:
        conn.execute(
            "CREATE TABLE agentbox_product_schema ("
            "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
            "version INTEGER NOT NULL, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO agentbox_product_schema VALUES (1, ?, '2026-01-01 00:00:00')",
            (product_stamp,),
        )
    conn.commit()
    conn.close()
    return root


def legacy_versions(root: Path) -> list[int]:
    conn = _connect(root)
    try:
        return [row[0] for row in conn.execute(
            "SELECT version FROM schema_versions ORDER BY version")]
    finally:
        conn.close()


def historical_row(root: Path) -> tuple | None:
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT id, objective, lifecycle FROM core_works WHERE id = ?",
            (HISTORICAL_WORK_ID,)).fetchone()
        return tuple(row) if row is not None else None
    finally:
        conn.close()


def chain_digest(root: Path) -> str:
    """SHA-256 over ordered (migration filename, file-bytes sha256,
    ``schema_versions`` row) plus the ``sqlite_master`` DDL text of every
    chain-built table that exists in this root."""
    ledger: dict[int, tuple] = {}
    conn = _connect(root)
    try:
        for row in conn.execute("SELECT version, applied_at FROM schema_versions"):
            ledger[int(row["version"])] = (int(row["version"]), row["applied_at"])
        chain_tables: set[str] = set()
        triples = []
        for path in _chain_files():
            data = path.read_bytes()
            version = int(path.name[:3])
            triples.append([path.name, hashlib.sha256(data).hexdigest(), ledger.get(version)])
            chain_tables.update(_CREATE_TABLE.findall(data.decode("utf-8")))
        ddl = [
            [name, sql] for name, sql in sorted(
                (row[0], row[1]) for row in conn.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type='table'"))
            if name in chain_tables
        ]
    finally:
        conn.close()
    assert all(entry[2] is not None for entry in triples), \
        "every sealed-chain version must hold a ledger row in a fully applied root"
    assert len(ddl) >= 10, "the chain-built table set must not be vacuously small"
    payload = json.dumps({"triples": triples, "ddl": ddl}, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def open_serve_and_stop(root: Path, rounds: int = 1) -> list[str]:
    """Repeated start rounds; each round SERVES through the composed App.

    Returns ``server.hello``'s ``serverId`` per round — the identity the
    host mints once per data root and must keep stable across restarts.
    """
    server_ids = []
    for _ in range(rounds):
        runtime = build_runtime(root)
        try:
            runtime.start()
            client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
            answer = client.post(
                "/wire/v1/server.hello",
                headers={"Authorization": f"Bearer {runtime.token}"},
                json={"jsonrpc": "2.0", "id": "t023", "method": "server.hello",
                      "params": {"clientVersions": ["wire/1"],
                                 "clientPresentationSupports": []}},
            )
            assert answer.status_code == 200, answer.text
            body = answer.json()
            assert "result" in body, body
            server_ids.append(body["result"]["serverId"])
        finally:
            runtime.stop()
    return server_ids


# --- deliverables (1) + (2): open-and-serve, ids and SQL digest survive ----


def test_new_and_old_temporary_roots_open_serve_and_keep_historical_ids(tmp_path):
    """(1) 新旧临时库: a synthesized pre-convergence root and a fresh root
    both open, serve ``server.hello``, and keep persistent ids across three
    repeated starts (FR-011)."""
    old_root = synthesize_historical_root(tmp_path, "old-root", through_version=9)
    assert legacy_versions(old_root) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    seeded = historical_row(old_root)
    assert seeded == (HISTORICAL_WORK_ID, HISTORICAL_OBJECTIVE, "active")

    old_ids = open_serve_and_stop(old_root, rounds=3)
    assert len(set(old_ids)) == 1, "server identity must be stable across restarts"
    assert legacy_versions(old_root) == [1, 2, 3, 4, 5, 6, 7, 8, 9], \
        "repeated starts renumbered or re-applied the sealed ledger"
    assert historical_row(old_root) == seeded, "historical id did not survive"

    new_root = _assert_scratch_root(tmp_path / "new-root", tmp_path)  # does not exist yet
    first_ids = open_serve_and_stop(new_root, rounds=1)
    # a persistent id minted on the fresh root must survive its restarts too
    conn = _connect(new_root)
    conn.execute(
        "INSERT INTO core_works (id, objective, lifecycle, created_at, updated_at) "
        "VALUES (?, ?, 'active', datetime('now'), datetime('now'))",
        (HISTORICAL_WORK_ID, "id minted on the fresh root"))
    conn.commit()
    conn.close()
    later_ids = open_serve_and_stop(new_root, rounds=2)
    assert [*(first_ids), *later_ids].count(first_ids[0]) == 3
    assert historical_row(new_root) == (HISTORICAL_WORK_ID, "id minted on the fresh root", "active")
    assert legacy_versions(new_root) == [1, 2, 3, 4, 5, 6, 7, 8, 9], \
        "the fresh product root must carry the same sealed chain"


def test_sql_bytes_and_ddl_digest_is_identical_across_repeated_starts(tmp_path):
    """(2) SQL 摘要: the digest over ordered (filename, file-bytes sha256,
    ledger row) + chain-table DDL text is byte-stable across restarts — a
    re-application, renumbering or DDL rewrite on start changes it."""
    for name, through in (("digest-old", 9),):
        root = synthesize_historical_root(tmp_path, name, through_version=through)
        before = chain_digest(root)
        open_serve_and_stop(root, rounds=2)
        assert chain_digest(root) == before, f"restart changed the SQL digest of {name}"
    fresh = _assert_scratch_root(tmp_path / "digest-new", tmp_path)
    open_serve_and_stop(fresh, rounds=1)
    built = chain_digest(fresh)
    open_serve_and_stop(fresh, rounds=1)
    assert chain_digest(fresh) == built, "restart changed the fresh root's digest"


# --- deliverable (3): the REAL guards refuse newer / foreign roots ---------


def test_a_newer_than_supported_root_is_refused_by_the_real_future_guard(tmp_path):
    """schema 22 > PRODUCT_SCHEMA_VERSION 21 must leave as the shipped
    ``FutureSchemaError``, not a silent downgrade or a generic crash."""
    root = synthesize_historical_root(
        tmp_path, "future-root", through_version=9, product_stamp=PRODUCT_SCHEMA_VERSION + 1)
    # S-03/S-06：schema 拒绝前移到 composition（build_runtime）；此刻尚无插件
    # 激活、无 stop 清场需求——data-root lock 在 _resolve 阶段尚未获取。
    with pytest.raises(FutureSchemaError, match="newer than supported"):
        build_runtime(root)
    assert legacy_versions(root) == [1, 2, 3, 4, 5, 6, 7, 8, 9], \
        "the refused root must be untouched"


def test_an_existing_directory_without_the_owner_marker_is_refused(tmp_path):
    """DATA_ROOT_UNOWNED: a directory this Server never marked is foreign
    ground — the host must not claim it."""
    foreign = _assert_scratch_root(tmp_path / "foreign", tmp_path)
    foreign.mkdir()
    (foreign / "someone-elses-file").write_text("do not touch", encoding="utf-8")
    with pytest.raises(RuntimeError, match="DATA_ROOT_UNOWNED"):
        build_runtime(foreign)
    assert (foreign / "someone-elses-file").read_text(encoding="utf-8") == "do not touch"


def test_a_root_marked_with_a_foreign_marker_identity_is_refused(tmp_path):
    """DATA_ROOT_MARKER_INVALID: an existing marker with other content names
    a different root generation; refusing beats rewriting it in place."""
    root = _assert_scratch_root(tmp_path / "wrong-marker", tmp_path)
    root.mkdir()
    (root / OWNER_MARKER_NAME).write_text("agentbox-server-r9999\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="DATA_ROOT_MARKER_INVALID"):
        build_runtime(root)
    assert (root / OWNER_MARKER_NAME).read_text(encoding="utf-8") == "agentbox-server-r9999\n"


# --- deliverable (4): the missing-provider case ----------------------------


def test_missing_legacy_provider_refuses_before_writing_historical_root(tmp_path):
    """A partial legacy ledger requires the sealed provider before any write."""
    root = synthesize_historical_root(tmp_path, "gap-root", through_version=5)
    database_path = root / DATABASE_NAME
    original_bytes = database_path.read_bytes()
    original_marker = (root / OWNER_MARKER_NAME).read_bytes()
    assert legacy_versions(root) == [1, 2, 3, 4, 5]
    # An explicit bare composition must not inherit the default product's
    # provider. Clear process state before build_runtime's first write.
    core_db.configure_database(None)
    core_db._reset_registered_migration_sources_for_tests()
    try:
        assert [s.namespace for s in core_db.registered_migration_sources()] == \
            [core_db.CORE_MIGRATION_NAMESPACE]
        with pytest.raises(LegacyMigrationProviderMissingError) as refusal:
            build_runtime(root, server_plugins=())
        assert refusal.value.code == "LEGACY_MIGRATION_PROVIDER_MISSING"
        assert database_path.read_bytes() == original_bytes
        assert (root / OWNER_MARKER_NAME).read_bytes() == original_marker
        assert not (root / "server.lock").exists()
        assert legacy_versions(root) == [1, 2, 3, 4, 5]
        assert not (root / "secrets" / "http-token").exists()
    finally:
        core_db.configure_database(None)
        register_legacy_migrations()  # restore process state for the suite


def test_control_same_partial_root_converges_when_the_provider_is_registered(tmp_path):
    """Non-vacuity for the gap test above: the identical [1..5] fixture DOES
    converge to [1..9] when the provider is registered, so the stale result
    in the gap case is caused by the missing provider, not a dead fixture."""
    root = synthesize_historical_root(tmp_path, "control-root", through_version=5)
    register_legacy_migrations()
    runtime = build_runtime(root)
    try:
        runtime.start()
    finally:
        runtime.stop()
    assert legacy_versions(root) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    conn = _connect(root)
    try:
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'core_dispatches_pre_v006_archive'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_default_product_assembles_provider_before_preflight(tmp_path, monkeypatch):
    """The production product selection registers the legacy source first."""
    root = synthesize_historical_root(tmp_path, "default-product", through_version=5)
    marker_bytes = (root / OWNER_MARKER_NAME).read_bytes()
    database_bytes = (root / DATABASE_NAME).read_bytes()
    actual_composition = bootstrap_runtime._resolve_product_composition()

    class ObservedComposition:
        def default_plugins(self):
            selected = actual_composition.default_plugins()
            assert (root / OWNER_MARKER_NAME).read_bytes() == marker_bytes
            assert (root / DATABASE_NAME).read_bytes() == database_bytes
            assert not (root / "server.lock").exists()
            assert not (root / "secrets" / "http-token").exists()
            return selected

        def database_type(self):
            return actual_composition.database_type()

        def server_contribution_points(self):
            return actual_composition.server_contribution_points()

    monkeypatch.setattr(bootstrap_runtime, "_resolve_product_composition", lambda: ObservedComposition())
    core_db.configure_database(None)
    core_db._reset_registered_migration_sources_for_tests()
    try:
        runtime = build_runtime(root)
        try:
            assert any(source.namespace == "agent_box_legacy"
                       for source in core_db.registered_migration_sources())
            runtime.start()
        finally:
            runtime.stop()
        assert legacy_versions(root) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    finally:
        core_db.configure_database(None)
        register_legacy_migrations()


@pytest.mark.parametrize("link_kind", ["state", "database"])
def test_symlinked_historical_database_path_is_refused_without_read_or_write(tmp_path, link_kind):
    external = synthesize_historical_root(tmp_path, "external", through_version=5)
    external_database = external / DATABASE_NAME
    external_bytes = external_database.read_bytes()
    root = _assert_scratch_root(tmp_path / f"link-{link_kind}", tmp_path)
    root.mkdir()
    (root / OWNER_MARKER_NAME).write_text(OWNER_MARKER_TEXT, encoding="utf-8")
    marker_bytes = (root / OWNER_MARKER_NAME).read_bytes()
    if link_kind == "state":
        (root / "state").symlink_to(external / "state", target_is_directory=True)
    else:
        (root / "state").mkdir()
        (root / DATABASE_NAME).symlink_to(external_database)
    # A guard after SQLite open would hit this witness. The explicit bare
    # composition keeps the default product out of this path-safety test.
    with patch.object(bootstrap_runtime.sqlite3, "connect", side_effect=AssertionError("read outside root")) as connect:
        with pytest.raises(DataRootPathUnsafeError) as refusal:
            build_runtime(root, server_plugins=())
        connect.assert_not_called()
    assert refusal.value.code == "DATA_ROOT_PATH_UNSAFE"
    assert external_database.read_bytes() == external_bytes
    assert (root / OWNER_MARKER_NAME).read_bytes() == marker_bytes
    assert not (root / "server.lock").exists()
    assert not (root / "secrets" / "http-token").exists()


def test_default_product_selection_runs_before_root_writes(tmp_path, monkeypatch):
    root = synthesize_historical_root(tmp_path, "selection", through_version=5)
    database_bytes = (root / DATABASE_NAME).read_bytes()
    marker_bytes = (root / OWNER_MARKER_NAME).read_bytes()
    observed = []

    class SelectionProbe:
        def default_plugins(self):
            assert not (root / "server.lock").exists()
            assert not (root / "secrets" / "http-token").exists()
            assert (root / OWNER_MARKER_NAME).read_bytes() == marker_bytes
            assert (root / DATABASE_NAME).read_bytes() == database_bytes
            observed.append("selected-before-write")
            return ()

    monkeypatch.setattr(bootstrap_runtime, "_resolve_product_composition", lambda: SelectionProbe())
    core_db.configure_database(None)
    core_db._reset_registered_migration_sources_for_tests()
    try:
        with pytest.raises(LegacyMigrationProviderMissingError):
            build_runtime(root)
        assert observed == ["selected-before-write"]
        assert (root / DATABASE_NAME).read_bytes() == database_bytes
        assert (root / OWNER_MARKER_NAME).read_bytes() == marker_bytes
    finally:
        core_db.configure_database(None)
        register_legacy_migrations()
