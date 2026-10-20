"""Generic dispatch: schema refusal before effects, unknown after a failure."""
from __future__ import annotations

import pytest

from ordessa_interfaces_contracts import CapabilityError, OperationResult
from ordessa_interfaces.system_access.discovery import DiscoveryError, load_capabilities, validate_bindings
from ordessa_interfaces.system_access.operations import RequestContext, invoke
from ordessa_interfaces.system_access.registry import build_registry

from host_fakes import FakeEntryPoint, FakeFactory, make_capability, refused


BINDINGS = {'services': object(), 'invocation_resolver': object()}


def test_input_schema_refuses_before_the_handler_runs():
    calls = []

    async def handler(request, context):
        calls.append(request)
        return OperationResult(status='completed', data={'value': request['value']})

    registry = build_registry([make_capability('demo', handler=handler)])
    context = RequestContext(principal={'principalId': 'p'}, request_id='r')

    import asyncio
    refused_result = asyncio.run(invoke(registry, 'demo.run', {'value': 'not-an-integer'}, context))
    assert refused_result.status == 'refused'
    assert refused_result.error.code == 'INVALID_INPUT'
    assert calls == []

    completed = asyncio.run(invoke(registry, 'demo.run', {'value': 3}, context))
    assert completed.status == 'completed' and completed.data == {'value': 3}
    assert len(calls) == 1


def test_handler_failure_and_invalid_result_are_unknown_not_refused():
    async def boom(request, context):
        raise RuntimeError('lost connection after write')

    async def bad_result(request, context):
        return {'status': 'completed'}

    async def refused_without_error(request, context):
        return OperationResult(status='refused')

    async def completed_with_error(request, context):
        return OperationResult(status='completed', error=CapabilityError(code='CONFLICT', message='x'))

    context = RequestContext(principal={'principalId': 'p'}, request_id='r')
    import asyncio
    for handler in (boom, bad_result, refused_without_error, completed_with_error):
        registry = build_registry([make_capability('demo', handler=handler)])
        result = asyncio.run(invoke(registry, 'demo.run', {'value': 1}, context))
        assert result.status == 'unknown'
        assert result.error.code == 'EFFECT_UNKNOWN'


def test_unknown_operation_is_refused_unsupported():
    registry = build_registry([make_capability('demo')])
    context = RequestContext(principal={'principalId': 'p'}, request_id='r')
    import asyncio
    result = asyncio.run(invoke(registry, 'demo.missing', {}, context))
    assert result.status == 'refused' and result.error.code == 'CAPABILITY_UNSUPPORTED'


def test_handler_refusal_passes_through_once():
    calls = []

    async def handler(request, context):
        calls.append(request)
        return refused('CONFLICT', 'same request already claimed')

    registry = build_registry([make_capability('demo', handler=handler)])
    context = RequestContext(principal={'principalId': 'p'}, request_id='r')
    import asyncio
    result = asyncio.run(invoke(registry, 'demo.run', {'value': 1}, context))
    assert result.status == 'refused' and result.error.code == 'CONFLICT'
    assert len(calls) == 1  # the dispatcher never retries


def test_malformed_entities_refuse_explicitly():
    with pytest.raises(DiscoveryError, match='mapping'):
        validate_bindings('not-a-mapping')
    with pytest.raises(DiscoveryError, match='missing'):
        validate_bindings({'services': object()})
    with pytest.raises(DiscoveryError, match='allowlist'):
        load_capabilities((), BINDINGS, entry_points=())
    with pytest.raises(DiscoveryError, match='not installed'):
        load_capabilities(('missing',), BINDINGS, entry_points=())
    with pytest.raises(DiscoveryError, match='build'):
        load_capabilities(('no-build',), BINDINGS,
                          entry_points=(FakeEntryPoint('no-build', object()),))


def test_module_attribute_entry_point_loads_under_the_allowlist():
    from types import SimpleNamespace
    entry = SimpleNamespace(name='modcap', module='host_fake_module', attr='factory')
    capabilities = load_capabilities(('modcap',), BINDINGS, entry_points=(entry,))
    assert capabilities[0].descriptor.id == 'modcap'


def test_allowlisted_factory_builds_once_and_receives_trusted_bindings():
    factory = FakeFactory(make_capability('demo', operation_ids=('demo.run',)))
    capabilities = load_capabilities(('demo',), BINDINGS,
                                     entry_points=(FakeEntryPoint('demo', factory),))
    assert factory.built == 1
    assert capabilities[0].descriptor.id == 'demo'
