"""Work Order 39 regression gates for the neutral Server boundary.

Covers: one idempotency key accepts and dispatches exactly once, two
non-branded test providers are selectable without Server changes, capability
answers derive from registration only, and the legacy native path is absent
from production assembly.
"""
from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition
from ordessa_server.credentials import CredentialRecords
from ordessa_server_compat.execution import (
    CancelOutcome, HarnessDescriptor, HarnessRegistry,
)
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.persistence import ProductRepositoryView
from ordessa_server_compat.profiles import ProfileRecords
from ordessa_server_compat.sessions import SessionRecords, SessionService
from ordessa_server.transport.http import create_app
from pacthold_runtime_compat.storage import Database, ObjectStore
from ordessa_workspace import WorkspaceRecords


class RecordingExecution:
    """Provider-neutral execution port that records dispatch claims."""

    def __init__(self, *, hold: bool = False) -> None:
        self.lock = threading.Lock()
        self.accepted: list[str] = []
        self.cancelled: list[str] = []
        self.hold = hold
        self.gate = threading.Event()

    def accept(self, turn_id):
        with self.lock:
            self.accepted.append(turn_id)
        if self.hold:
            self.gate.wait(5)

    def cancel(self, turn_id):
        with self.lock:
            self.cancelled.append(turn_id)
        return True

    def cancel_execution(self, turn_id):
        return (CancelOutcome.CONFIRMED_STOPPED if self.cancel(turn_id)
                else CancelOutcome.REFUSED_NO_ACTIVE_RUN)


class WslFixture:
    def distributions(self):
        return [{"name": "Ubuntu"}]

    def probe(self, distribution, user):
        return {"probe_id": "probe_fixture", "distribution": distribution, "user": user}

    def browse(self, probe_id, path):
        return {"probe_id": probe_id, "path": path, "directories": []}

    def open_workspace(self, probe_id, path):
        return {"connection_id": "conn_fixture", "distribution": "Ubuntu",
                "user": "tester", "path": path}


def alpha_beta_registry():
    """Two non-branded provider descriptors with distinct honest claims."""
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        "alpha", credential_kind="alpha-key",
        configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
        capability_claims={"stream": True},
    ))
    registry.register(HarnessDescriptor(
        "beta", credential_kind=None,
        configuration_validator=lambda value: None if "required" in value else ValueError(),
        capability_claims={},
    ))
    return registry


def build_pieces(tmp_path, execution, *, home_concurrency=None):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    credentials = CredentialRecords(database)
    profiles = ProfileRecords(database, idempotency)
    sessions_records = SessionRecords(database, idempotency,
                                      home_concurrency=home_concurrency)
    workspaces = WorkspaceRecords(database, idempotency)
    sessions = SessionService(
        sessions_records, idempotency, ObjectStore(tmp_path / "data"),
        harnesses=alpha_beta_registry(), profiles=profiles, credentials=credentials,
        execution=execution,
    )
    repository = ProductRepositoryView(
        database=database, idempotency=idempotency, credentials=credentials,
        workspaces=workspaces, profiles=profiles, sessions=sessions_records,
    )
    return database, idempotency, sessions, repository


def test_concurrent_same_key_turn_acceptance_dispatches_once(tmp_path):
    execution = RecordingExecution(hold=True)
    database, idempotency, sessions, repository = build_pieces(tmp_path, execution)
    credentials = repository.credentials
    profiles = repository.profiles
    objects = ObjectStore(tmp_path / "data")
    credentials.register("credential-1", "alpha-key", "locator")
    config = objects.publish(b'{"schema_version":1,"harness_type":"alpha","configuration":{}}')
    profile = profiles.create(
        key="p", request_digest="p", name="role", harness_type="alpha",
        config_digest=config.digest, credential_id="credential-1",
    )[1]
    workspace = repository.workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/workspace", connection_id="connection",
    )[1]
    session = sessions.create_session("s", {
        "workspace_id": workspace["workspace_id"], "profile_id": profile["profile_id"],
    })[1]

    body = {"text": "one intent", "expected_profile_revision": 1}
    receipts: list = []
    errors: list = []

    # Deterministic counter-example window: both racers finish the
    # pre-commit idempotency read (both None) before either commits.
    barrier = threading.Barrier(2, timeout=5)
    original = idempotency.get

    def raced_pre_read(scope, key, request_digest):
        result = original(scope, key, request_digest)
        barrier.wait()
        return result

    idempotency.get = raced_pre_read

    def race():
        try:
            receipts.append(sessions.create_turn(session["session_id"], "turn-key", body))
        except BaseException as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=race) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    execution.gate.set()
    idempotency.get = original  # stop forcing the race window for later calls

    assert errors == []
    turn_ids = {receipt[1]["turn_id"] for receipt in receipts}
    assert len(turn_ids) == 1, receipts
    assert receipts[0] == receipts[1], "replay must return the same identity"
    assert len(execution.accepted) == 1, execution.accepted

    # A sequential replay after the fact also never re-dispatches.
    replay = sessions.create_turn(session["session_id"], "turn-key", body)
    assert replay == receipts[0]
    assert len(execution.accepted) == 1


def test_two_neutral_providers_are_selectable_without_server_changes(tmp_path):
    execution = RecordingExecution()
    runtime = build_runtime(
        tmp_path / "providers",
        server_plugins=create_composition().compatibility_plugins(
            harnesses=alpha_beta_registry(),
            connector=WslFixture(), execution=execution),
    )
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": f"Bearer {runtime.token}"}

        def post(path, body, key):
            return client.post(path, headers={**headers, "Idempotency-Key": key}, json=body)

        workspace = post("/api/v1/workspaces", {
            "probe_id": "probe_fixture", "path": "/workspace",
        }, "workspace").json()
        runtime.plugin_host.provided_port('product.repository').register_credential("credential-1", "alpha-key", "locator")
        alpha_profile = post("/api/v1/profiles", {
            "name": "alpha role", "harness_type": "alpha",
            "configuration": {}, "credential_id": "credential-1",
        }, "alpha-profile").json()
        beta_profile = post("/api/v1/profiles", {
            "name": "beta role", "harness_type": "beta",
            "configuration": {"required": True}, "credential_id": None,
        }, "beta-profile").json()
        assert alpha_profile["capabilities"] == {"stream": True}
        assert beta_profile["capabilities"] == {}

        for name, profile in (("alpha", alpha_profile), ("beta", beta_profile)):
            session = post("/api/v1/sessions", {
                "workspace_id": workspace["workspace_id"],
                "profile_id": profile["profile_id"],
            }, f"session-{name}").json()
            turn = post(f"/api/v1/sessions/{session['session_id']}/turns", {
                "text": f"hello from {name}", "expected_profile_revision": 1,
            }, f"turn-{name}")
            assert turn.status_code == 202, turn.json()
        assert len(execution.accepted) == 2

        # The same Server rejected an unregistered provider without a brand branch.
        rejected = post("/api/v1/profiles", {
            "name": "unknown role", "harness_type": "gamma",
            "configuration": {}, "credential_id": None,
        }, "gamma-profile")
        assert rejected.status_code == 503
        assert rejected.json()["error"]["code"] == "HARNESS_UNAVAILABLE"

        listed = client.get("/api/v1/profiles", headers=headers).json()["items"]
        claims = {item["harness_type"]: item["capabilities"] for item in listed}
        assert claims == {"alpha": {"stream": True}, "beta": {}}


def test_capability_answers_reflect_registration_only(tmp_path):
    runtime = build_runtime(tmp_path / "honest")
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": f"Bearer {runtime.token}"}
        readiness = client.get("/api/v1/readiness", headers=headers).json()
        assert readiness["capabilities"]["harnesses"] == {}
        assert readiness["capabilities"]["execution"] is False
        turn = client.post(
            "/api/v1/sessions/session-missing/turns",
            headers={**headers, "Idempotency-Key": "x"},
            json={"text": "t", "expected_profile_revision": 1},
        )
        assert turn.status_code == 503
        assert turn.json()["error"]["code"] == "EXECUTION_CAPABILITY_UNAVAILABLE"

    registered = build_runtime(
        tmp_path / "registered",
        server_plugins=create_composition().compatibility_plugins(
            harnesses=alpha_beta_registry(),
            connector=WslFixture()),
    )
    with TestClient(create_app(registered), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": f"Bearer {registered.token}"}
        readiness = client.get("/api/v1/readiness", headers=headers).json()
        harnesses = readiness["capabilities"]["harnesses"]
        assert set(harnesses) == {"alpha", "beta"}
        assert harnesses["alpha"]["capability_claims"] == {"stream": True}
        assert harnesses["alpha"]["available"] is False
        assert harnesses["alpha"]["unavailable_reason"] == "EXECUTION_CAPABILITY_UNAVAILABLE"
        assert harnesses["beta"]["capability_claims"] == {}

        # Nothing is invented for an unregistered harness type or absent execution.
        assert client.get("/api/v1/profiles", headers=headers).json() == {"items": []}


def test_same_profile_two_sessions_admitted_and_settled_in_order(tmp_path):
    """Order 67: the uniqueness unit is the Session, not the Profile.

    Two different Sessions of one Profile each get a Turn (the dropped
    per-profile index no longer refuses the second); a second Turn for the
    *same* Session is still refused with the unchanged wire code; the
    Profile's run_state stays active until the last of its Turns finishes,
    and its generation advances once per completed Turn.
    """
    import pytest

    from ordessa_server.errors import ServerError

    execution = RecordingExecution()
    database, idempotency, sessions, repository = build_pieces(tmp_path, execution)
    credentials, profiles, records = (
        repository.credentials, repository.profiles, repository.sessions,
    )
    objects = ObjectStore(tmp_path / "data")
    credentials.register("credential-1", "alpha-key", "locator")
    config = objects.publish(b'{"schema_version":1,"harness_type":"alpha","configuration":{}}')
    profile = profiles.create(
        key="p", request_digest="p", name="role", harness_type="alpha",
        config_digest=config.digest, credential_id="credential-1",
    )[1]
    workspace = repository.workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/workspace", connection_id="connection",
    )[1]
    first = sessions.create_session("s1", {
        "workspace_id": workspace["workspace_id"], "profile_id": profile["profile_id"],
    })[1]
    second = sessions.create_session("s2", {
        "workspace_id": workspace["workspace_id"], "profile_id": profile["profile_id"],
    })[1]

    body = {"text": "one intent", "expected_profile_revision": 1}
    _, turn_a = sessions.create_turn(first["session_id"], "key-a", body)
    _, turn_b = sessions.create_turn(second["session_id"], "key-b", body)
    assert turn_a["turn_id"] != turn_b["turn_id"]
    assert set(execution.accepted) == {turn_a["turn_id"], turn_b["turn_id"]}

    # The same Session's second Turn is refused - and the code is unchanged.
    with pytest.raises(ServerError) as refusal:
        sessions.create_turn(first["session_id"], "key-a2", body)
    assert refusal.value.code == "TURN_CONCURRENCY_CONFLICT"
    assert "Session" in refusal.value.message and "Profile" not in refusal.value.message

    # Cross-profile protection: while the Session has an active Turn, another
    # role cannot take it over - the switch is rejected with the running
    # reason, so no second writer can enter the same native session.
    other_profile = profiles.create(
        key="p2", request_digest="p2", name="other", harness_type="alpha",
        config_digest=config.digest, credential_id="credential-1",
    )[1]
    with database.read() as conn:
        session_version = conn.execute(
            "SELECT version FROM server_sessions WHERE id=?", (first["session_id"],),
        ).fetchone()[0]
    outcome, switch_body = records.switch_profile(
        session_id=first["session_id"], profile_id=other_profile["profile_id"],
        expected_version=session_version, request_id="switch-key", request_digest="switch",
    )
    assert outcome == "rejected"
    assert switch_body["reason"] == "execution_running"

    records.set_turn_dispatch(
        turn_a["turn_id"], work_id="w-a", execution_id="e-a", dispatch_id="d-a")
    records.set_turn_dispatch(
        turn_b["turn_id"], work_id="w-b", execution_id="e-b", dispatch_id="d-b")
    records.complete_turn(
        turn_a["turn_id"], checkpoint_object_digest="sha256:a",
        checkpoint_native_id="native-a", result_object_digest="sha256:ra")
    with database.read() as conn:
        row = conn.execute(
            "SELECT run_state FROM server_profiles WHERE id=?", (profile["profile_id"],),
        ).fetchone()
    assert row["run_state"] == "active", "a sibling Turn is still in flight"

    records.complete_turn(
        turn_b["turn_id"], checkpoint_object_digest="sha256:b",
        checkpoint_native_id="native-b", result_object_digest="sha256:rb")
    with database.read() as conn:
        row = conn.execute(
            "SELECT run_state,native_generation FROM server_profiles WHERE id=?",
            (profile["profile_id"],),
        ).fetchone()
    assert row["run_state"] == "idle", "the last active Turn settles the Profile"
    assert row["native_generation"] == 2, "one advance per completed Turn"


def test_exclusive_home_families_keep_one_active_turn_per_profile(tmp_path):
    """Order 67's narrowed lock, per family declaration.

    A family whose home cannot be certified for concurrent writers declares
    `homeConcurrency = "exclusive"`: for it alone, a second Session of one
    Profile is refused - and the refusal names the asset (the Harness home),
    distinct from the Session-scoped admission.
    """
    import pytest

    from ordessa_server.errors import ServerError

    execution = RecordingExecution()
    database, idempotency, sessions, repository = build_pieces(
        tmp_path, execution, home_concurrency={"beta": "exclusive"},
    )
    credentials, profiles = repository.credentials, repository.profiles
    objects = ObjectStore(tmp_path / "data")
    config = objects.publish(b'{"schema_version":1,"harness_type":"beta","configuration":{"required":true}}')
    profile = profiles.create(
        key="p", request_digest="p", name="exclusive role", harness_type="beta",
        config_digest=config.digest, credential_id=None,
    )[1]
    workspace = repository.workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/workspace", connection_id="connection",
    )[1]
    first = sessions.create_session("s1", {
        "workspace_id": workspace["workspace_id"], "profile_id": profile["profile_id"],
    })[1]
    second = sessions.create_session("s2", {
        "workspace_id": workspace["workspace_id"], "profile_id": profile["profile_id"],
    })[1]

    body = {"text": "one intent", "expected_profile_revision": 1}
    _, first_turn = sessions.create_turn(first["session_id"], "key-a", body)
    with pytest.raises(ServerError) as refusal:
        sessions.create_turn(second["session_id"], "key-b", body)
    assert refusal.value.code == "TURN_CONCURRENCY_CONFLICT"
    assert "home" in refusal.value.message, refusal.value.message

    # Once the first Turn is terminal, the sibling Session proceeds.
    records = repository.sessions
    records.set_turn_dispatch(
        first_turn["turn_id"], work_id="w-a", execution_id="e-a", dispatch_id="d-a")
    records.complete_turn(
        first_turn["turn_id"], checkpoint_object_digest="sha256:a",
        checkpoint_native_id="native-a", result_object_digest="sha256:ra")
    _, second_turn = sessions.create_turn(second["session_id"], "key-c", body)
    assert second_turn["turn_id"] != first_turn["turn_id"]


def test_two_profiles_with_one_name_get_two_homes():
    """The locator carries the Profile's identity, so a shared display name
    cannot collide two homes (the HOME_MARKER_CONFLICT class the family gates
    kept hitting across runs on a persistent home root)."""
    from ordessa_server_compat.composition import _profile_home_locator

    first = _profile_home_locator("role", ".config/kilo",
                                  profile_id="profile_0123456789abcdef")
    second = _profile_home_locator("role", ".config/kilo",
                                   profile_id="profile_fedcba9876543210")
    assert first != second
    assert first.endswith("/.config/kilo") and second.endswith("/.config/kilo")
    # A rename does not change anything for a recorded locator; a missing id
    # still yields a usable (if generic) locator.
    assert _profile_home_locator("role", ".pi", profile_id="profile_0123456789abcdef") == first.replace(".config/kilo", ".pi")
    assert _profile_home_locator("role", ".pi") == "role/.pi"
