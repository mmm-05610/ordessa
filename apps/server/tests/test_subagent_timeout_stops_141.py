"""Work Order 141: a subagent time-out must STOP the child, not just stop waiting.

`_await_terminal` used to hit the deadline and `raise DelegationError('SUBAGENT_TIMEOUT')`
with no cancel action, so the child kept running (and spending) past the "resource
boundary" of `65:81`, and the refusal carried no `turnId`/handle to locate it (`65:90`
"no silent degrade"). Time-out was not a stop entry point - unlike the two parent-cancel
cascades that DO stop children. ops takes the literal reading: stop-then-report.

These gates drive the real `DelegationService.run` against a child that never finishes:
* the timeout cancels the child - it is not left active in the ledger;
* the refusal is still the typed `SUBAGENT_TIMEOUT` (no generic collapse);
* the refusal body names a locatable handle and the usage actually incurred;
* the success path (a child that finishes in time) is unchanged.
"""
from __future__ import annotations

import pytest

from ordessa_server.execution import (CancelOutcome, HarnessDescriptor,
                                   HarnessRegistry)
from ordessa_server.execution.delegation import DelegationService
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.profiles import ProfileRecords
from ordessa_server.profiles.subagents import DelegationError
from ordessa_server_compat.sessions import SessionRecords, SessionService
from ordessa_server.workspaces import WorkspaceRecords
from pacthold.storage import Database, ObjectStore

ACTIVE_STATES = {"accepted", "running", "capturing"}


class _NeverFinishing:
    """A child that stays running until cancelled; cancel reaches the terminal state.

    Mirrors `test_subagent_rule_liveness_086._NeverFinishes`: the process is gone on
    cancel, so the turn leaves the active set.
    """

    def __init__(self, records) -> None:
        self.records = records
        self.accepted: list[str] = []
        self.cancelled: list[str] = []

    def accept(self, turn_id: str) -> None:
        self.accepted.append(turn_id)
        self.records.set_turn_dispatch(
            turn_id, work_id="w", execution_id="e", dispatch_id="d", state="running")

    def cancel(self, turn_id: str) -> bool:
        self.cancelled.append(turn_id)
        self.records.finish_cancelled(turn_id)
        return True

    def cancel_execution(self, turn_id: str):
        return (CancelOutcome.CONFIRMED_STOPPED if self.cancel(turn_id)
                else CancelOutcome.REFUSED_NO_ACTIVE_RUN)


class _Completing:
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

    def cancel(self, turn_id: str) -> bool:  # pragma: no cover - not used by success path
        self.records.finish_cancelled(turn_id)
        return True

    def cancel_execution(self, turn_id: str):  # pragma: no cover - not used by success path
        return (CancelOutcome.CONFIRMED_STOPPED if self.cancel(turn_id)
                else CancelOutcome.REFUSED_NO_ACTIVE_RUN)


def _env(tmp_path, *, execution_cls=_NeverFinishing):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    profiles = ProfileRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    records = SessionRecords(database, idempotency)
    objects = ObjectStore(tmp_path / "data")
    execution = execution_cls(records)
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
    child = profile("beta")
    workspace = workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/w", connection_id="w")[1]
    parent_session = sessions.create_session("parent-session", {
        "workspace_id": workspace["workspace_id"], "profile_id": parent["profile_id"]})[1]
    sessions.create_session("child-seed", {
        "workspace_id": workspace["workspace_id"], "profile_id": child["profile_id"]})
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])
    # a-3 A-family rebuild (C ruling 06:19Z): the live parent arrives via the
    # acceptance route so its frozen object carries the permissions section;
    # the shared fake port leaves it running (dispatch only), matching every
    # observation in this file.
    _, _parent_turn = sessions.create_turn(parent_session["session_id"], "parent-key", {
        "text": "parent task",
        "expected_profile_revision": int(profiles.get(parent["profile_id"])["config_revision"]),
    })
    service.parent_turn_id = _parent_turn["turn_id"]
    return database, records, sessions, service, parent, child


def _turn_state(database, turn_id):
    with database.read() as conn:
        row = conn.execute("SELECT state FROM server_turns WHERE id=?", (turn_id,)).fetchone()
    return str(row["state"]) if row is not None else None


def test_timeout_cancels_the_child_and_keeps_the_typed_code(tmp_path):
    database, records, _sessions, service, parent, _child = _env(tmp_path)
    with pytest.raises(DelegationError) as timed_out:
        service.run(parent_turn_id=service.parent_turn_id, parent_profile_id=parent["profile_id"],
                    arguments={"subagent": "beta", "description": "do some work",
                               "prompt": "x", "timeout": 1})
    # G2: still the typed code, not a generic collapse.
    assert timed_out.value.code == "SUBAGENT_TIMEOUT"
    # The refusal names a locatable handle + the usage section (G3).
    message = timed_out.value.message
    assert "turnId=" in message and "usage so far" in message


def test_timeout_leaves_the_child_not_active_on_the_ledger(tmp_path):
    database, _records, _sessions, service, parent, _child = _env(tmp_path)
    with pytest.raises(DelegationError):
        service.run(parent_turn_id=service.parent_turn_id, parent_profile_id=parent["profile_id"],
                    arguments={"subagent": "beta", "description": "do some work",
                               "prompt": "x", "timeout": 1})
    # The timed-out child turn (the only child turn for parent-turn) must have left the
    # active set - the resource boundary actually stopped it (G1).
    with database.read() as conn:
        kids = [str(r["id"]) for r in conn.execute(
            "SELECT id FROM server_turns WHERE parent_turn_id=?",
            (service.parent_turn_id,)).fetchall()]
    assert kids, "a child turn was created before the wait"
    assert all(_turn_state(database, kid) not in ACTIVE_STATES for kid in kids), kids


def test_success_path_is_unchanged(tmp_path):
    # A child that finishes inside the deadline returns the normal body, unchanged.
    database, _records, _sessions, service, parent, _child = _env(tmp_path, execution_cls=_Completing)
    result = service.run(parent_turn_id=service.parent_turn_id, parent_profile_id=parent["profile_id"],
                         arguments={"subagent": "beta", "description": "do some work",
                                    "prompt": "x", "timeout": 5})
    assert result["state"] == "completed"
    assert result["summary"].startswith("summary of turn_")
    assert result["task_id"].startswith("native-turn_")
