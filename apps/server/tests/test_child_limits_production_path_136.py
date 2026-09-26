"""Work Order 136: the child's "narrow-only" limits must reach the *production* call.

`validate_run_arguments` already implements the G2 narrowing checks and both refusal
codes (`SUBAGENT_PERMISSION_WIDENED` / `SUBAGENT_MODEL_WIDENED`) - and `test_subagents.py`
proves them by *manually* stuffing ``child_limits`` in. But the real delegating caller
(`DelegationService.run`) never passed ``child_limits``, so on the production path those
two branches were structurally dead: an over-wide preset or a different model slipped
through as ACCEPTED (AUD-B-018, OF-14 family case #5).

Every gate here drives the **production** `DelegationService.run`, never a hand-built
`child_limits`, and asserts:
* a child on `plan` asked to run at `default` is refused `SUBAGENT_PERMISSION_WIDENED`;
* a model-pinned child asked for another model is refused `SUBAGENT_MODEL_WIDENED`;
* legitimate tightening is still accepted, and a child that declares no models is
  never over-rejected.
"""
from __future__ import annotations

import pytest

from ordessa_server.execution.delegation import DelegationService
from ordessa_server.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.profiles import ProfileRecords
from ordessa_server.profiles.subagents import DelegationError, validate_run_arguments
from ordessa_server_compat.sessions import SessionRecords, SessionService
from ordessa_server.workspaces import WorkspaceRecords
from pacthold.storage import Database, ObjectStore


class _FakeExecution:
    """Completes every accepted child turn so the run returns a normal result."""

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


class _FakeRegistry:
    """Resolves one harness to a model-control id, so the model slot is locatable."""

    def __init__(self, control_id: str) -> None:
        self._control_id = control_id

    def __contains__(self, harness: str) -> bool:
        return harness == "codex"

    def get(self, harness: str):
        return type("Descriptor", (), {"model_control_id": self._control_id})()


def _env(tmp_path, *, child_preset: str | None = None, registry=None, child_config: dict | None = None):
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
                                execution=execution, registry=registry, objects=objects)

    parent_cfg = objects.publish(
        b'{"schema_version":1,"harness_type":"codex","configuration":{}}').digest
    child_value = {"schema_version": 1, "harness_type": "codex",
                   "configuration": (child_config or {})}
    import json
    child_cfg = objects.publish(json.dumps(child_value).encode()).digest

    parent = profiles.create(key="p", request_digest="p", name="alpha", harness_type="codex",
                             config_digest=parent_cfg, credential_id=None)[1]
    child = profiles.create(key="c", request_digest="c", name="beta", harness_type="codex",
                            config_digest=child_cfg, credential_id=None)[1]
    if child_preset is not None:
        profiles.set_permissions(
            profile_id=child["profile_id"], preset=child_preset, rules=[],
            expected_version=profiles.get(child["profile_id"])["version"],
            key="cp", request_digest="cp")
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])
    workspace = workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/workspace", connection_id="c")[1]
    session = sessions.create_session("parent-session", {
        "workspace_id": workspace["workspace_id"], "profile_id": parent["profile_id"]})[1]
    sessions.create_session("child-seed", {
        "workspace_id": workspace["workspace_id"], "profile_id": child["profile_id"]})
    # a-3 A-family rebuild (C ruling 06:19Z): parent via the acceptance route;
    # the fake port leaves it running after dispatch.
    _, _parent_turn = sessions.create_turn(session["session_id"], "parent-key", {
        "text": "parent task",
        "expected_profile_revision": int(profiles.get(parent["profile_id"])["config_revision"]),
    })
    service.parent_turn_id = _parent_turn["turn_id"]
    return service, parent, child


def _run(service, parent, args):
    return service.run(parent_turn_id=service.parent_turn_id,
                       parent_profile_id=parent["profile_id"], arguments=args)


def test_permission_widening_is_rejected_on_the_production_path(tmp_path):
    service, parent, _child = _env(tmp_path, child_preset="plan")
    with pytest.raises(DelegationError) as widened:
        _run(service, parent, {"subagent": "beta", "description": "do some work",
                               "prompt": "x", "permission": "default"})
    assert widened.value.code == "SUBAGENT_PERMISSION_WIDENED"


def test_permission_tightening_is_still_accepted_on_the_production_path(tmp_path):
    # A child on `default` may be run at the narrower `plan`.
    service, parent, _child = _env(tmp_path, child_preset="default")
    result = _run(service, parent, {"subagent": "beta", "description": "do some work",
                                    "prompt": "x", "permission": "plan"})
    assert result["state"] == "completed"


def test_model_widening_is_rejected_on_the_production_path(tmp_path):
    pinned = {"model": {"providerId": "prov-1", "modelId": "gpt-5"}}
    service, parent, _child = _env(tmp_path, registry=_FakeRegistry("model"),
                                   child_config=pinned)
    with pytest.raises(DelegationError) as widened:
        _run(service, parent, {"subagent": "beta", "description": "do some work",
                               "prompt": "x", "model": "gpt-2"})
    assert widened.value.code == "SUBAGENT_MODEL_WIDENED"


def test_pinned_model_is_accepted_and_unpinned_child_is_not_over_rejected(tmp_path):
    # The child's own model passes.
    service, parent, _child = _env(
        tmp_path, registry=_FakeRegistry("model"),
        child_config={"model": {"providerId": "prov-1", "modelId": "gpt-5"}})
    assert _run(service, parent, {"subagent": "beta", "description": "do some work",
                                  "prompt": "x", "model": "gpt-5"})["state"] == "completed"
    # A child that declares no models is never rejected for a model request.
    service2, parent2, _ = _env(tmp_path / "none", registry=_FakeRegistry("model"))
    assert _run(service2, parent2, {"subagent": "beta", "description": "do some work",
                                    "prompt": "x", "model": "whatever"})["state"] == "completed"


def test_counterexample_the_dead_low_seam_this_order_resurrects(tmp_path):
    # Pre-fix witness: validate_run_arguments WITHOUT child_limits accepts the very
    # widening the production path now refuses - this is exactly why the manual-seam
    # tests could be green while the code was dead. The fix routes limits through run.
    roster = [{"profileId": "c", "name": "beta", "harness": "codex", "description": "",
               "available": True, "reason": None}]
    ok = validate_run_arguments(
        {"subagent": "beta", "description": "do some work", "prompt": "x",
         "model": "gpt-2"}, roster=roster)  # no child_limits, as production used to
    assert ok["model"] == "gpt-2"  # ACCEPTED: the widening slipped through
