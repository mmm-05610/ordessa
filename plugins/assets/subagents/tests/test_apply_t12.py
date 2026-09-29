"""T12 apply orchestration — send-exactly-once, same-session resume, busy/unload.

Evidence level (read this first): every "flow works" test below injects a
controlled, in-memory fixture that mimics the shape of C0's
`ConfigurationService` (the same stand-in style as
`plugins/harness/tests/test_configuration_service_controlled.py`). It proves the
ORDERING of this orchestrator, i.e. L1/L2. It is **not** production G18/G19/G20
evidence: the default product's ACP admission port reports `ready=False` here, so
no real one-use permit, native runtime generation or operation-bound native
receipt exists, and the honest default outcome of `plan_apply` with no injected
service is a typed refusal (see `test_honest_default_refuses_missing_port`).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from ordessa_harness_api import (
    ApplicationTarget, Confirmed, DesiredFragment, NotFound, OperationRecord,
    Plan, Refused, TargetHandle, Unknown,
)
from ordessa_harness_api.errors import ErrorCode

from ordessa_assets_subagents import apply as apply_mod, errors
from ordessa_assets_subagents.apply import (
    ApplyCoordinator, ApplyStatus, MessageRelease, NEW_SESSION_SENTINEL,
    PlanApplyRequest, missing_production_collaborators,
)

TARGET = ApplicationTarget("srv", "ses", "chan", 7)
HANDLE = TargetHandle("claude-agents", 8)
PINNED_SESSION = "native-session-1"


def _fragment(value="fixture-model") -> DesiredFragment:
    return DesiredFragment(apply_mod.FACET_ID, "item-1", "v1", "business:fixture",
                           "source-1", "set", {"model": value})


def _snapshot():
    # The orchestrator never reads the snapshot's fields (it is an opaque,
    # host-supplied pin), so a lightweight stand-in keeps this test independent
    # of the resolution/ceiling chain while the adapters seam is remapped.
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _SnapshotPin:
        snapshot_digest: str

    return _SnapshotPin("sha256:" + "1" * 64)


class FixtureService:
    """An in-memory stand-in for the C0 ConfigurationService Protocol (L1/L2)."""

    def __init__(self, *, result="confirmed"):
        self.result = result
        self.plan_calls = 0
        self.apply_calls = 0
        self._plans: dict[str, Plan] = {}
        self._records: dict[str, OperationRecord] = {}

    def inspect(self, target):  # not used by the orchestrator
        raise NotImplementedError

    def _plan(self, target, plan_id="plan-1"):
        plan = Plan(plan_id, target, "digest", "base-1", "native-version-1",
                    1, "auth-1", "secret-ref-1", "2099-01-01T00:00:00+00:00")
        self._plans[plan_id] = plan
        return plan

    def plan(self, target, desired_fragments, expected_revision):
        self.plan_calls += 1
        if self.result == "plan-refused":
            return Refused(ErrorCode.STALE_PLAN, ("expected revision changed",), True)
        return self._plan(target)

    def apply(self, plan_id, operation_key, submission_permit):
        self.apply_calls += 1
        if self.result == "confirmed":
            confirmed = Confirmed(operation_key, "applied-1", PINNED_SESSION,
                                  TARGET.runtime_generation, "fixture:evidence",
                                  ("private/settings.json",))
            self._records[operation_key] = OperationRecord(operation_key, operation_key,
                                                            TARGET, confirmed)
            return confirmed
        if self.result == "refused":
            return Refused(ErrorCode.TARGET_CONFLICT, ("native field collision",), True,
                           operation_id=operation_key)
        if self.result == "unknown":
            unknown = Unknown(operation_key, "verifying", ("partial generation written",),
                              ("native readback required",), "reconcile")
            self._records[operation_key] = OperationRecord(operation_key, operation_key,
                                                            TARGET, unknown)
            return unknown
        raise AssertionError(f"unknown fixture result {self.result!r}")

    def query(self, operation_key):
        return self._records.get(operation_key, NotFound(operation_key))

    def reconcile(self, operation_key):
        record = self.query(operation_key)
        return record.result if isinstance(record, OperationRecord) else Refused(
            ErrorCode.OPERATION_UNKNOWN, ("operation not found",), True)


def _request(coordinator_target=TARGET, handle=HANDLE, operation_key="op-1",
             host_session=PINNED_SESSION, pinned_session=PINNED_SESSION,
             message="please review the diff"):
    return PlanApplyRequest(
        snapshot=_snapshot(), target=coordinator_target, handle=handle,
        fragments=(_fragment(),), operation_key=operation_key,
        submission_permit="signed:fixture", expected_revision="base-1",
        pinned_session_identity=pinned_session, host_session_identity=host_session,
        original_message=message,
    )


# -- 5. today's reality check: honest default is a typed refusal ---------------

def test_honest_default_refuses_missing_port():
    """No injected service => refusal naming the missing port, no simulation."""
    coordinator = ApplyCoordinator(service=None)
    outcome = coordinator.plan_apply(_request())
    assert outcome.status is ApplyStatus.ABSENT
    assert outcome.reason_code == errors.NATIVE_ENTRY_UNAVAILABLE
    assert "ready=False" in outcome.detail
    assert "one-use execution permit" in outcome.detail
    # a refusal never issues a send
    assert not outcome.released
    assert coordinator.outbox == ()
    # refusal records the exact missing production collaborators
    assert set(outcome.item_diagnostics) == set(missing_production_collaborators())


def test_missing_collaborator_seam_report_lists_the_four_authorities():
    missing = missing_production_collaborators()
    assert "acp_admission_port_ready" in missing
    assert "one_use_execution_permit" in missing
    assert "native_runtime_generation" in missing
    assert "operation_bound_native_receipt" in missing


def test_reconcile_without_service_is_absent_refusal():
    coordinator = ApplyCoordinator(service=None)
    outcome = coordinator.reconcile("op-1")
    assert outcome.status is ApplyStatus.ABSENT
    assert not outcome.released


# -- 2. send-exactly-once gate (G18) -------------------------------------------

def test_confirmed_sends_original_message_once_fixture_level():
    """L1/L2 fixture ordering proof, NOT production G18 evidence."""
    outbox: list[str] = []
    service = FixtureService(result="confirmed")
    coordinator = ApplyCoordinator(service=service, outbox=outbox)
    outcome = coordinator.plan_apply(_request(message="review the diff please"))
    assert outcome.status is ApplyStatus.CONFIRMED
    assert outbox == ["review the diff please"]
    assert service.apply_calls == 1


def test_replay_same_operation_key_does_not_send_twice():
    service = FixtureService(result="confirmed")
    outbox: list[str] = []
    coordinator = ApplyCoordinator(service=service, outbox=outbox)
    request = _request(operation_key="op-key")
    first = coordinator.plan_apply(request)
    second = coordinator.plan_apply(request)   # same key -> recorded replay
    assert first.status is ApplyStatus.CONFIRMED
    assert second is first
    assert outbox == ["please review the diff"]  # exactly one
    assert service.apply_calls == 1              # replay never re-applies


def test_refused_never_sends_and_leaves_state_untouched():
    service = FixtureService(result="refused")
    outbox: list[str] = []
    coordinator = ApplyCoordinator(service=service, outbox=outbox)
    outcome = coordinator.plan_apply(_request())
    assert outcome.status is ApplyStatus.REFUSED
    assert outcome.reason_code == ErrorCode.TARGET_CONFLICT.value
    assert outcome.item_diagnostics == ("native field collision",)  # reason per item
    assert outbox == []
    assert not outcome.released


def test_plan_refusal_sends_nothing():
    service = FixtureService(result="plan-refused")
    outbox: list[str] = []
    coordinator = ApplyCoordinator(service=service, outbox=outbox)
    outcome = coordinator.plan_apply(_request())
    assert outcome.status is ApplyStatus.REFUSED
    assert service.apply_calls == 0
    assert outbox == []


def test_unknown_sends_nothing_and_stays_queryable():
    service = FixtureService(result="unknown")
    outbox: list[str] = []
    coordinator = ApplyCoordinator(service=service, outbox=outbox)
    outcome = coordinator.plan_apply(_request(operation_key="op-u"))
    assert outcome.status is ApplyStatus.UNKNOWN
    assert outbox == []
    assert not outcome.released
    assert isinstance(outcome.service_result, Unknown)
    # queryable by operationKey
    record = service.query("op-u")
    assert isinstance(record, OperationRecord) and record.result.kind == "unknown"


def test_retry_attempt_on_unknown_does_not_send_or_reapply():
    """§C4: an Unknown must not auto-retry the prompt or the effect."""
    service = FixtureService(result="unknown")
    outbox: list[str] = []
    coordinator = ApplyCoordinator(service=service, outbox=outbox)
    request = _request(operation_key="op-u")
    coordinator.plan_apply(request)
    assert service.apply_calls == 1
    # a second call with the same key is a recorded replay, not a fresh apply
    second = coordinator.plan_apply(request)
    assert second.status is ApplyStatus.UNKNOWN
    assert service.apply_calls == 1
    assert outbox == []


def test_release_object_is_structurally_single_use():
    """Prove the guard: switch MessageRelease to a boolean-and-kept-message and
    this test goes red because a second release() would return the message."""
    release = MessageRelease("the original message")
    assert release.release() == "the original message"
    assert release.spent is True
    assert release.release() is None      # second call yields nothing
    assert release.release() is None      # and remains nothing, structurally


# -- 3. same-session resume (G19) ---------------------------------------------

def test_absent_native_session_identity_is_refused():
    service = FixtureService(result="confirmed")
    outbox: list[str] = []
    coordinator = ApplyCoordinator(service=service, outbox=outbox)
    outcome = coordinator.plan_apply(_request(host_session=None))
    assert outcome.status is ApplyStatus.REFUSED
    assert outcome.reason_code == errors.NATIVE_ENTRY_UNAVAILABLE
    assert service.apply_calls == 0 and outbox == []


def test_fresh_session_new_identity_is_refused_as_restoration():
    """G19 negative: a `session/new`-style identity must never pass as restore."""
    service = FixtureService(result="confirmed")
    outbox: list[str] = []
    coordinator = ApplyCoordinator(service=service, outbox=outbox)
    outcome = coordinator.plan_apply(_request(host_session=NEW_SESSION_SENTINEL))
    assert outcome.status is ApplyStatus.REFUSED
    assert "session/new" in outcome.detail or "never accepted as restoration" in outcome.detail
    assert service.apply_calls == 0 and outbox == []


def test_mismatched_pinned_session_identity_is_refused():
    service = FixtureService(result="confirmed")
    coordinator = ApplyCoordinator(service=service)
    outcome = coordinator.plan_apply(_request(host_session="other-native-session"))
    assert outcome.status is ApplyStatus.REFUSED
    assert "not the pinned" in outcome.detail
    assert service.plan_calls == 0  # refused before even planning


# -- 4. busy / unload ordering (G20) ------------------------------------------

def test_busy_instance_refuses_superseding_plan():
    service = FixtureService(result="unknown")
    coordinator = ApplyCoordinator(service=service)
    coordinator.plan_apply(_request(operation_key="pending"))  # leaves target busy
    assert service.apply_calls == 1
    supersede = coordinator.plan_apply(_request(operation_key="supersede"))
    assert supersede.status is ApplyStatus.REFUSED
    assert supersede.reason_code == errors.PROVIDER_BUSY
    assert service.apply_calls == 1  # superseding plan never reaches apply


def test_unload_while_busy_is_refused():
    service = FixtureService(result="unknown")
    coordinator = ApplyCoordinator(service=service)
    coordinator.plan_apply(_request(operation_key="pending"))
    outcome = coordinator.request_unload(TARGET)
    assert outcome.status is ApplyStatus.REFUSED
    assert outcome.reason_code == errors.PROVIDER_BUSY


def test_unload_allowed_when_settled():
    service = FixtureService(result="confirmed")
    coordinator = ApplyCoordinator(service=service)
    coordinator.plan_apply(_request(operation_key="done"))  # confirmed -> settled
    outcome = coordinator.request_unload(TARGET)
    assert outcome.status is ApplyStatus.CONFIRMED


def test_stale_generation_plan_is_marked_stale_and_never_applied():
    """G20: use TargetHandle.generation as the pin; an older generation cannot land."""
    service = FixtureService(result="confirmed")
    coordinator = ApplyCoordinator(service=service)
    coordinator.plan_apply(_request(handle=TargetHandle("claude-agents", 8),
                                     operation_key="gen8"))
    assert service.apply_calls == 1
    late_plan = coordinator.plan_apply(_request(handle=TargetHandle("claude-agents", 7),
                                                operation_key="gen7-late"))
    assert late_plan.status is ApplyStatus.REFUSED
    assert late_plan.reason_code == errors.REVISION_STALE
    # refused before the plan call, so the stale generation cannot land
    assert service.plan_calls == 1


def test_equal_generation_is_not_treated_as_stale():
    service = FixtureService(result="confirmed")
    coordinator = ApplyCoordinator(service=service)
    coordinator.plan_apply(_request(handle=TargetHandle("h", 5), operation_key="a"))
    outcome = coordinator.plan_apply(_request(handle=TargetHandle("h", 6), operation_key="b"))
    assert outcome.status is ApplyStatus.CONFIRMED


# -- reconcile keeps an Unknown queryable, no overwrite-clear -----------------

def test_reconcile_unknown_returns_recorded_result_no_send():
    service = FixtureService(result="unknown")
    outbox: list[str] = []
    coordinator = ApplyCoordinator(service=service, outbox=outbox)
    coordinator.plan_apply(_request(operation_key="op-u"))
    outcome = coordinator.reconcile("op-u")
    assert outcome.status is ApplyStatus.UNKNOWN
    assert outbox == []


# -- FR08: the orchestrator is pure; no I/O, no spawn, no socket --------------

@pytest.mark.parametrize("forbidden", ["subprocess", "socket", "os.system", "Popen",
                                        "http.client", "urllib", "fork", "execve"])
def test_apply_source_contains_no_effect_capability(forbidden):
    source = Path(apply_mod.__file__).read_text(encoding="utf-8")
    assert forbidden not in source, f"apply.py must not reference {forbidden!r}"


def test_apply_source_makes_no_builtin_open_call():
    """FR08: no `open()` anywhere in apply.py (it never writes files)."""
    tree = ast.parse(Path(apply_mod.__file__).read_text(encoding="utf-8"))
    open_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "open"
    ]
    assert open_calls == []
