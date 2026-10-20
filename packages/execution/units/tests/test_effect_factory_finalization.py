"""Deferred effect-write factory is finalized before any Unit effect."""
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, current_thread
from types import SimpleNamespace

import pytest

pytest_plugins = ("test_local_owner",)

from ordessa_execution_agents.harness.transport import EffectWriteGuard
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.admission.owner_selection import AgentOwnerUnavailable
from ordessa_units.admission.invocation import InvocationAuthorityRefused
from ordessa_units.management.manager import UnitManagementRefused


@asynccontextmanager
async def _acquire_effect(identity, deadline, calls):
    calls.append(current_thread())
    yield


@asynccontextmanager
async def _acquire_fixed_effect(identity, deadline):
    yield


def _factory(calls):
    def make_guard(unit_ref, operation_ref, input_digest, params):
        return EffectWriteGuard(
            unit_ref,
            operation_ref,
            input_digest,
            params,
            lambda identity, deadline: _acquire_effect(identity, deadline, calls),
        )

    return make_guard


def _fixed_factory(unit_ref, operation_ref, input_digest, params):
    return EffectWriteGuard(unit_ref, operation_ref, input_digest, params, _acquire_fixed_effect)


def _reservation_count(world):
    with world.journal._connect() as db:
        return db.execute("SELECT COUNT(*) FROM harness_unit_reservations").fetchone()[0]


def _turn_count(world):
    with world.journal._connect() as db:
        return db.execute("SELECT COUNT(*) FROM harness_acp_turn_attempts").fetchone()[0]


@pytest.mark.parametrize(
    "live_owner",
    [{"defer_effect_write_guard_factory": True, "acp_turn_opt_in": True}],
    indirect=True,
)
def test_deferred_owner_refuses_create_until_factory_then_uses_original_guard(live_owner):
    world = live_owner
    owner, authorization = world.owner, world.owner.authorization()
    assert owner.effect_write_guard_factory is None
    pending_operations = world.store.pending_operations("env")
    reservation_count = _reservation_count(world)
    attempts = tuple(world.original_manager._attempts)
    active_uses = world.environment.snapshot.active_uses

    with pytest.raises(AgentOwnerUnavailable, match="finalization"):
        owner.ensure_unit_creation_ready()

    with pytest.raises(AgentOwnerUnavailable, match="finalization"):
        owner.resolve_plan(owner.spec, authorization)

    with pytest.raises(AgentOwnerUnavailable, match="finalization"):
        world.public_manager.create(owner.spec, authorization)

    with pytest.raises(AgentOwnerUnavailable, match="finalization"):
        owner.authorize("prepare", owner.spec, authorization)

    # A Mapping plan and structurally sufficient negative-control context
    # cannot bypass the original Manager's creation preflight or claim an attempt.
    forged_context = SimpleNamespace(facts={
        "action": "prepare",
        "query": False,
        "request": {"environmentNamespace": "env", "principalScope": "fixture-principal",
                    "requestId": "forged-pending-prepare"},
        "operationRef": "forged-pending-prepare.prepare",
        "stepId": "forged-pending-prepare.prepare.native",
    })
    with pytest.raises(AgentOwnerUnavailable, match="finalization"):
        world.original_manager.create({}, forged_context, specification=owner.spec)

    assert world.store.pending_operations("env") == pending_operations
    assert _reservation_count(world) == reservation_count == 0
    assert tuple(world.original_manager._attempts) == attempts == ()
    assert tuple(world.original_manager._units) == ()
    assert world.public_manager.list() == ()
    assert world.environment.snapshot.active_uses == active_uses == 0
    assert owner.effect_write_guard_factory is None

    with pytest.raises(AttributeError):
        owner.effect_write_guard_factory = _factory([])

    effect_threads = []
    guard_factory = _factory(effect_threads)
    original_manager, records = world.original_manager, world.records
    owner.bind_effect_write_guard_factory(guard_factory)
    assert owner.effect_write_guard_factory is guard_factory
    assert owner.manager is world.public_manager
    assert owner.records is records
    assert owner._ports.unit_manager is original_manager

    unit = world.public_manager.create(owner.spec, authorization)
    native = owner.native_unit(unit, authorization)
    effect_thread = native.effect_write_thread
    lease = owner.authorize("interaction", unit, authorization)
    prompt = [{"type": "text", "text": "effect factory finalized"}]
    response = native.prompt(
        unit.identity,
        lease,
        operation_ref="factory-finalization-turn",
        timeout=5,
        prompt=prompt,
    )

    assert response["state"] == "completed"
    assert response["operationRef"] == "factory-finalization-turn"
    assert safe_json({"prompt": response["input"]["params"]["prompt"]}) == safe_json({"prompt": prompt})
    assert safe_json({"prompt": response["response"]["result"]["observedPrompt"]}) == safe_json({"prompt": prompt})
    assert effect_threads == [effect_thread]
    assert _turn_count(world) == 1
    assert unit.close(authorization)["state"] == "confirmed"


@pytest.mark.parametrize(
    "live_owner",
    [{"defer_effect_write_guard_factory": True, "acp_turn_opt_in": True}],
    indirect=True,
)
def test_invalid_factory_does_not_finalize_or_create_effects(live_owner):
    world = live_owner
    owner = world.owner
    before = (
        tuple(world.store.pending_operations("env")),
        _reservation_count(world),
        tuple(world.original_manager._attempts),
        world.environment.snapshot.active_uses,
    )

    with pytest.raises(AgentOwnerUnavailable):
        owner.bind_effect_write_guard_factory(object())

    assert owner.effect_write_guard_factory is None
    assert (
        tuple(world.store.pending_operations("env")),
        _reservation_count(world),
        tuple(world.original_manager._attempts),
        world.environment.snapshot.active_uses,
    ) == before


@pytest.mark.parametrize(
    "configuration",
    [
        {"acp_turn_opt_in": False, "effect_write_guard_factory": None},
        {"acp_turn_opt_in": True, "effect_write_guard_factory": _fixed_factory},
    ],
    ids=["requires-original-acp-opt-in", "requires-empty-pending-factory"],
)
@pytest.mark.parametrize(
    "live_owner",
    [{"acp_turn_opt_in": True}],
    indirect=True,
)
def test_deferred_owner_configuration_requires_opt_in_and_empty_factory(
    live_owner, configuration
):
    world = live_owner
    owner = world.owner
    before = (
        tuple(world.store.pending_operations("env")),
        _reservation_count(world),
        tuple(world.original_manager._attempts),
        world.environment.snapshot.active_uses,
    )

    from ordessa_units.assembly.local_owner import build_local_unit_owner

    with pytest.raises(AgentOwnerUnavailable):
        build_local_unit_owner(
            admission_context=world.admission,
            permission=world.permission,
            environment_instance=world.environment,
            preparation=world.preparation,
            materializer=world.materializer,
            environment_sharing=True,
            timeout=5,
            callback_approval=None,
            effect_write_guard_factory=configuration["effect_write_guard_factory"],
            acp_turn_opt_in=configuration["acp_turn_opt_in"],
            defer_effect_write_guard_factory=True,
            clock=lambda: world.now[0],
        )

    assert (
        tuple(world.store.pending_operations("env")),
        _reservation_count(world),
        tuple(world.original_manager._attempts),
        world.environment.snapshot.active_uses,
    ) == before


@pytest.mark.parametrize(
    "live_owner",
    [{"defer_effect_write_guard_factory": True, "acp_turn_opt_in": True}],
    indirect=True,
)
def test_factory_is_bound_once_even_when_rebound_with_same_object(live_owner):
    owner = live_owner.owner
    first = _factory([])
    second = _factory([])
    owner.bind_effect_write_guard_factory(first)

    with pytest.raises(AgentOwnerUnavailable):
        owner.bind_effect_write_guard_factory(first)
    with pytest.raises(AgentOwnerUnavailable):
        owner.bind_effect_write_guard_factory(second)
    assert owner.effect_write_guard_factory is first


@pytest.mark.parametrize(
    "live_owner",
    [{"defer_effect_write_guard_factory": True, "acp_turn_opt_in": True}],
    indirect=True,
)
def test_concurrent_finalizers_bind_exactly_one_factory(live_owner):
    owner = live_owner.owner
    barrier = Barrier(2)
    factories = (_factory([]), _factory([]))

    def finalize(factory):
        barrier.wait()
        try:
            owner.bind_effect_write_guard_factory(factory)
            return "bound", factory
        except AgentOwnerUnavailable:
            return "refused", factory

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(finalize, factories))

    assert sorted(result for result, _factory_value in results) == ["bound", "refused"]
    winner = next(factory for result, factory in results if result == "bound")
    assert owner.effect_write_guard_factory is winner


@pytest.mark.parametrize(
    "preflight_result",
    [False, None],
    ids=["false", "none"],
)
@pytest.mark.parametrize(
    "live_owner",
    [{"defer_effect_write_guard_factory": True, "acp_turn_opt_in": True}],
    indirect=True,
)
def test_original_manager_rejects_non_true_creation_preflight(
    live_owner, monkeypatch, preflight_result
):
    world = live_owner
    owner = world.owner
    owner.bind_effect_write_guard_factory(_factory([]))
    forged_context = SimpleNamespace(facts={
        "action": "prepare",
        "query": False,
        "request": {"environmentNamespace": "env", "principalScope": "fixture-principal",
                    "requestId": "negative-preflight"},
        "operationRef": "negative-preflight.prepare",
        "stepId": "negative-preflight.prepare.native",
    })
    before = (
        tuple(world.store.pending_operations("env")),
        _reservation_count(world),
        tuple(world.original_manager._attempts),
        tuple(world.original_manager._units),
        world.environment.snapshot.active_uses,
    )
    monkeypatch.setattr(world.original_manager, "_creation_preflight", lambda: preflight_result)

    with pytest.raises(UnitManagementRefused):
        world.original_manager.create({}, forged_context, specification=owner.spec)

    assert (
        tuple(world.store.pending_operations("env")),
        _reservation_count(world),
        tuple(world.original_manager._attempts),
        tuple(world.original_manager._units),
        world.environment.snapshot.active_uses,
    ) == before


@pytest.mark.parametrize(
    "live_owner",
    [
        {},
        {"acp_turn_opt_in": True, "effect_write_guard_factory": _fixed_factory},
    ],
    indirect=True,
    ids=["unconfigured-immediate", "configured-immediate"],
)
def test_immediate_owner_cannot_be_changed_to_deferred_factory(live_owner):
    world = live_owner
    owner = world.owner
    with pytest.raises(AgentOwnerUnavailable):
        owner.bind_effect_write_guard_factory(_factory([]))
    assert owner.effect_write_guard_factory is (None if not owner.acp_turn_opt_in else _fixed_factory)
    assert world.environment.snapshot.active_uses == 0


@pytest.mark.parametrize(
    "live_owner",
    [{"defer_effect_write_guard_factory": True, "acp_turn_opt_in": True}],
    indirect=True,
)
@pytest.mark.parametrize("state", ["draining", "revoked", "expired"])
def test_closed_or_invalid_owner_cannot_finalize_factory(live_owner, state):
    world = live_owner
    if state == "draining":
        assert world.public_manager.close(world.owner.authorization())["state"] == "confirmed"
        expected = AgentOwnerUnavailable
    elif state == "revoked":
        world.access_revoked_cleanup = True
        world.owner.revoke()
        expected = InvocationAuthorityRefused
    else:
        world.now[0] = world.permission.expires_at + 1
        expected = InvocationAuthorityRefused

    with pytest.raises(expected):
        world.owner.bind_effect_write_guard_factory(_factory([]))
    assert world.owner.effect_write_guard_factory is None
    assert _reservation_count(world) == 0
    assert tuple(world.original_manager._attempts) == ()
    assert world.environment.snapshot.active_uses == 0
