"""Public prompt, durable-record and Unit lifecycle boundary checks."""
import pytest
import json

from test_public_unit_api import public_units
from ordessa_units.api import UnitApiRefused, UnitReconnectUnavailable
from ordessa_units.records import UnitRecordsRefused


def _stored_turns(records, unit_id):
    with records.journal._connect() as db:
        return tuple((operation_ref, state, json.loads(body_json)) for operation_ref, state, body_json in
            db.execute('SELECT operation_ref,state,body_json FROM harness_acp_turn_attempts WHERE unit_ref=?',
                (unit_id,)).fetchall())


def test_public_prompt_and_request_share_the_durable_native_path(public_units):
    world = public_units
    unit = world.manager.create(world.spec, world.authorization('normal-prompt'))
    interaction = unit.interaction(world.authorization('normal-prompt'))

    response = interaction.prompt({
        'prompt': [{'type': 'text', 'text': 'first normal prompt'}], 'timeout': 2,
    })
    assert response['observedConfiguration'] == {'marker': 'public-unit-profile'}
    first = _stored_turns(world.records, unit.identity['unitId'])
    assert len(first) == 1
    assert first[0][0].startswith('unit-prompt/')
    assert first[0][1] == first[0][2]['state'] == 'completed'
    assert first[0][2]['response']['result'] == response

    second_response = interaction.request('session/prompt', {
        'prompt': [{'type': 'text', 'text': 'second normal prompt'}],
    }, timeout=2)
    turns = _stored_turns(world.records, unit.identity['unitId'])
    assert len(turns) == 2
    assert turns[0][0] != turns[1][0]
    assert turns[1][2]['response']['result'] == second_response
    assert unit.close(world.authorization('close-normal-prompt'))['state'] == 'confirmed'
    assert world.environments.instance.snapshot.active_uses == 0
    assert world.environments.instance.snapshot.observation.state == 'running'


def test_public_prompt_preserves_native_timeout_payload_separately_from_wait_control(public_units):
    world = public_units
    unit = world.manager.create(world.spec, world.authorization('native-timeout'))
    interaction = unit.interaction(world.authorization('native-timeout'))

    interaction.prompt({'prompt': [{'type': 'text', 'text': 'native timeout field'}], 'timeout': 17}, timeout=2)

    turns = _stored_turns(world.records, unit.identity['unitId'])
    assert len(turns) == 1
    assert turns[0][2]['request']['raw']['params']['timeout'] == 17
    assert unit.close(world.authorization('close-native-timeout'))['state'] == 'confirmed'


def test_public_prompt_accepts_stable_operation_ref_without_native_param_or_replay(public_units):
    world = public_units
    unit = world.manager.create(world.spec, world.authorization('stable-operation-ref'))
    interaction = unit.interaction(world.authorization('stable-operation-ref'))
    operation_ref = 'library-work/attempt-7'
    params = {'prompt': [{'type': 'text', 'text': 'stable prompt'}]}

    response = interaction.prompt(params, timeout=2, operation_ref=operation_ref)
    assert response['observedConfiguration'] == {'marker': 'public-unit-profile'}
    turns = _stored_turns(world.records, unit.identity['unitId'])
    assert len(turns) == 1
    assert turns[0][0] == operation_ref
    assert turns[0][1] == turns[0][2]['state'] == 'completed'
    assert turns[0][2]['input']['params']['prompt'] == params['prompt']
    assert 'operationRef' not in turns[0][2]['input']['params']
    assert turns[0][2]['request']['raw']['params'] == turns[0][2]['input']['params']

    # The original Records reserve fence rejects both exact duplicates and
    # content conflicts before any second native dispatch.
    with pytest.raises(UnitApiRefused, match='already exists') as exact_replay:
        interaction.prompt(params, timeout=2, operation_ref=operation_ref)
    assert isinstance(exact_replay.value.__cause__, UnitRecordsRefused)
    changed = {'prompt': [{'type': 'text', 'text': 'different content'}]}
    with pytest.raises(UnitApiRefused, match='already exists') as conflicting_replay:
        interaction.prompt(changed, timeout=2, operation_ref=operation_ref)
    assert isinstance(conflicting_replay.value.__cause__, UnitRecordsRefused)
    assert len(_stored_turns(world.records, unit.identity['unitId'])) == 1
    assert unit.close(world.authorization('close-stable-operation-ref'))['state'] == 'confirmed'


def test_unknown_stable_operation_ref_is_not_retried_with_new_dispatch(public_units, monkeypatch):
    from ordessa_units.sessions import prompt as prompt_module

    world = public_units
    unit = world.manager.create(world.spec, world.authorization('unknown-operation-ref'))
    interaction = unit.interaction(world.authorization('unknown-operation-ref'))
    operation_ref = 'library-work/attempt-unknown'
    original_finish = prompt_module.acp_turns.finish

    def fail_completed_finish(records, ref, state, response=None):
        if state == 'completed':
            raise RuntimeError('controlled failure while sealing completed receipt')
        return original_finish(records, ref, state, response)

    monkeypatch.setattr(prompt_module.acp_turns, 'finish', fail_completed_finish)
    params = {'prompt': [{'type': 'text', 'text': 'one uncertain prompt'}]}
    with pytest.raises(RuntimeError, match='controlled failure'):
        interaction.prompt(params, timeout=2, operation_ref=operation_ref)

    turns = _stored_turns(world.records, unit.identity['unitId'])
    assert len(turns) == 1
    assert turns[0][0] == operation_ref
    assert turns[0][1] == turns[0][2]['state'] == 'unknown'
    assert turns[0][2]['request'] is not None
    assert 'operationRef' not in turns[0][2]['input']['params']

    with pytest.raises(UnitApiRefused, match='already exists') as unknown_replay:
        interaction.prompt(params, timeout=2, operation_ref=operation_ref)
    assert isinstance(unknown_replay.value.__cause__, UnitRecordsRefused)
    assert len(_stored_turns(world.records, unit.identity['unitId'])) == 1
    assert unit.close(world.authorization('close-unknown-operation-ref'))['state'] == 'confirmed'


def test_cancel_and_disconnect_do_not_stop_or_release_unit_or_enable_reconnect(public_units):
    world = public_units
    unit = world.manager.create(world.spec, world.authorization('lifecycle'))
    interaction = unit.interaction(world.authorization('lifecycle'))
    interaction.cancel()
    interaction.disconnect()

    with pytest.raises(UnitReconnectUnavailable):
        interaction.request('session/prompt', {'prompt': []})
    with pytest.raises(UnitReconnectUnavailable):
        unit.interaction(world.authorization('reconnect'))
    record = world.instances[0].channel_factory.owned_record
    assert record.process.observe().state == 'running'
    assert world.records.owner_read_session(unit.identity['unitId']).state == 'confirmed'
    assert world.environments.instance.snapshot.active_uses == 1
    assert unit.close(world.authorization('close-after-disconnect'))['state'] == 'confirmed'
    assert world.environments.instance.snapshot.active_uses == 0
    shared = world.environments.instance.acquire('after-unit-close', sharing=True)
    assert shared.release()['resourcePreserved'] is True


@pytest.mark.parametrize('public_units', [False], indirect=True)
def test_prompt_refuses_when_original_durable_record_opt_in_is_missing(public_units):
    world = public_units
    unit = world.manager.create(world.spec, world.authorization('no-opt-in'))
    interaction = unit.interaction(world.authorization('no-opt-in'))
    with pytest.raises(UnitApiRefused, match='durable-record opt-in'):
        interaction.prompt({'prompt': [{'type': 'text', 'text': 'no unrecorded fallback'}]})
    assert world.records.owner_read_session(unit.identity['unitId']).state == 'confirmed'
    assert unit.close(world.authorization('close-no-opt-in'))['state'] == 'confirmed'


def test_prompt_refuses_when_canonical_effect_guard_has_no_engineering_binding(public_units):
    world = public_units
    unit = world.manager.create(world.spec, world.authorization('guarded'))
    instance = world.instances[-1]
    guard = lambda *_args: object()
    instance._effect_write_guard_factory = guard
    instance._fixed_effect_write_guard_factory = guard
    interaction = unit.interaction(world.authorization('guarded'))
    with pytest.raises(UnitApiRefused, match='original Engineering binding'):
        interaction.prompt({'prompt': [{'type': 'text', 'text': 'remain refused'}]})
    assert _stored_turns(world.records, unit.identity['unitId']) == ()
    assert unit.close(world.authorization('close-guarded'))['state'] == 'confirmed'
