"""Read-only preflight for the original invocation ticket."""
import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.admission.invocation import InvocationAuthorityRefused, InvocationIssuer

from test_local_owner import live_owner


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_admission_preflight_revalidates_without_changing_original_ticket_or_claim(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    context = world.owner.authorize('stop', unit, authorization)
    facts = context.facts
    request_ref = facts['request']
    request = RequestKey(request_ref['environmentNamespace'], request_ref['principalScope'],
                         request_ref['requestId'])
    claim_before = world.store.read_operation_step(request, facts['stepId'])
    assert claim_before is not None and claim_before.outcome == 'possibly-dispatched'
    registered = world.issuer._issued[id(context)]
    issued_before = (registered[0], registered[1], registered[2], registered[3], registered[4])
    terminations_before = tuple(world.records.owner_read_termination(unit.identity['unitId'], action)
                                for action in ('stop', 'release'))

    verified = world.verifier.verify_admission(
        context, 'stop', facts['providerRef'], facts['targetRef'], facts['inputDigest'])
    repeated = world.verifier.verify_admission(
        context, 'stop', facts['providerRef'], facts['targetRef'], facts['inputDigest'])

    assert verified == facts == repeated
    assert tuple(world.issuer._issued[id(context)]) == issued_before
    assert world.issuer.verified_consumption(context) is False
    assert world.store.read_operation_step(request, facts['stepId']) == claim_before
    assert tuple(world.records.owner_read_termination(unit.identity['unitId'], action)
                 for action in ('stop', 'release')) == terminations_before == (None, None)
    assert unit._instance.channel_factory.owned_record.process.observe().state == 'running'
    assert world.environment.snapshot.active_uses == 1

    stopped = unit._instance.stop(unit.identity, context)
    world.owner.complete('stop', unit, context, stopped)
    assert stopped['state'] == 'confirmed'
    assert world.public_manager.close(authorization)['state'] == 'confirmed'


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_admission_preflight_refuses_expired_or_copied_ticket_without_poisoning_original(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    context = world.owner.authorize('stop', unit, authorization)
    facts = context.facts
    registered = world.issuer._issued[id(context)]
    copied = __import__('copy').copy(context)
    client = unit._instance.channel_factory.owned_record.entry

    with pytest.raises(InvocationAuthorityRefused):
        unit._instance.stop(unit.identity, copied)
    assert world.issuer._issued[id(context)] is registered
    assert registered[3:] == ['issued', False]
    assert client._native_admission_open is True
    assert world.records.owner_read_termination(unit.identity['unitId'], 'stop') is None

    world.now[0] = world.permission.expires_at
    with pytest.raises(InvocationAuthorityRefused):
        unit._instance.stop(unit.identity, context)
    assert world.issuer._issued[id(context)] is registered
    assert registered[3:] == ['issued', False]
    assert world.issuer.verified_consumption(context) is False
    assert world.records.owner_read_termination(unit.identity['unitId'], 'stop') is None
    assert client._native_admission_open is True
    world.now[0] = 10.0
    stopped = unit._instance.stop(unit.identity, context)
    world.owner.complete('stop', unit, context, stopped)
    assert stopped['state'] == 'confirmed'
    assert world.public_manager.close(authorization)['state'] == 'confirmed'


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_admission_preflight_rejects_context_from_another_issuer(live_owner):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    context = world.owner.authorize('stop', unit, authorization)
    facts = context.facts
    other_issuer = InvocationIssuer(world.store, world.owner.authority, world.owner.state,
                                    clock=lambda: world.now[0])
    try:
        with pytest.raises(InvocationAuthorityRefused):
            other_issuer.verifier().verify_admission(
                context, 'stop', facts['providerRef'], facts['targetRef'], facts['inputDigest'])
        assert world.issuer._issued[id(context)][3:] == ['issued', False]
        assert world.issuer.verified_consumption(context) is False
    finally:
        other_issuer.close()
    stopped = unit._instance.stop(unit.identity, context)
    world.owner.complete('stop', unit, context, stopped)
    assert world.public_manager.close(authorization)['state'] == 'confirmed'
