"""Work dispatch bootstrap through the original public Unit and ACP owners.

The peer is the existing controlled local ACP fixture; this test exercises no
provider model, alternate Unit authority, or test-only lifecycle implementation.
"""
from contextlib import contextmanager
from threading import Event, Lock, get_ident

import pytest

import test_local_owner as local_owner_fixture
from test_local_owner import live_owner
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_units.errors import UnitGuaranteeUnavailable
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
from ordessa_units.sessions.acp_factory import AcpChannelFactory
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess


WORK_INVOKE = "engineering.work.invoke"
DISPATCH = "engineering.executions.dispatch"
UNIT_START = "execution.units.start"


@pytest.fixture(autouse=True)
def _add_work_capabilities_before_live_owner(monkeypatch):
    """Extend the fixture authority before its LocalUnitOwner is constructed."""
    original = local_owner_fixture._access_authority

    def access_authority(*, capabilities=None, token=local_owner_fixture.BEARER):
        selected = tuple(dict.fromkeys((
            *(local_owner_fixture.CAPABILITIES if capabilities is None else capabilities),
            WORK_INVOKE,
            DISPATCH,
        )))
        return original(capabilities=selected, token=token)

    monkeypatch.setattr(local_owner_fixture, "_access_authority", access_authority)


def _observe_acp_start(monkeypatch, stages):
    original_handshake = AcpChannelFactory.handshake
    original_establish = AcpChannelFactory.establish_session

    def handshake(self, entry, *, before_effect):
        result = original_handshake(self, entry, before_effect=before_effect)
        stages.append("initialize-completed")
        return result

    def establish_session(self, entry, handshake_result, *, before_effect):
        result = original_establish(
            self, entry, handshake_result, before_effect=before_effect,
        )
        stages.append("session-new-completed")
        return result

    monkeypatch.setattr(AcpChannelFactory, "handshake", handshake)
    monkeypatch.setattr(AcpChannelFactory, "establish_session", establish_session)


def _engineering_access(world):
    return EngineeringCommandAccess(world.access)


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_work_dispatch_bootstrap_yields_same_authority_for_original_unit_start(
        live_owner, monkeypatch):
    world = live_owner
    access = _engineering_access(world)
    caller = world.principal
    stages = []
    _observe_acp_start(monkeypatch, stages)

    with access.admit(
        caller, Scope("env", "project"), WORK_INVOKE,
        request_id="controlled-work-bootstrap-positive",
        trace_id="controlled-work-bootstrap-positive",
    ) as work_context:
        with access.admit_work_step(
            work_context, DISPATCH,
            request_id="controlled-work-bootstrap-positive:dispatch",
        ) as dispatch_context:
            with access.guard_unit_bootstrap(
                dispatch_context, permission=world.permission,
            ):
                unit = world.public_manager.create(
                    world.owner.spec, world.owner.authorization(),
                )
            access.require(dispatch_context, DISPATCH)
        access.require(work_context, WORK_INVOKE)

    snapshot = unit.snapshot()
    assert snapshot["state"] == "confirmed"
    assert isinstance(snapshot["sessionId"], str) and snapshot["sessionId"]
    assert stages == ["initialize-completed", "session-new-completed"]

    closed = unit.close(world.owner.authorization())
    assert closed["state"] == "confirmed"
    assert world.records.owner_read_termination(
        unit.identity["unitId"], "stop",
    )["state"] == "confirmed"
    assert world.records.owner_read_termination(
        unit.identity["unitId"], "release",
    )["state"] == "confirmed"


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_dispatch_guard_without_bootstrap_blocks_original_acp_before_write(
        live_owner, monkeypatch):
    world = live_owner
    access = _engineering_access(world)
    caller = world.principal
    main_thread = get_ident()
    callback_attempted = Event()
    callback_entered = Event()
    event_lock = Lock()
    callback_threads = []
    stages = []
    _observe_acp_start(monkeypatch, stages)

    original_guard = world.access.guard

    @contextmanager
    def observed_guard(principal, scope, operation):
        thread_id = get_ident()
        is_sdk_start = operation == UNIT_START and thread_id != main_thread
        if is_sdk_start:
            with event_lock:
                callback_threads.append(thread_id)
            callback_attempted.set()
        with original_guard(principal, scope, operation):
            if is_sdk_start:
                callback_entered.set()
            yield

    monkeypatch.setattr(world.access, "guard", observed_guard)
    failed = None
    unit = None

    try:
        with access.admit(
            caller, Scope("env", "project"), WORK_INVOKE,
            request_id="controlled-work-bootstrap-negative",
            trace_id="controlled-work-bootstrap-negative",
        ) as work_context:
            with access.admit_work_step(
                work_context, DISPATCH,
                request_id="controlled-work-bootstrap-negative:dispatch",
            ) as dispatch_context:
                try:
                    world.public_manager.create(
                        world.owner.spec, world.owner.authorization(),
                    )
                except UnitLifecycleRefused as error:
                    assert callback_attempted.wait(2), (
                        "the original SDK write guard did not reach the Unit permission"
                    )
                    assert not callback_entered.is_set(), (
                        "the SDK thread unexpectedly entered the same authority guard"
                    )
                    units = world.public_manager.list()
                    assert len(units) == 1
                    unit = units[0]
                    assert unit.snapshot()["state"] == "unknown"
                    raise error
    except UnitLifecycleRefused as error:
        failed = error

    assert failed is not None, "unguarded cross-thread bootstrap unexpectedly completed"
    assert callback_attempted.is_set()
    assert callback_entered.wait(2), "the original callback did not resume after child guard exit"
    with event_lock:
        assert callback_threads
        assert all(thread_id != main_thread for thread_id in callback_threads)
    assert stages == [], "unknown bootstrap was incorrectly reported as a completed ACP stage"
    assert unit is not None and unit.snapshot()["state"] == "unknown"

    # Capture only the exact original process handle for post-termination
    # evidence; session reconciliation remains a separate UnitRecords fact.
    original_factory = unit._instance.channel_factory
    original_record = original_factory.owned_record
    assert original_record is not None
    process_exit_evidence = []
    release_calls = []
    original_release = original_factory.release

    def observe_before_release(entry):
        observation = original_record.process.observe()
        assert observation.state == "exited" and observation.exit_code is not None
        process_exit_evidence.append((observation.state, observation.exit_code is not None))
        release_calls.append(entry)
        return original_release(entry)

    monkeypatch.setattr(original_factory, "release", observe_before_release)

    # Reconcile the process only through its exact original Unit stop/release
    # path. These termination receipts do not resolve the unknown ACP session.
    closed = unit.close(world.owner.authorization())
    assert closed["state"] == "confirmed"
    assert world.records.owner_read_termination(
        unit.identity["unitId"], "stop",
    )["state"] == "confirmed"
    assert world.records.owner_read_termination(
        unit.identity["unitId"], "release",
    )["state"] == "confirmed"
    assert process_exit_evidence == [("exited", True)]
    assert release_calls == [original_record.entry]
    assert world.records.owner_read_session(
        unit.identity["unitId"],
    ).state == "unknown"

    pending = world.admission.pending()
    assert any(pending.values())
    with pytest.raises(UnitGuaranteeUnavailable):
        world.admission.close()
    assert any(world.admission.pending().values())

    # The existing fixture path releases only the EnvironmentUse and owner
    # objects. It deliberately preserves the unresolved session/start record.
    world.unknown_release_completed = True
    world.leave_unknown = True
