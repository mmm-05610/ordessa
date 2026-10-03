from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition
from ordessa_server.credentials import CredentialRecords
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.profiles import ProfileRecords, ProfileService
from ordessa_server.transport.http import create_app
from pacthold_runtime_compat.storage import Database, FutureSchemaError, ObjectStore
from pacthold_runtime_compat.storage import database as product_db
from pacthold_runtime_compat.legacy_migrations import db as core_db


def codex_validator(value):
    if not isinstance(value, dict):
        raise ValueError()
    return None


def codex_registry(claims=None):
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        "codex", credential_kind="codex-login",
        configuration_validator=codex_validator, capability_claims=claims or {},
    ))
    return registry


class WslFixture:
    def __init__(self):
        self.open_calls = 0

    def distributions(self):
        return [{"name": "Ubuntu", "state": "running", "version": 2}]

    def probe(self, distribution, user):
        return {"probe_id": "probe_fixture", "distribution": distribution, "user": user, "expires_in": 30}

    def browse(self, probe_id, path):
        return {"probe_id": probe_id, "path": path, "directories": ["中文 空格"]}

    def open_workspace(self, probe_id, path):
        self.open_calls += 1
        return {"connection_id": "conn_fixture", "distribution": "Ubuntu", "user": "tester", "path": path}


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "server-data"
    runtime = build_runtime(
        root,
        server_plugins=create_composition().compatibility_plugins(
            harnesses=codex_registry(),
            connector=WslFixture()),
    )
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": f"Bearer {runtime.token}"}
        yield runtime, client, headers


def post(client, headers, path, body, key):
    return client.post(path, headers={**headers, "Idempotency-Key": key}, json=body)


def test_liveness_is_minimal_and_every_product_route_requires_auth(server):
    _runtime, client, headers = server
    assert client.get("/live").json() == {"status": "alive"}
    denied = client.get("/api/v1/readiness")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    ready = client.get("/api/v1/readiness", headers=headers)
    assert ready.status_code == 200
    codex = ready.json()["capabilities"]["harnesses"]["codex"]
    assert codex["available"] is False
    assert codex["capability_claims"] == {}
    assert codex["unavailable_reason"] == "EXECUTION_CAPABILITY_UNAVAILABLE"
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/api/v1/openapi.json").status_code == 401
    assert client.get("/api/v1/openapi.json", headers=headers).status_code == 200


def test_host_origin_and_strict_json_are_independent_guards(server):
    _runtime, client, headers = server
    assert client.get("/live", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/v1/readiness", headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    invalid = post(client, headers, "/api/v1/profiles", {
        "name": "role", "harness_type": "codex", "configuration": {}, "extra": True,
    }, "profile-extra")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "REQUEST_INVALID"


def test_profile_workspace_and_session_records_are_idempotent(server):
    runtime, client, headers = server
    workspace_body = {"probe_id": "probe_fixture", "path": "/home/tester/中文 空格"}
    first_workspace = post(client, headers, "/api/v1/workspaces", workspace_body, "workspace-1")
    assert first_workspace.status_code == 201
    assert post(client, headers, "/api/v1/workspaces", workspace_body, "workspace-1").json() == first_workspace.json()
    assert runtime.plugin_host.provided_port('product.service').workspaces.connector.open_calls == 1

    profile_body = {
        "name": "Codex role", "harness_type": "codex",
        "configuration": {"model": "configured-later"}, "credential_id": None,
    }
    first_profile = post(client, headers, "/api/v1/profiles", profile_body, "profile-1")
    assert first_profile.status_code == 201
    assert post(client, headers, "/api/v1/profiles", profile_body, "profile-1").json() == first_profile.json()
    conflict = post(client, headers, "/api/v1/profiles", {**profile_body, "name": "other"}, "profile-1")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    session_body = {
        "workspace_id": first_workspace.json()["workspace_id"],
        "profile_id": first_profile.json()["profile_id"],
    }
    session = post(client, headers, "/api/v1/sessions", session_body, "session-1")
    assert session.status_code == 201
    assert client.get(f"/api/v1/sessions/{session.json()['session_id']}", headers=headers).status_code == 200



def test_product_records_survive_server_restart(tmp_path):
    root = tmp_path / "restart"
    first = build_runtime(root, server_plugins=create_composition().compatibility_plugins(
        harnesses=codex_registry(), connector=WslFixture()))
    with TestClient(create_app(first), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": f"Bearer {first.token}"}
        workspace = post(client, headers, "/api/v1/workspaces", {"probe_id": "probe_fixture", "path": "/workspace"}, "w")
        profile = post(client, headers, "/api/v1/profiles", {"name": "role", "harness_type": "codex", "configuration": {}}, "p")
        session = post(client, headers, "/api/v1/sessions", {
            "workspace_id": workspace.json()["workspace_id"], "profile_id": profile.json()["profile_id"],
        }, "s")
        session_id = session.json()["session_id"]
        token = first.token
    second = build_runtime(root, server_plugins=create_composition().compatibility_plugins(
        harnesses=codex_registry(), connector=WslFixture()))
    assert second.token == token
    with TestClient(create_app(second), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": f"Bearer {token}"}
        assert len(client.get("/api/v1/workspaces", headers=headers).json()["items"]) == 1
        assert len(client.get("/api/v1/profiles", headers=headers).json()["items"]) == 1
        assert client.get(f"/api/v1/sessions/{session_id}", headers=headers).status_code == 200


def test_secret_shaped_configuration_is_rejected_before_object_publication(server):
    runtime, client, headers = server
    response = post(client, headers, "/api/v1/profiles", {
        "name": "unsafe", "harness_type": "codex",
        "configuration": {"api_token": "must-not-be-read-or-stored"},
    }, "unsafe-profile")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SECRET_FIELD_FORBIDDEN"
    assert not list((runtime.data_root / "objects").rglob("*"))


def test_unconfigured_runtime_reports_typed_capability_blockers(tmp_path):
    runtime = build_runtime(tmp_path / "unavailable")
    # A Server with no connector can still serve local workspaces whenever the
    # host can run the room; this test pins the typed-blocker contract on a
    # host where it cannot, so the blocker names the placement that is missing.
    from ordessa_workspace.local_environment import LocalEnvironmentProvider
    runtime.plugin_host.provided_port('product.service').workspaces.local = LocalEnvironmentProvider(
        sandbox_probe=lambda: {"status": "unavailable", "code": "binary_missing"},
    )
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": f"Bearer {runtime.token}"}
        readiness = client.get("/api/v1/readiness", headers=headers).json()
        assert {item["code"] for item in readiness["blockers"]} == {
            "LOCAL_SANDBOX_UNAVAILABLE", "EXECUTION_CAPABILITY_UNAVAILABLE",
        }
        assert readiness["capabilities"]["harnesses"] == {}
        assert readiness["capabilities"]["execution"] is False
        response = client.get("/api/v1/wsl/distributions", headers=headers)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "WSL_CONNECTOR_UNAVAILABLE"


def test_future_schema_refuses_startup_without_overwrite(tmp_path):
    root = tmp_path / "future"
    runtime = build_runtime(root)
    runtime.start()
    runtime.stop()
    with sqlite3.connect(root / "state" / "agentbox.sqlite") as conn:
        conn.execute("UPDATE agentbox_product_schema SET version=999 WHERE singleton=1")
    with pytest.raises(FutureSchemaError):
        build_runtime(root)
    with sqlite3.connect(root / "state" / "agentbox.sqlite") as conn:
        assert conn.execute("SELECT version FROM agentbox_product_schema").fetchone()[0] == 999


def test_existing_unowned_directory_is_refused_without_modification(tmp_path):
    root = tmp_path / "unowned"
    root.mkdir()
    sentinel = root / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(RuntimeError, match="DATA_ROOT_UNOWNED"):
        build_runtime(root)
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert set(path.name for path in root.iterdir()) == {"sentinel.txt"}


def test_root_created_by_ensure_data_root_owns_itself(tmp_path):
    """B-005 / C-01 §3: the creator claims the root it creates.

    The CLI creates the root through `ensure_data_root` before
    `build_runtime` runs; without the owner marker written at creation time
    the runtime refuses the fresh root as foreign (DATA_ROOT_UNOWNED) and a
    first start can never succeed. This is that exact path — the directory is
    NOT pre-marked by the test.
    """
    from ordessa_server.bootstrap.data_root import (
        OWNER_MARKER_CONTENT,
        OWNER_MARKER_NAME,
        ensure_data_root,
        resolve_data_root,
    )

    created = ensure_data_root(resolve_data_root({}, home=str(tmp_path)))
    assert created.created is True
    marker = created.path / OWNER_MARKER_NAME
    assert marker.read_text(encoding="utf-8") == OWNER_MARKER_CONTENT

    runtime = build_runtime(created.path)
    try:
        assert runtime is not None
    finally:
        runtime.stop()


def test_data_root_with_a_foreign_owner_marker_is_refused(tmp_path):
    root = tmp_path / "foreign"
    root.mkdir()
    (root / ".agentbox-server-root").write_text("agentbox-server-r9\n", encoding="utf-8")
    sentinel = root / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(RuntimeError, match="DATA_ROOT_MARKER_INVALID"):
        build_runtime(root)
    assert sentinel.read_text(encoding="utf-8") == "preserve"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not Windows ACL evidence")
def test_bootstrap_token_is_owner_only_on_posix(tmp_path):
    runtime = build_runtime(tmp_path / "protected-token")
    try:
        assert runtime.token_path.stat().st_mode & 0o777 == 0o600
    finally:
        runtime.stop()


def test_data_roots_are_isolated_and_single_owner_is_enforced(tmp_path):
    first = build_runtime(tmp_path / "one")
    second = build_runtime(tmp_path / "two")
    first.start()
    try:
        with pytest.raises(RuntimeError, match="DATA_ROOT_IN_USE"):
            build_runtime(tmp_path / "one")
        second.start()
        try:
            assert first.database.path != second.database.path
            with first.database.read() as first_conn, second.database.read() as second_conn:
                assert first_conn.execute("PRAGMA database_list").fetchone()[2] != second_conn.execute("PRAGMA database_list").fetchone()[2]
        finally:
            second.stop()
    finally:
        first.stop()


def test_object_failure_cannot_leave_a_dangling_profile_reference(tmp_path):
    class BrokenObjects(ObjectStore):
        def publish(self, content):
            raise OSError("injected publish failure")

    database = Database(tmp_path / "broken")
    database.initialize()
    idempotency = IdempotentRecords(database)
    service = ProfileService(
        ProfileRecords(database, idempotency), idempotency,
        BrokenObjects(tmp_path / "broken"),
        harnesses=codex_registry(), credentials=CredentialRecords(database),
    )
    with pytest.raises(OSError, match="injected"):
        service.create("key", {
            "name": "role", "harness_type": "codex", "configuration": {}, "credential_id": None,
        })
    with database.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM server_profiles").fetchone()[0] == 0


def test_core_uses_the_server_owned_database_file(tmp_path):
    """S1c target state (026 T006-01 first half): the execution chain rides
    the composition's instance store, and the server owns its file.

    Change note (assertions re-pointed, none deleted — the S1c entry in
    `docs/known-issues.md` names this ID as the one to move onto the instance
    store): the original gate proved via `PRAGMA database_list` that the
    process-global legacy connection resolved to the server-owned product
    database — at the time the only "Core" the execution chain had. Since the
    instance-store injection landed, the execution chain (the sidecar
    backend's WorkService/ExecutionService, the reach the S1c entry measures)
    no longer touches that global at all: the host's C1 instance store
    (`state/core.sqlite`, the `CoreBinding` seam) IS the chain's store. The
    gate now asserts that target state directly — the injected store is the
    binding's own connection and a chain filing lands in the instance file,
    never in the legacy one — while keeping both original halves that remain
    true: the instance store is server-owned (its own file, never the legacy
    one), and the LEGACY binding still binds exactly the server-owned legacy
    database (its semantics are unchanged; retiring it is the next T006-01
    slice, not this one).
    """
    backends = []

    def execution_factory(records, objects, approvals, notifier, _connectors,
                          _credentials, _secrets, turn_inputs):
        # the same injection line the composition's own factories run: the
        # host port rides host_ports -> context.ports -> TurnInputs.ports
        from ordessa_server_compat.composition import _injected_core_store
        from ordessa_server_compat.execution.sidecar_backend import (
            SidecarExecutionBackend,
        )

        def port_factory(context, on_event):
            raise RuntimeError("no native turn runs in this gate")

        backend = SidecarExecutionBackend(
            records, objects, approvals, port_factory=port_factory,
            on_event=notifier.notify, store=_injected_core_store(turn_inputs),
        )
        backends.append(backend)
        return backend

    runtime = build_runtime(
        tmp_path / "core-shared",
        server_plugins=create_composition().compatibility_plugins(
            execution_factory=execution_factory),
    )
    runtime.start()
    try:
        root = (tmp_path / "core-shared").resolve()
        core_path = Path(runtime.core_binding.store_path)
        assert core_path.resolve() == root / "state" / "core.sqlite"
        assert core_path.resolve() != runtime.database.path
        runtime.core_binding.snapshot()  # opens the round lazily
        assert core_path.is_file(), "the instance store did not land in the data root"
        row = core_db.get_conn().execute("PRAGMA database_list").fetchone()
        assert Path(row[2]).resolve() == runtime.database.path
        assert core_db.get_conn().execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='core_works'"
        ).fetchone() is not None
        # -- S1c target state: the chain's store is the host's instance store
        assert len(backends) == 1
        backend = backends[0]
        assert callable(backend.store)
        assert backend.store() is runtime.core_binding.store
        work = backend.work_service.create_work("S1c target-state filing")
        filed = runtime.core_binding.store.execute(
            "SELECT objective FROM core_works WHERE id = ?", (work.id,)).fetchone()
        assert filed is not None and filed[0] == "S1c target-state filing"
        # and the legacy global database did not receive the chain's filing
        legacy = core_db.get_conn().execute(
            "SELECT COUNT(*) FROM core_works WHERE id = ?", (work.id,)).fetchone()
        assert legacy[0] == 0
    finally:
        runtime.stop()


def _table_signatures(conn):
    """Structural fingerprint of every product table: columns and indexes.

    Work Order 121 (AUD-B-006): the old "upgrade" test only asserted
    `version == N` plus two index names - it did not look at a single column, so a
    migration that left a wrong type / NOT NULL / primary key would sail through.
    This fingerprint is what makes the gate actually bite: the migrated database
    must be structurally identical to a greenfield one, table for table.
    """
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
    signature = {}
    for table in tables:
        cols = tuple(
            (row["name"], row["type"], row["notnull"], row["dflt_value"], row["pk"])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall())
        indexes = tuple(sorted(
            (row["name"], row["sql"] or "") for row in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' "
                "AND tbl_name=? AND sql IS NOT NULL", (table,)).fetchall()))
        signature[table] = (cols, indexes)
    return signature


def test_migrations_chain_from_a_synthetic_pre_v2_seed_converges_and_preserves(tmp_path):
    # Work Order 121 (AUD-B-006) recharacterized HONESTLY. This used to be named
    # as if it proved a "real v1 upgrade". It does not: v1 was never published
    # (`git log --all -S"agentbox_product_schema" --diff-filter=A` -> only
    # 5a45303, which already shipped PRODUCT_SCHEMA_VERSION = 2), so the seed
    # below is a *synthetic* pre-2 shape used only to drive the forward chain.
    # It therefore asserts the chain RUNS, is IDEMPOTENT and PRESERVES rows -
    # NOT "greenfield equivalence" (a fictional seed cannot claim that, and an
    # earlier attempt to do so legitimately failed, which is the whole finding).
    # The real structural guard is `test_greenfield_schema_holds_load_bearing_invariants`.
    root = tmp_path / "migration"
    path = root / "state" / "agentbox.sqlite"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE agentbox_product_schema (
          singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL, applied_at TEXT NOT NULL
        );
        INSERT INTO agentbox_product_schema VALUES (1,1,'old');
        CREATE TABLE server_profiles (id TEXT PRIMARY KEY);
        CREATE TABLE server_sessions (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL);
        CREATE TABLE server_turns (
          id TEXT PRIMARY KEY, session_id TEXT NOT NULL, profile_revision INTEGER NOT NULL,
          native_generation INTEGER NOT NULL, state TEXT NOT NULL, capture_state TEXT NOT NULL,
          cleanup_state TEXT NOT NULL, input_object_digest TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        INSERT INTO server_profiles VALUES ('profile-old');
        INSERT INTO server_sessions VALUES ('session-old','profile-old');
        INSERT INTO server_turns VALUES (
          'turn-old','session-old',1,0,'completed','captured','cleaned','sha256:old','old','old'
        );
        """)
    database = Database(root)
    database.initialize()
    database.initialize()   # idempotent re-init must not drift or error
    with database.read() as conn:
        assert conn.execute(
            "SELECT version FROM agentbox_product_schema WHERE singleton=1"
        ).fetchone()[0] == product_db.PRODUCT_SCHEMA_VERSION
        row = conn.execute("SELECT * FROM server_turns WHERE id='turn-old'").fetchone()
        assert row["session_id"] == "session-old"          # forward-only, row preserved
        indexes = {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='server_turns'"
            ).fetchall()
        }
        assert "server_one_active_turn_per_session" in indexes
        assert "server_one_active_turn_per_profile" not in indexes  # Order 67 drop holds


def test_greenfield_schema_holds_load_bearing_invariants(tmp_path):
    # 121's REAL structural gate: the shipped schema itself is asserted at the
    # column level (type / NOT NULL), so a DDL change or a migration that lands
    # the wrong shape reddens this - which the old `version == N` check could not.
    # It includes 092's load-bearing nullable `harness_type`.
    root = tmp_path / "green"
    Database(root).initialize()
    with Database(root).read() as conn:
        columns = {row["name"]: row for row in
                   conn.execute("PRAGMA table_info(server_provider_models)").fetchall()}
        assert "harness_type" in columns
        assert columns["harness_type"]["notnull"] == 0   # 092: NULL == shared upstream
        turn_cols = {row["name"] for row in
                     conn.execute("PRAGMA table_info(server_turns)").fetchall()}
        assert {"terminal_reason", "error_code", "result_object_digest",
                "queue_item_id"} <= turn_cols             # the identity/outcome fields


def test_structural_comparator_is_not_blind_to_a_column_drift():
    # 121 G1 counter-example witness: prove the structural fingerprint above
    # actually distinguishes a column's type / NOT NULL / PK, i.e. the equivalence
    # test is not vacuously true. Two hand-built in-memory tables that differ only
    # by one column's nullability MUST have different signatures.
    def build(nullable: bool):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        nn = "" if nullable else " NOT NULL"
        conn.execute(f"CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT{nn})")
        return conn

    a = _table_signatures(build(True))
    b = _table_signatures(build(False))
    assert a != b, "the comparator missed a NOT NULL drift - the upgrade gate would too"
    # ...and identical shapes are stable (so equality means equality).
    assert a == _table_signatures(build(True))


def test_restart_seals_unfinished_turn_as_unknown_without_redispatch(tmp_path):
    root = tmp_path / "interrupted"
    first = build_runtime(root, server_plugins=create_composition().compatibility_plugins(
        harnesses=codex_registry(), connector=WslFixture()))
    first.start()
    try:
        workspace = first.plugin_host.provided_port('product.repository').create_workspace(
            key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
            remote_path="/workspace", connection_id="connection",
        )[1]
        config = first.objects.publish(b'{"schema_version":1,"harness_type":"codex","configuration":{}}')
        profile = first.plugin_host.provided_port('product.repository').create_profile(
            key="p", request_digest="p", name="role", harness_type="codex",
            config_digest=config.digest, credential_id=None,
        )[1]
        session = first.plugin_host.provided_port('product.repository').create_session(
            key="s", request_digest="s", workspace_id=workspace["workspace_id"],
            profile_id=profile["profile_id"],
        )[1]
        prompt = first.objects.publish(b'{"schema_version":1,"text":"pending"}')
        first.plugin_host.provided_port('product.repository').create_turn(
            session_id=session["session_id"], key="t", request_digest="t",
            input_object_digest=prompt.digest, expected_profile_revision=1,
            effective_config_object_digest=config.digest,
        )
    finally:
        first.stop()

    second = build_runtime(root, server_plugins=create_composition().compatibility_plugins(
        harnesses=codex_registry(), connector=WslFixture()))
    second.start()
    try:
        recovered = second.plugin_host.provided_port('product.repository').get_session(session["session_id"])
        assert recovered["status"] == "recovery_required"
        assert recovered["turns"][0]["state"] == "unknown"
        assert recovered["turns"][0]["error_code"] == "SERVER_RESTART_INTERRUPTED"
        assert recovered["events"][-1]["data"]["state"] == "unknown"
    finally:
        second.stop()
