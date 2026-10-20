"""Ctrl+C policy: a native cancel request is not an outcome.

A first interrupt during an active prompt sends the provider's session/cancel
notification and leaves the original call running. Only a second interrupt
stops waiting locally. Nothing here rewrites the original result as cancelled.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from ordessa_agent_tools.session import Interrupt, _prompt_instance_argument, _read_reference


REFERENCE = {'schemaVersion': 'agent-instance/1', 'namespace': 'local-test',
             'instanceId': 'instance-1', 'bindingDigest': 'sha256:' + 'a' * 64}


class Receipt:
    def __init__(self, state):
        self.state = state


class FakeInteractions:
    def __init__(self, *, state='accepted', error=None):
        self.calls = []
        self._state = state
        self._error = error

    async def cancel_session(self, instance_ref, *, request_id, invocation, write_guard, deadline):
        self.calls.append({'ref': instance_ref, 'request_id': request_id,
                           'guard': write_guard, 'deadline': deadline})
        if self._error is not None:
            raise self._error
        return Receipt(self._state)


class FakeAuthority:
    def authenticate(self, command):
        return {'kind': 'local-os-user', 'id': 'os-user:1000'}

    def resolve(self, context):
        return ('invocation', context.request_id)


class FakeOwner:
    def __init__(self, interactions):
        self.interactions = interactions


class FakeAgents:
    def __init__(self, interactions, authority):
        self.interactions = interactions
        self.authority = authority


class FakeEnvironment:
    def __init__(self, authority):
        self.authority = authority


class FakeSession:
    def __init__(self, interactions, authority):
        self.agents = FakeAgents(interactions, authority)
        self.environment = FakeEnvironment(authority)


class Stderr:
    def __init__(self):
        self.text = ''

    def write(self, value):
        self.text += value

    def flush(self):
        pass


def _state_file(tmp_path, document):
    path = tmp_path / 'start.json'
    path.write_text(json.dumps(document))
    return path


def test_prompt_instance_argument_reads_both_flag_forms():
    assert _prompt_instance_argument(
        ['agents', 'prompt', '--instance-ref', '/a.json#/data/instanceRef']) == '/a.json#/data/instanceRef'
    assert _prompt_instance_argument(
        ['agents', 'prompt', '--instance-ref=/a.json#/data/instanceRef']) == '/a.json#/data/instanceRef'
    assert _prompt_instance_argument(['agents', 'start', '--instance-ref', '/a.json']) is None
    assert _prompt_instance_argument(['environments', 'inspect', 'demo']) is None
    assert _prompt_instance_argument(['agents', 'prompt']) is None


def test_reference_reader_accepts_closed_projection(tmp_path):
    path = _state_file(tmp_path, {'data': {'instanceRef': REFERENCE}})
    reference = _read_reference(str(path) + '#/data/instanceRef')
    assert reference.projection() == REFERENCE


@pytest.mark.parametrize('argument', [
    'relative.json#/data/instanceRef',
    '/definitely/absent.json#/data/instanceRef',
])
def test_reference_reader_refuses_unsafe_paths(tmp_path, argument):
    with pytest.raises((ValueError, OSError)):
        _read_reference(argument)


def test_reference_reader_refuses_absent_pointer(tmp_path):
    path = _state_file(tmp_path, {'data': {}})
    with pytest.raises(ValueError):
        _read_reference(str(path) + '#/data/instanceRef')


def test_first_interrupt_sends_native_cancel_and_keeps_the_original_call(tmp_path):
    path = _state_file(tmp_path, {'data': {'instanceRef': REFERENCE}})

    async def scenario():
        interactions = FakeInteractions()
        session = FakeSession(interactions, FakeAuthority())
        stderr = Stderr()
        interrupt = Interrupt(session, stderr)
        victim = asyncio.create_task(asyncio.sleep(10))
        interrupt.task = victim
        interrupt.bind(['agents', 'prompt', '--instance-ref',
                        str(path) + '#/data/instanceRef'])
        interrupt.request()
        await asyncio.sleep(0)
        assert interrupt.native_attempted is True
        assert victim.cancelled() is False, 'the first interrupt must not stop the original call'
        victim.cancel()
        assert len(interactions.calls) == 1
        call = interactions.calls[0]
        assert call['ref'].projection() == REFERENCE
        assert call['request_id'].startswith('sigint-')
        assert 'cancel notification accepted' in stderr.text
        assert 'not rewritten' in stderr.text

    asyncio.run(scenario())


def test_second_interrupt_stops_waiting_locally(tmp_path):
    path = _state_file(tmp_path, {'data': {'instanceRef': REFERENCE}})

    async def scenario():
        interactions = FakeInteractions()
        session = FakeSession(interactions, FakeAuthority())
        interrupt = Interrupt(session, Stderr())
        victim = asyncio.create_task(asyncio.sleep(10))
        interrupt.task = victim
        interrupt.bind(['agents', 'prompt', '--instance-ref',
                        str(path) + '#/data/instanceRef'])
        interrupt.request()
        await asyncio.sleep(0)
        assert victim.cancelled() is False
        interrupt.request()
        await asyncio.sleep(0)
        return victim

    assert asyncio.run(scenario()).cancelled() is True


def test_interrupt_outside_a_prompt_cancels_the_local_task_immediately():
    async def scenario():
        session = FakeSession(FakeInteractions(), FakeAuthority())
        interrupt = Interrupt(session, Stderr())
        victim = asyncio.create_task(asyncio.sleep(10))
        interrupt.task = victim
        interrupt.bind(['environments', 'exec', 'demo', '--', '/bin/true'])
        interrupt.request()
        await asyncio.sleep(0)
        return victim

    assert asyncio.run(scenario()).cancelled() is True


def test_failed_native_cancel_is_reported_honestly(tmp_path):
    path = _state_file(tmp_path, {'data': {'instanceRef': REFERENCE}})

    async def scenario():
        interactions = FakeInteractions(error=RuntimeError('endpoint gone'))
        session = FakeSession(interactions, FakeAuthority())
        stderr = Stderr()
        interrupt = Interrupt(session, stderr)
        interrupt.task = asyncio.current_task()
        interrupt.bind(['agents', 'prompt', '--instance-ref',
                        str(path) + '#/data/instanceRef'])
        interrupt.request()
        await asyncio.sleep(0)
        assert 'native cancel was not sent' in stderr.text
        assert 'original prompt still owns its result' in stderr.text

    asyncio.run(scenario())
