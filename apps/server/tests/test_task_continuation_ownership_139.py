"""Work Order 139: `task_id` continuation must check session OWNERSHIP, not just family.

The continuation branch used to `SELECT ... WHERE checkpoint_native_id=?` globally and
reject only a cross-harness-family session. That let a parent authorized for child C
resume child D's native handle (same family, different profile - in another workspace),
and `fetchone()` made a handle shared by several sessions resolve to whichever row came
first. ops takes the zero-contract option: reuse `SUBAGENT_NOT_AUTHORIZED`, no new code,
no schema index (this order adds only code-level determinism).

These gates drive the real `DelegationService.run` continuation path:
* resuming an unauthorized same-family profile's handle -> `SUBAGENT_NOT_AUTHORIZED`;
* a handle shared by two sessions -> deterministic `SUBAGENT_NOT_AUTHORIZED` (not a row);
* the existing cross-family rejection still gives `SUBAGENT_TASK_FAMILY_MISMATCH`;
* resuming the authorized child's OWN handle still succeeds (positive unchanged).
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


class _Completing:
    def __init__(self, records) -> None:
        self.records = records

    def accept(self, turn_id) -> None:
        self.records.set_turn_dispatch(turn_id, work_id="w", execution_id="e", dispatch_id="d", state="running")
        self.records.append_turn_event(turn_id, "message.delta", {"text": f"summary of {turn_id}"})
        self.records.complete_turn(
            turn_id, checkpoint_object_digest="sha256:a",
            checkpoint_native_id=f"native-{turn_id}", result_object_digest="sha256:r",
            usage={"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}, usage_source="fake")

    def cancel(self, turn_id):
        self.records.finish_cancelled(turn_id)
        return True

    def cancel_execution(self, turn_id):
        return (CancelOutcome.CONFIRMED_STOPPED if self.cancel(turn_id)
                else CancelOutcome.REFUSED_NO_ACTIVE_RUN)


def _env(tmp_path):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    profiles = ProfileRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    records = SessionRecords(database, idempotency)
    objects = ObjectStore(tmp_path / "data")
    execution = _Completing(records)
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

    def cfg(harness):
        return objects.publish(
            f'{{"schema_version":1,"harness_type":"{harness}","configuration":{{}}}}'.encode()).digest

    def profile(name, harness="codex"):
        return profiles.create(key=name, request_digest=name, name=name, harness_type=harness,
                               config_digest=cfg(harness), credential_id=None)[1]

    parent = profile("alpha")
    authorized = profile("beta")            # C - granted, same family as D
    unauthorized = profile("delta")         # D - NOT granted, same family (codex)
    foreign = profile("claude", harness="claude-code")   # other family
    ws_parent = workspaces.create(key="wp", request_digest="wp", distribution="Ubuntu",
                                  remote_user="t", remote_path="/wp", connection_id="wp")[1]["workspace_id"]
    ws_other = workspaces.create(key="wo", request_digest="wo", distribution="Ubuntu",
                                 remote_user="t", remote_path="/wo", connection_id="wo")[1]["workspace_id"]
    parent_session = sessions.create_session("ps", {
        "workspace_id": ws_parent, "profile_id": parent["profile_id"]})[1]
    # C is reachable (granted, home == parent workspace).
    sessions.create_session("c-seed", {"workspace_id": ws_parent, "profile_id": authorized["profile_id"]})
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=authorized["profile_id"])

    # a-3 A-family rebuild (C ruling 06:19Z): live parent via the acceptance route
    # so its frozen object carries the permissions section; fake port leaves it running.
    _, _parent_turn = sessions.create_turn(parent_session["session_id"], "parent-key", {
        "text": "parent task",
        "expected_profile_revision": int(profiles.get(parent["profile_id"])["config_revision"]),
    })
    service.parent_turn_id = _parent_turn["turn_id"]

    def session_with_handle(profile_id, workspace_id, key, handle):
        sid = sessions.create_session(key, {
            "workspace_id": workspace_id, "profile_id": profile_id})[1]["session_id"]
        with database.transaction() as conn:
            conn.execute("UPDATE server_sessions SET checkpoint_native_id=? WHERE id=?", (handle, sid))
        return sid

    d_session = session_with_handle(unauthorized["profile_id"], ws_other, "d-seed", "delta-handle")
    claude_session = session_with_handle(foreign["profile_id"], ws_other, "cl-seed", "claude-handle")
    # A handle shared by two sessions -> ambiguous.
    amb_a = session_with_handle(authorized["profile_id"], ws_parent, "amb-a", "amb-handle")
    amb_b = session_with_handle(unauthorized["profile_id"], ws_other, "amb-b", "amb-handle")
    return dict(database=database, records=records, service=service, sessions=sessions,
                parent=parent, authorized=authorized, d_session=d_session,
                claude_session=claude_session, amb=(amb_a, amb_b))


def _run(env, args):
    return env["service"].run(parent_turn_id=env["service"].parent_turn_id,
                              parent_profile_id=env["parent"]["profile_id"], arguments=args)


def test_resuming_an_unauthorized_same_family_handle_is_refused(tmp_path):
    env = _env(tmp_path)
    with pytest.raises(DelegationError) as refused:
        _run(env, {"subagent": "beta", "description": "continue the prior work", "prompt": "x",
                   "task_id": "delta-handle"})
    assert refused.value.code == "SUBAGENT_NOT_AUTHORIZED"


def test_ambiguous_handle_fails_deterministically_not_by_row_order(tmp_path):
    env = _env(tmp_path)
    with pytest.raises(DelegationError) as refused:
        _run(env, {"subagent": "beta", "description": "continue the prior work", "prompt": "x",
                   "task_id": "amb-handle"})
    assert refused.value.code == "SUBAGENT_NOT_AUTHORIZED"


def test_cross_family_handle_still_gives_the_family_code(tmp_path):
    # G5: the existing cross-family rejection must remain SUBAGENT_TASK_FAMILY_MISMATCH.
    env = _env(tmp_path)
    with pytest.raises(DelegationError) as refused:
        _run(env, {"subagent": "beta", "description": "continue the prior work", "prompt": "x",
                   "task_id": "claude-handle"})
    assert refused.value.code == "SUBAGENT_TASK_FAMILY_MISMATCH"


def test_resuming_the_authorized_child_own_handle_still_works(tmp_path):
    env = _env(tmp_path)
    first = _run(env, {"subagent": "beta", "description": "start the child work", "prompt": "x"})
    second = _run(env, {"subagent": "beta", "description": "continue the prior work", "prompt": "y",
                        "task_id": first["task_id"]})
    assert second["resumed"] is True
    assert second["sessionId"] == first["sessionId"]
