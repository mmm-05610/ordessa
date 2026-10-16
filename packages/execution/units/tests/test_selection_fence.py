"""Live selection fences on the original LocalUnitOwner and Unit records."""
import threading
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest_plugins = ('test_local_owner',)


PEER_WAIT_FOR_RESPONSE = r'''
import json, os, sys, time
session_id='selection-fence-session'
for line in sys.stdin:
    request=json.loads(line); method=request['method']; params=request.get('params',{})
    if method=='initialize': result={'protocolVersion':1,'agentCapabilities':{'loadSession':True}}
    elif method=='session/new': result={'sessionId':session_id,'configOptions':[]}
    elif method=='session/load': result={}
    elif method=='_ordessa/session/configuration': result={'sessionId':session_id,'configOptions':[]}
    elif method=='session/prompt':
        while not os.path.exists(os.path.join(os.getcwd(),'.selection-response')): time.sleep(.005)
        result={'stopReason':'end_turn','observedPrompt':params.get('prompt')}
    elif method=='session/cancel': continue
    else: result={}
    print(json.dumps({'jsonrpc':'2.0','id':request.get('id'),'result':result}),flush=True)
'''


_SELECTION_HOLDER = {}


@asynccontextmanager
async def _selection_effect_acquire(_identity, _deadline):
    holder = _SELECTION_HOLDER
    assert holder['caller_guard'] is False
    with holder['services'].guard_unit_selection(**holder['selection']):
        holder['entered'] = True
        holder['thread'] = threading.get_ident()
        try:
            yield
        finally:
            holder['released'] = True
            holder['released_event'].set()


def _selection_effect_factory(unit_ref, operation_ref, input_digest, params):
    from ordessa_execution_agents.harness.transport import EffectWriteGuard
    return EffectWriteGuard(unit_ref, operation_ref, input_digest, params, _selection_effect_acquire)


@pytest.mark.parametrize('live_owner', [{
    'acp_turn_opt_in': True,
    'effect_write_guard_factory': _selection_effect_factory,
    'preparation_peer': PEER_WAIT_FOR_RESPONSE,
}], indirect=True)
def test_local_owner_selection_guards_commit_spans_and_sdk_thread_write(live_owner):
    from ordessa_infrastructure.identifiers import RequestKey
    from ordessa_units.public import unit_services

    # The fixed factory is installed by the real LocalUnitOwner before Unit
    # creation. Its acquire callback receives the actual SDK-loop write and
    # enters the same live-source guard there, never under a caller-held guard.
    holder = _SELECTION_HOLDER
    holder.clear()
    holder.update(caller_guard=False, entered=False, released=False,
                  write_event=threading.Event(), released_event=threading.Event())
    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    instance = world.owner.native_unit(unit, world.owner.authorization())
    services = unit_services(world.admission, owner_ports=world.owner._ports)
    prompt = [{'type': 'text', 'text': 'selection fence bounded write'}]
    session_id = instance.projection.read_session(unit.identity).native_facts['sessionId']
    params = {'sessionId': session_id, 'prompt': prompt}
    prompt_digest = instance.records.acp_prompt_input_digest(unit.identity, params)
    invocation = world.owner.authorize_acp_turn_query(
        world.owner.authorization(), RequestKey('env', world.permission.principal_scope, 'selection-query'),
        unit.identity, 'selection-turn', expected_prompt_input_digest=prompt_digest,
    )
    holder['services'] = services
    holder['selection'] = {'unit_ref': unit.identity,
        'expected_profile_revision': world.permission.profile_revision,
        'query_invocation': invocation,
        'query_input_digest': invocation.facts['inputDigest'], 'require_live': True}
    process = instance.channel_factory.owned_record.process
    original_write = process.write_stdin
    async def observed_write(data, *, timeout=None):
        assert holder['entered'] and not holder['released']
        holder['write_event'].set()
        return await original_write(data, timeout=timeout)
    process.write_stdin = observed_write

    # Engineering's two caller-thread COMMIT contexts are separate guards.
    # Each must refuse a close while its own exact original selection is held.
    for _commit in (1, 2):
        holder['caller_guard'] = True
        with services.guard_unit_selection(**holder['selection']):
            pending = unit.close(world.owner.authorization())
            assert pending['state'] == 'pending' and pending['unresolved'] is True
            assert world.records.owner_read_termination(unit.identity['unitId'], 'stop') is None
            assert world.environment.snapshot.active_uses == 1
            assert instance.channel_factory.owned_record.process.observe().state == 'running'
        holder['caller_guard'] = False

    # The actual SDK effect guard acquires permission/source on its loop
    # thread for the bounded write. No caller-thread permission guard remains
    # held while prompt_recorded waits for the peer response.
    cwd = Path(instance.prepared_agent.harness.launch_spec.cwd)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(instance.prompt_recorded, unit.identity,
            instance.lease_port.grant(unit.identity), operation_ref='selection-turn',
            timeout=5, prompt=prompt)
        assert holder['write_event'].wait(2)
        assert holder['released_event'].wait(2)
        assert not pending.done()  # Native response wait starts after the write guard exits.
        (cwd / '.selection-response').touch()
        result = pending.result(timeout=7)
    assert result['state'] == 'completed'
    assert result['inputDigest'] == prompt_digest
    assert holder['entered'] and holder['released']
    assert holder['thread'] != threading.get_ident()

    assert world.environment.snapshot.active_uses == 1
    assert world.environment.snapshot.observation.state == 'running'
    assert instance.channel_factory.owned_record.process.observe().state == 'running'
    assert unit.close(world.owner.authorization())['state'] == 'confirmed'
    assert world.environment.snapshot.active_uses == 0
    assert world.environment.snapshot.observation.state == 'running'


@pytest.mark.parametrize('live_owner', [{'acp_turn_opt_in': True}], indirect=True)
@pytest.mark.parametrize('denial', ['expired', 'revoked'])
def test_live_selection_revalidates_original_permission_without_installing_fence(live_owner, denial):
    from ordessa_infrastructure.identifiers import RequestKey
    from ordessa_units.admission.invocation import InvocationAuthorityRefused
    from ordessa_interfaces.system_access.contracts.transport import AccessError
    from ordessa_units.public import unit_services

    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    instance = world.owner.native_unit(unit, world.owner.authorization())
    services = unit_services(world.admission, owner_ports=world.owner._ports)
    prompt = [{'type': 'text', 'text': 'bounded selection authorization check'}]
    session_id = instance.projection.read_session(unit.identity).native_facts['sessionId']
    params = {'sessionId': session_id, 'prompt': prompt}
    prompt_digest = instance.records.acp_prompt_input_digest(unit.identity, params)
    invocation = world.owner.authorize_acp_turn_query(
        world.owner.authorization(), RequestKey('env', world.permission.principal_scope, 'selection-auth-query'),
        unit.identity, 'selection-auth-turn', expected_prompt_input_digest=prompt_digest,
    )

    if denial == 'expired':
        world.now[0] = world.permission.expires_at + 1
        error = InvocationAuthorityRefused
    else:
        world.access.revoke()
        world.access_revoked_cleanup = True
        error = AccessError
    with pytest.raises(error):
        with services.guard_unit_selection(unit.identity,
                expected_profile_revision=world.permission.profile_revision,
                query_invocation=invocation,
                query_input_digest=invocation.facts['inputDigest'], require_live=True):
            pytest.fail('denied permission entered live selection fence')

    assert instance.try_quiesce() is True
    assert world.records.owner_read_termination(unit.identity['unitId'], 'stop') is None
    assert instance.channel_factory.owned_record.process.observe().state == 'running'
