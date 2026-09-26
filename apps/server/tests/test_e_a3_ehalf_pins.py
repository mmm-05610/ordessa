"""a-3 E half pins (K2-E consumption + K3'-E frozen-posture source).

Approved per-path in `approvals/a-3-release.md` (K2/K3'/K4) with the two
confluence interfaces published by C in `C-notice-E-047-051-ruled.md` §3:

* K2-E (读法甲) - the Core bookkeeping (work + execution) of an accepted Turn
  is created by the acceptance path *before* this consumer runs; the consumer
  reads that identity and the dispatch key from the turn row, never minting a
  second producer. A row without that identity is refused typed instead of
  silently re-creating.
* K3'-E - the parent's posture travels through the parent Turn's **frozen**
  effective configuration (top-level `permissions`, value shape
  `{preset, keys}`), never re-derived from the parent Profile's live row; a
  parent Turn without the section is refused typed.

Red sides (per V2 §5, `pristine` = the batch baseline `19dce83`):
* every pin here is RED on the pristine tree: `accept` still creates the
  work/execution itself (so `_CoreSpy.created` grows and the dispatch key is
  the locally built `turn-dispatch:<turn>`), and `_merged_posture` still reads
  both postures from live Profile rows (so the parent's later live edit leaks
  into the child and a parent turn without a frozen section is not refused).
* key-cell pins (race ruling §一.2①): the behavioral pin is RED on the merged
  form *without* E's key cell (`execution_key` NULL on the child row - clean
  assertion) and ERRORS on this single-leg tree with `no such column:
  execution_key` - **declared confluence red**: the column arrives with S's
  K1.1 schema v21, and the merge order lands S's six commits first. The
  spelling counter-lock needs no schema and flips red/green on the line alone.

Run (from `source/`):
    PYTHONPATH=src:$(ls -d plugins/*/src | paste -sd:) \
    ../tmp/venv/bin/python -m pytest tests/server/test_e_a3_ehalf_pins.py -q
"""
from __future__ import annotations

import inspect
import json

import pytest

from ordessa_server.errors import ServerError
from ordessa_server_compat.execution.delegation import DelegationService
from ordessa_server_compat.execution.sidecar_backend import SidecarExecutionBackend
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.profiles import ProfileRecords
from ordessa_server_compat.sessions import SessionRecords, SessionService
from ordessa_workspace import WorkspaceRecords
from pacthold.storage import Database, ObjectStore


class _StopAtPortFactory(RuntimeError):
    """Stop the acceptance strictly after the frozen inputs were read and the
    dispatch call was made, before any native side effect."""


# ---------------------------------------------------------------------------
# K2-E - the acceptance consumer reads the row identity, creates nothing.

class _CoreSpy:
    """Counts Core creations and records every dispatch call, delegating
    everything else untouched to the real service."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.created = 0
        self.dispatched: list[tuple[str, str]] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def create_work(self, *args, **kwargs):
        self.created += 1
        return self._inner.create_work(*args, **kwargs)

    def create_execution(self, *args, **kwargs):
        self.created += 1
        return self._inner.create_execution(*args, **kwargs)

    def dispatch_execution(self, execution_id, inputs, registry, idempotency_key):
        self.dispatched.append((execution_id, idempotency_key))
        return self._inner.dispatch_execution(execution_id, inputs, registry, idempotency_key)


class _FakeRecords:
    def __init__(self, contexts: dict[str, dict]) -> None:
        self.contexts = contexts
        self.dispatches: list[tuple[str, dict]] = []
        self.failures: list[tuple[str, str]] = []

    def get_turn_context(self, turn_id: str) -> dict:
        return self.contexts[turn_id]

    def set_turn_dispatch(self, turn_id: str, **kwargs) -> None:
        self.dispatches.append((turn_id, kwargs))

    def fail_turn(self, turn_id: str, code: str, queue_records=None) -> None:
        self.failures.append((turn_id, code))


def _k2_backend(tmp_path, *, row_identity: bool):
    """Backend whose rows optionally carry the identity the acceptance path
    would have written (execution_key + work_id + execution_id)."""
    store = ObjectStore(tmp_path / "objects")
    input_digest = store.publish(json.dumps({"message": {"text": "go"}}).encode()).digest
    frozen = store.publish(json.dumps(
        {"schema_version": 1, "harness_type": "qoder-sidecar",
         "configuration": {"model": "m"}}).encode()).digest
    context = {
        "session_id": "ses-a3", "profile_id": "prof-a3", "harness_type": "qoder-sidecar",
        "remote_path": "/work/a3", "profile_revision": 3,
        "input_object_digest": input_digest,
        "effective_config_object_digest": frozen,
    }
    records = _FakeRecords({"row-a3": dict(context)})
    backend = SidecarExecutionBackend(
        records, store, None,
        port_factory=lambda ctx, on_event: (_ for _ in ()).throw(
            _StopAtPortFactory("pin boundary")),
    )
    works = _CoreSpy(backend.work_service)
    executions = _CoreSpy(backend.execution_service)
    backend.work_service = works
    backend.execution_service = executions
    if row_identity:
        # the acceptance path's step, simulated verbatim: create the Core
        # bookkeeping once and put its identity + key on the row.
        work = backend.work_service.create_work(
            "AgentBox Session Turn", metadata={"session_id": "ses-a3", "turn_id": "row-a3"})
        execution = backend.execution_service.create_execution(
            work.id, backend.provider.provider_id,
            responsibility_intent="execute one accepted Session Turn through its Harness extension",
            provenance={"session_id": "ses-a3", "turn_id": "row-a3"})
        records.contexts["row-a3"]["execution_key"] = "turn-dispatch:row-a3"
        records.contexts["row-a3"]["work_id"] = work.id
        records.contexts["row-a3"]["execution_id"] = execution.id
        works.created = 0
        executions.created = 0
        executions.dispatched.clear()
    return backend, records, works, executions, store


def test_a3_k2_accept_consumes_the_row_identity_and_creates_nothing(tmp_path, tmp_agent_box_home):
    backend, records, works, executions, _store = _k2_backend(tmp_path, row_identity=True)
    row = records.contexts["row-a3"]

    with pytest.raises(Exception):   # the pin boundary, wrapped by Core dispatch
        backend.accept("row-a3")

    assert works.created == 0 and executions.created == 0, (
        "accept minted a second producer: the bookkeeping belongs to the "
        "acceptance path (K2 甲), the consumer must create nothing")
    assert executions.dispatched == [(row["execution_id"], row["execution_key"])], (
        "accept must dispatch the row's execution with the row's key, "
        f"got {executions.dispatched}")


def test_a3_k2_accept_refuses_a_row_without_identity(tmp_path, tmp_agent_box_home):
    backend, records, works, executions, _store = _k2_backend(tmp_path, row_identity=False)

    with pytest.raises(ServerError) as refused:
        backend.accept("row-a3")

    assert refused.value.code == "IDEMPOTENCY_CONFLICT"
    assert refused.value.status == 409
    assert works.created == 0 and executions.created == 0
    assert executions.dispatched == [], "a refused accept must not dispatch anything"
    assert records.dispatches == [], "a refused accept must not write a dispatch back"


# ---------------------------------------------------------------------------
# K3'-E - the parent posture comes from the parent Turn's frozen section.

_K3_FROZEN_WITH_PERMISSIONS = {
    "schema_version": 1, "harness_type": "codex", "configuration": {"model": "m"},
    "permissions": {"preset": "default", "keys": {"bash": "deny"}},
}
_K3_FROZEN_WITHOUT_PERMISSIONS = {
    "schema_version": 1, "harness_type": "codex", "configuration": {"model": "m"},
}


def _k3_pieces(tmp_path, *, parent_frozen: dict):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    profiles = ProfileRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    records = SessionRecords(database, idempotency)
    objects = ObjectStore(tmp_path / "data")
    sessions = SessionService(records, idempotency, objects, harnesses=None,
                             profiles=profiles, credentials=None, execution=None)
    service = DelegationService(records=records, profiles=profiles, sessions=sessions,
                               execution=None, objects=objects)

    def config_for(model: str) -> str:
        return objects.publish(json.dumps(
            {"schema_version": 1, "harness_type": "codex",
             "configuration": {"model": model}}).encode()).digest

    shared = config_for("m")
    parent = profiles.create(key="p", request_digest="p", name="alpha", harness_type="codex",
                            config_digest=shared, credential_id=None)[1]
    child = profiles.create(key="c", request_digest="c", name="beta", harness_type="codex",
                            config_digest=shared, credential_id=None)[1]
    workspace = workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/workspace", connection_id="c")[1]
    # the child's own row is its acceptance face: give it one grant and no deny.
    _write_permissions(database, child["profile_id"], "default",
                       [{"key": "bash", "action": "allow"}, {"key": "webfetch", "action": "allow"}])
    session_row = sessions.create_session("parent-seed", {
        "workspace_id": workspace["workspace_id"],
        "profile_id": parent["profile_id"]})[1]
    frozen_digest = objects.publish(json.dumps(parent_frozen).encode()).digest
    message_digest = objects.publish(
        json.dumps({"schema_version": 1, "message": {"text": "parent"}}).encode()).digest
    _claimed, _status, body = records.create_turn(
        session_id=session_row["session_id"], key="a3-parent-turn",
        request_digest="rd-a3-parent", input_object_digest=message_digest,
        expected_profile_revision=int(parent["config_revision"]),
        effective_config_object_digest=frozen_digest)
    parent_turn_id = body["turn_id"]
    return (database, profiles, records, objects, service, child, parent,
            parent_turn_id)


def _write_permissions(database, profile_id: str, preset: str, rules: list) -> None:
    with database.transaction() as conn:
        conn.execute(
            "UPDATE server_profiles SET permission_preset=?, permission_rules_json=?, "
            "config_revision=config_revision+1 WHERE id=?",
            (preset, json.dumps(rules), profile_id))


def _merged_posture(service, *, parent_turn_id, parent_profile_id, child_profile):
    """Call the pin's unit, preferring the a-3 signature and falling back to the
    pristine one so the same scenario runs on both trees (red side needs to
    reach the old live-row derivation, not fail on the signature)."""
    try:
        return service._merged_posture(
            parent_turn_id=parent_turn_id, parent_profile_id=parent_profile_id,
            child_profile=child_profile)
    except TypeError:
        return service._merged_posture(
            parent_profile_id=parent_profile_id, child_profile=child_profile)


def test_a3_k3_frozen_parent_posture_is_the_source_not_the_live_row(tmp_path):
    (database, profiles, _records, _objects, service, child, parent,
     parent_turn_id) = _k3_pieces(tmp_path, parent_frozen=_K3_FROZEN_WITH_PERMISSIONS)

    # a committed live-row edit on the PARENT after the turn was accepted: the
    # parent profile now denies nothing at all.
    _write_permissions(database, parent["profile_id"], "default", [])

    merged = _merged_posture(
        service, parent_turn_id=parent_turn_id,
        parent_profile_id=parent["profile_id"], child_profile=profiles.get(child["profile_id"]))

    assert merged["keys"]["bash"] == "deny", (
        "the parent's later live edit leaked into the child: the posture must "
        "travel through the parent Turn's frozen section")
    assert merged["keys"]["webfetch"] == "allow"      # the child's own grant stands
    assert merged["inheritedFrom"] == parent["profile_id"]


def test_a3_k3_no_parent_live_row_derivation_remains(tmp_path):
    source = inspect.getsource(DelegationService._merged_posture)
    assert "_frozen_posture" in source, "the frozen parent source is not wired"
    assert "posture_of(parent)" not in source, (
        "the parent posture is still derived from a live row")
    assert "profiles.get(parent_profile_id)" not in source, (
        "the parent Profile's live row is still read for posture")


def test_a3_k3_parent_turn_without_permissions_section_is_refused_typed(tmp_path):
    (_database, profiles, _records, _objects, service, child, parent,
     parent_turn_id) = _k3_pieces(tmp_path, parent_frozen=_K3_FROZEN_WITHOUT_PERMISSIONS)

    with pytest.raises(ServerError) as refused:
        _merged_posture(
            service, parent_turn_id=parent_turn_id,
            parent_profile_id=parent["profile_id"],
            child_profile=profiles.get(child["profile_id"]))

    assert refused.value.code == "PROFILE_CONFIGURATION_INVALID"
    assert refused.value.status == 409


def test_a3_k2_row_identity_is_the_only_dispatch_key_source():
    """K2 甲 counter-lock: the acceptance consumer must not mint the dispatch
    key locally again (the retired `turn-dispatch:{turn_id}` literal)."""
    source = inspect.getsource(SidecarExecutionBackend.accept)
    assert 'f"turn-dispatch:{turn_id}"' not in source
    assert "execution_key" in source
    assert 'context.get("work_id")' in source


# ---------------------------------------------------------------------------
# key cell (race ruling §一.2①, E sole writer) - the child row mints its key.

def _key_pieces(tmp_path):
    """Minimal delegation pieces: a child Profile and a session bound to it,
    no parent Turn row (parent_turn_id stays an opaque handle here, as the
    INC1c N1 pins already exercise) and no execution port (creation never
    touches one)."""
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    profiles = ProfileRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    records = SessionRecords(database, idempotency)
    objects = ObjectStore(tmp_path / "data")
    sessions = SessionService(records, idempotency, objects, harnesses=None,
                             profiles=profiles, credentials=None, execution=None)
    service = DelegationService(records=records, profiles=profiles, sessions=sessions,
                               execution=None, objects=objects)
    config_digest = objects.publish(json.dumps(
        {"schema_version": 1, "harness_type": "codex",
         "configuration": {"model": "m"}}).encode()).digest
    child = profiles.create(key="c", request_digest="c", name="beta",
                            harness_type="codex", config_digest=config_digest,
                            credential_id=None)[1]
    workspace = workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/workspace", connection_id="c")[1]
    session_row = sessions.create_session("seed-key-cell", {
        "workspace_id": workspace["workspace_id"],
        "profile_id": child["profile_id"]})[1]
    return database, records, profiles, service, child, session_row


def test_a3_key_cell_child_row_carries_the_derived_execution_key(tmp_path):
    """The delegation child INSERT mints `execution:{turn_id}` at creation,
    read through `get_turn_context` - the exact read point K2-E accept
    consumes - so the child acceptance leg finds the identity instead of
    refusing an identity-less row."""
    (_database, records, profiles, service, child, session_row) = _key_pieces(tmp_path)
    fresh = profiles.get(child["profile_id"])
    turn_id = service._create_child_turn(
        session_id=session_row["session_id"], child_profile=fresh,
        parent_turn_id="parent-turn", prompt="go", model=None, posture=None)

    context = records.get_turn_context(turn_id)
    assert context.get("execution_key") == f"execution:{turn_id}", (
        "the child row must carry its K1.1-family derived key "
        f"`execution:{turn_id}` at creation, got "
        f"{context.get('execution_key')!r}: the consumer reads it, never mints it")


def test_a3_key_cell_derivation_spelling_matches_the_session_family():
    """Schema-free counter-lock: the derivation must stay the exact K1.1
    family spelling (flips red on the line alone, both sim directions)."""
    source = inspect.getsource(DelegationService._create_child_turn)
    assert 'f"execution:{turn_id}"' in source, (
        "the child key must be derived as `execution:{turn_id}`, the same "
        "spelling the Session write points mint")
    assert "turn-dispatch:" not in source, (
        "the retired dispatch-literal family must not re-enter the child INSERT")
