"""Low-level Unit stop performs auth and idle preflight before SDK quiescence."""
from threading import Event, Thread
from dataclasses import replace

import pytest

from ordessa_units.admission.invocation import InvocationAuthorityRefused

from test_local_owner import live_owner


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_invalid_low_level_stop_authorization_leaves_sdk_and_termination_untouched(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    client = instance.channel_factory.owned_record.entry

    with pytest.raises(InvocationAuthorityRefused):
        instance.stop(unit.identity, object())

    assert client._native_admission_open is True
    assert world.records.owner_read_termination(unit.identity['unitId'], 'stop') is None
    assert world.records.owner_read_termination(unit.identity['unitId'], 'release') is None
    assert instance.channel_factory.owned_record.process.observe().state == 'running'
    assert world.environment.snapshot.active_uses == 1


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_busy_low_level_stop_is_pending_without_consuming_or_opening_termination(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    client = instance.channel_factory.owned_record.entry
    context = world.owner.authorize('stop', unit, authorization)
    facts = context.facts
    request_ref = facts['request']
    from ordessa_infrastructure.identifiers import RequestKey
    request = RequestKey(request_ref['environmentNamespace'], request_ref['principalScope'],
                         request_ref['requestId'])
    claim_before = world.store.read_operation_step(request, facts['stepId'])
    assert claim_before is not None and claim_before.outcome == 'possibly-dispatched'
    entered, resume = Event(), Event()
    errors = []

    def hold_original_sdk_operation():
        try:
            with client.admitted_operation():
                entered.set()
                if not resume.wait(5):
                    raise TimeoutError('test SDK operation was not released')
        except BaseException as error:
            errors.append(error)

    worker = Thread(target=hold_original_sdk_operation)
    worker.start()
    assert entered.wait(5)
    try:
        result = instance.stop(unit.identity, context)
        assert result == {'unitRef': unit.identity, 'action': 'stop',
                          'state': 'pending', 'unresolved': True}
        assert client._native_admission_open is True
        assert world.issuer.verified_consumption(context) is False
        assert world.records.owner_read_termination(unit.identity['unitId'], 'stop') is None
        assert world.records.owner_read_termination(unit.identity['unitId'], 'release') is None
        assert world.store.read_operation_step(request, facts['stepId']) == claim_before
        assert instance.channel_factory.owned_record.process.observe().state == 'running'
        assert world.environment.snapshot.active_uses == 1
    finally:
        resume.set()
        worker.join(5)
    assert not worker.is_alive()
    assert errors == []

    stopped = instance.stop(unit.identity, context)
    world.owner.complete('stop', unit, context, stopped)
    assert stopped['state'] == 'confirmed'
    assert world.issuer.verified_consumption(context) is True
    assert world.records.owner_read_termination(unit.identity['unitId'], 'stop')['state'] == 'confirmed'
    assert world.records.owner_read_termination(unit.identity['unitId'], 'release') is None
    assert world.environment.snapshot.active_uses == 1
    assert world.public_manager.close(authorization)['state'] == 'confirmed'
    assert world.environment.snapshot.active_uses == 0


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_revoke_during_current_state_preflight_does_not_quiesce_live_unit(live_owner, monkeypatch):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    client = instance.channel_factory.owned_record.entry
    context = world.owner.authorize('stop', unit, authorization)
    original_inspect = world.owner.state.inspect

    def revoke_after_real_state_inspection(*args, **kwargs):
        result = original_inspect(*args, **kwargs)
        world.owner.revoke()
        return result

    monkeypatch.setattr(world.owner.state, 'inspect', revoke_after_real_state_inspection)
    world.access_revoked_cleanup = True
    with pytest.raises(InvocationAuthorityRefused):
        instance.stop(unit.identity, context)

    assert client._native_admission_open is True
    assert world.issuer._issued[id(context)][3:] == ['issued', False]
    assert world.issuer.verified_consumption(context) is False
    assert world.records.owner_read_termination(unit.identity['unitId'], 'stop') is None
    assert world.records.owner_read_termination(unit.identity['unitId'], 'release') is None
    assert instance.channel_factory.owned_record.process.observe().state == 'running'
    assert world.environment.snapshot.active_uses == 1
    monkeypatch.setattr(world.owner.state, 'inspect', original_inspect)


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_changed_generation_evidence_does_not_quiesce_or_open_termination(live_owner, monkeypatch):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    client = instance.channel_factory.owned_record.entry
    context = world.owner.authorize('stop', unit, authorization)
    original_inspect = world.owner.state.inspect
    world.access_revoked_cleanup = True

    def inspect_with_changed_generation(*args, **kwargs):
        state = original_inspect(*args, **kwargs)
        return replace(state, management_epoch=state.management_epoch + 1)

    monkeypatch.setattr(world.owner.state, 'inspect', inspect_with_changed_generation)
    with pytest.raises(InvocationAuthorityRefused):
        instance.stop(unit.identity, context)

    assert client._native_admission_open is True
    assert world.issuer._issued[id(context)][3:] == ['issued', False]
    assert world.issuer.verified_consumption(context) is False
    assert world.records.owner_read_termination(unit.identity['unitId'], 'stop') is None
    assert world.records.owner_read_termination(unit.identity['unitId'], 'release') is None
    assert instance.channel_factory.owned_record.process.observe().state == 'running'
    assert world.environment.snapshot.active_uses == 1
    monkeypatch.setattr(world.owner.state, 'inspect', original_inspect)


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_low_level_release_preflights_before_any_release_effect(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    stopped_context = world.owner.authorize('stop', unit, authorization)
    stopped = instance.stop(unit.identity, stopped_context)
    world.owner.complete('stop', unit, stopped_context, stopped)
    assert stopped['state'] == 'confirmed'

    release_context = world.owner.authorize('release', unit, authorization)
    client = instance.channel_factory.owned_record.entry
    assert client._native_admission_open is False
    with pytest.raises(InvocationAuthorityRefused):
        instance.release(unit.identity, object())
    assert world.records.owner_read_termination(unit.identity['unitId'], 'release') is None
    assert world.issuer.verified_consumption(release_context) is False
    assert client._native_admission_open is False
    assert world.environment.snapshot.active_uses == 1

    released = world.original_manager.release(unit.identity, release_context)
    world.owner.complete('release', unit, release_context, released)
    assert released['state'] == 'confirmed'
    assert world.records.owner_read_termination(unit.identity['unitId'], 'release')['state'] == 'confirmed'
    assert world.environment.snapshot.active_uses == 0
    assert world.public_manager.close(authorization)['state'] == 'confirmed'
