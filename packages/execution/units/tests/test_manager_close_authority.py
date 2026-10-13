"""Manager drain is gated by the production owner's finite cleanup authority."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from test_local_owner import live_owner
from test_public_unit_api import public_units
from ordessa_interfaces.system_access.contracts.transport import AccessError
from ordessa_units.admission.invocation import InvocationAuthorityRefused
from ordessa_units.admission.run_permission import LocalUnitInvocationAuthority
from ordessa_units.api.errors import UnitApiRefused
from ordessa_units.assembly.instance import UnitAssembly


def _start_unit(world):
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    interaction = unit.interaction(authorization)
    prompt = {"prompt": [{"type": "text", "text": "manager close authority"}]}
    assert interaction.prompt(prompt, timeout=5)["stopReason"] == "end_turn"
    return unit, interaction, authorization, prompt


def _assert_refusal_preserved_owner(world, operations_before):
    assert world.original_manager._draining is False
    assert len(world.owner._operations) == operations_before


def test_foreign_manager_authorization_does_not_drain_or_block_unit(live_owner):
    world = live_owner
    unit, interaction, authorization, prompt = _start_unit(world)
    operations_before = len(world.owner._operations)
    foreign = LocalUnitInvocationAuthority(
        world.admission.store_port, world.permission, owner_id="different-owner"
    ).authorization()

    with pytest.raises(InvocationAuthorityRefused):
        world.public_manager.close(foreign)
    _assert_refusal_preserved_owner(world, operations_before)
    assert world.public_manager.get(unit.identity) is unit
    assert interaction.prompt(prompt, timeout=5)["stopReason"] == "end_turn"


def test_expired_manager_authorization_does_not_drain_or_block_unit(live_owner):
    world = live_owner
    unit, interaction, authorization, prompt = _start_unit(world)
    operations_before = len(world.owner._operations)
    world.now[0] = world.permission.expires_at + 1

    with pytest.raises(InvocationAuthorityRefused):
        world.public_manager.close(authorization)
    _assert_refusal_preserved_owner(world, operations_before)

    world.now[0] = 10.0
    assert interaction.prompt(prompt, timeout=5)["stopReason"] == "end_turn"
    assert world.public_manager.get(unit.identity) is unit


@pytest.mark.parametrize("missing_action", ["stop", "release"])
def test_manager_close_requires_both_cleanup_actions_before_drain(live_owner, missing_action):
    world = live_owner
    unit, interaction, authorization, prompt = _start_unit(world)
    operations_before = len(world.owner._operations)
    authority = world.owner.authority
    original_permission = authority.permission
    authority.permission = replace(
        original_permission,
        actions=frozenset(original_permission.actions - {missing_action}),
    )
    try:
        with pytest.raises(InvocationAuthorityRefused):
            world.public_manager.close(authorization)
        _assert_refusal_preserved_owner(world, operations_before)
    finally:
        authority.permission = original_permission

    assert interaction.prompt(prompt, timeout=5)["stopReason"] == "end_turn"
    assert world.public_manager.get(unit.identity) is unit


def test_revoked_access_does_not_drain_original_manager(live_owner):
    world = live_owner
    _unit, _interaction, authorization, _prompt = _start_unit(world)
    operations_before = len(world.owner._operations)
    world.access.revoke()
    world.access_revoked_cleanup = True

    with pytest.raises(AccessError):
        world.public_manager.close(authorization)
    _assert_refusal_preserved_owner(world, operations_before)


def test_missing_manager_close_hook_refuses_without_drain(public_units):
    fixture = public_units

    class MissingCloseGate:
        def resolve_plan(self, *_args):
            raise AssertionError("close does not resolve a plan")

        def authorize(self, *_args):
            raise AssertionError("close does not mint a unit invocation")

    assembly = UnitAssembly(fixture.original, MissingCloseGate())
    with pytest.raises(UnitApiRefused, match="manager close authorization"):
        assembly.close_manager(fixture.authorization("missing-gate"))
    assert fixture.original._draining is False


def test_controlled_binding_rejects_unidentified_close_authorization(public_units):
    fixture = public_units
    with pytest.raises(UnitApiRefused):
        fixture.manager.close(object())
    assert fixture.original._draining is False


def test_authorized_manager_close_preserves_original_stop_release_and_use(live_owner):
    world = live_owner
    unit, _interaction, authorization, _prompt = _start_unit(world)
    result = world.public_manager.close(authorization)

    assert result["state"] == "confirmed"
    assert result["units"][0]["state"] == "confirmed"
    assert world.original_manager._draining is True
    assert world.original_manager._units == {}
    assert world.records.owner_read_termination(unit.identity["unitId"], "stop")["state"] == "confirmed"
    assert world.records.owner_read_termination(unit.identity["unitId"], "release")["state"] == "confirmed"
    assert world.environment.snapshot.active_uses == 0
