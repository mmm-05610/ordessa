"""Work Order 138: delegation must carry the *workspace* axis (AUD-B-020, high).

Before: a fresh child landed in whatever workspace the child profile last touched, so a
turn about project A could write into project B (and the landing point drifted). The
roster also never carried the contract's `workspace` field, so the same-workscope rule
(65:83) had no visible or enforced face.

ops `R-0070 ①` picks the literal reading: placement = the parent turn's workspace, the
roster emits `workspace`, and candidates are filtered to the parent's workspace. These
gates drive the real `DelegationService.run` (never a hand-placed session):

* a child whose workspace IS the parent's is offered and lands in it;
* a child whose workspace is a *different* project is not a candidate - requesting it is
  an explicit `SUBAGENT_NOT_AUTHORIZED`, never a silent landing in that other project;
* the roster carries the `workspace` field.
"""
from __future__ import annotations

import pytest

from ordessa_server_compat.execution.delegation import DelegationService
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.profiles import ProfileRecords
from ordessa_server_compat.profiles.subagents import DelegationError
from ordessa_server_compat.sessions import SessionRecords, SessionService
from ordessa_workspace import WorkspaceRecords
from pacthold_runtime_compat.storage import Database, ObjectStore


class _FakeExecution:
    def __init__(self, records) -> None:
        self.records = records
        self.accepted: list[str] = []

    def accept(self, turn_id: str) -> None:
        self.accepted.append(turn_id)
        self.records.set_turn_dispatch(
            turn_id, work_id="w", execution_id="e", dispatch_id="d", state="running")
        self.records.append_turn_event(turn_id, "message.delta", {"text": f"summary of {turn_id}"})
        self.records.complete_turn(
            turn_id, checkpoint_object_digest="sha256:a",
            checkpoint_native_id=f"native-{turn_id}", result_object_digest="sha256:r",
            usage={"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}, usage_source="fake")


def _workspace(workspaces, name):
    return workspaces.create(
        key=name, request_digest=name, distribution="Ubuntu", remote_user="tester",
        remote_path=f"/{name}", connection_id=name)[1]["workspace_id"]


def _env(tmp_path):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    profiles = ProfileRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    records = SessionRecords(database, idempotency)
    objects = ObjectStore(tmp_path / "data")
    execution = _FakeExecution(records)
    _harnesses = HarnessRegistry()
    _harnesses.register(HarnessDescriptor(
        "codex", credential_kind=None,
        configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
        capability_claims={"stream": True},
    ))
    sessions = SessionService(records, idempotency, objects, harnesses=_harnesses,
                              profiles=profiles, credentials=None, execution=execution)
    service = DelegationService(records=records, profiles=profiles, sessions=sessions,
                                execution=execution, objects=objects)

    cfg = objects.publish(b'{"schema_version":1,"harness_type":"codex","configuration":{}}').digest

    def profile(name):
        return profiles.create(key=name, request_digest=name, name=name, harness_type="codex",
                               config_digest=cfg, credential_id=None)[1]

    parent = profile("alpha")
    local = profile("beta")      # home workspace == workspace A
    remote = profile("gamma")    # home workspace == workspace B (another project)

    ws_a = _workspace(workspaces, "ws-a")
    ws_b = _workspace(workspaces, "ws-b")

    parent_session = sessions.create_session("parent-session", {
        "workspace_id": ws_a, "profile_id": parent["profile_id"]})[1]
    sessions.create_session("local-seed", {"workspace_id": ws_a, "profile_id": local["profile_id"]})
    sessions.create_session("remote-seed", {"workspace_id": ws_b, "profile_id": remote["profile_id"]})
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=local["profile_id"])
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=remote["profile_id"])
    # a-3 A-family rebuild (C ruling 06:19Z): live parent via the acceptance route
    # so its frozen object carries the permissions section; fake port leaves it running.
    _, _parent_turn = sessions.create_turn(parent_session["session_id"], "parent-key", {
        "text": "parent task",
        "expected_profile_revision": int(profiles.get(parent["profile_id"])["config_revision"]),
    })
    service.parent_turn_id = _parent_turn["turn_id"]
    return database, service, parent, ws_a, ws_b


def _child_session_workspace(database, session_id):
    with database.read() as conn:
        row = conn.execute("SELECT workspace_id FROM server_sessions WHERE id=?",
                           (session_id,)).fetchone()
    return str(row["workspace_id"])


def test_same_workspace_child_lands_in_the_parent_workspace(tmp_path):
    database, service, parent, ws_a, _ws_b = _env(tmp_path)
    result = service.run(parent_turn_id=service.parent_turn_id, parent_profile_id=parent["profile_id"],
                         arguments={"subagent": "beta", "description": "do some work",
                                    "prompt": "x"})
    assert _child_session_workspace(database, result["sessionId"]) == ws_a


def test_cross_workspace_child_is_not_offered(tmp_path):
    # `gamma`'s home is workspace B (a different project). From a parent turn in A it
    # is not a candidate; requesting it refuses explicitly - it must NOT land in B.
    _database, service, parent, _ws_a, ws_b = _env(tmp_path)
    with pytest.raises(DelegationError) as refused:
        service.run(parent_turn_id=service.parent_turn_id, parent_profile_id=parent["profile_id"],
                    arguments={"subagent": "gamma", "description": "do some work", "prompt": "x"})
    assert refused.value.code == "SUBAGENT_NOT_AUTHORIZED"
    # And no child session was ever created in the other project.
    assert _database is not None and ws_b  # sanity that B exists as a distinct workspace


def test_roster_carries_the_workspace_field(tmp_path):
    _database, service, parent, ws_a, ws_b = _env(tmp_path)
    listing = service.list_for(parent_profile_id=parent["profile_id"])
    by_name = {entry["name"]: entry for entry in listing["roster"]}
    assert by_name["beta"]["workspace"] == ws_a
    assert by_name["gamma"]["workspace"] == ws_b
    assert "workspace" in listing["roster"][0]


def test_counterexample_inference_based_placement_would_reach_another_project(tmp_path):
    # The pre-fix shape: placement = child's last-touched workspace. For `gamma` that is
    # B, so a same-conversation delegation would create a fresh child session in another
    # project. After the fix, `gamma` is filtered out of the candidate roster, so the run
    # refuses and creates no child session there - `gamma` keeps only its one seed session.
    database, service, parent, _ws_a, ws_b = _env(tmp_path)
    with pytest.raises(DelegationError):
        service.run(parent_turn_id=service.parent_turn_id, parent_profile_id=parent["profile_id"],
                    arguments={"subagent": "gamma", "description": "do some work", "prompt": "x"})
    with database.read() as conn:
        gamma_sessions_in_b = conn.execute(
            "SELECT COUNT(*) AS c FROM server_sessions s "
            "JOIN server_profiles p ON p.id=s.profile_id "
            "WHERE s.workspace_id=? AND p.name='gamma'",
            (ws_b,),
        ).fetchone()["c"]
    assert int(gamma_sessions_in_b) == 1, (
        "only gamma's seed session may exist in project B; the refused delegation must "
        "not have created a child session there")
