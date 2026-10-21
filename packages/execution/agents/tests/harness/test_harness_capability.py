"""Unit coverage for the read-only ``agents.harness`` capability (GAP-G2).

The capability projects an explicitly pinned ``HarnessCatalog``. It must never
claim admission from PATH, launch a process, write files or open a session, and
it must refuse rather than report an empty catalog as successful.

The tests use fake providers that satisfy the pinned provider protocol and only
record calls: no Harness distribution has to be installed and no network is
needed. Dispatch goes through the real generic ``CapabilityHost`` so input
schema enforcement is exercised as well.
"""
import asyncio
import os
import subprocess

import pytest

from ordessa_agents.capability.harness import (
    CAPABILITY_ID,
    build_harness_capability,
    descriptor,
)
from ordessa_agents.harness.providers.catalog import HarnessCatalog
from ordessa_agents.sdk.harness import HarnessDescriptor, HarnessError
from ordessa_interfaces_contracts import (
    canonical_json,
    compute_descriptor_digest,
    validate_capability,
    validate_result,
)
from ordessa_interfaces.system_access import (
    CapabilityHost,
    RequestContext,
    build_registry,
)

NAMESPACE = 'gap-g2'
LIST = CAPABILITY_ID + '.list'
DESCRIBE = CAPABILITY_ID + '.describe'


def _descriptor(provider_id, definition_id=None, *, revision='1',
                protocol_id='acp/v1', implementation_digest='sha256:' + 'a' * 64):
    return HarnessDescriptor(
        provider_id,
        {'environmentNamespace': NAMESPACE,
         'definitionId': provider_id if definition_id is None else definition_id,
         'revision': revision},
        implementation_digest,
        protocol_id,
        ('config', 'workspace'),
        ('model',),
    )


def _pin(descriptor):
    return dict(descriptor.definition_ref)


class FakeProvider:
    """Pinned provider stand-in; only implements the required callable port."""

    def __init__(self, provider_id, *, definition_id=None, revision='1', protocol_id='acp/v1'):
        self.descriptor = _descriptor(provider_id, definition_id, revision=revision,
                                      protocol_id=protocol_id)
        self.calls = {'validate_profile': 0, 'prepare': 0, 'open_session': 0}

    def validate_profile(self, content):
        self.calls['validate_profile'] += 1
        raise AssertionError('capability must not validate a Profile')

    def prepare(self, content, context):
        self.calls['prepare'] += 1
        raise AssertionError('capability must not prepare a Profile')

    def open_session(self, process, context):
        self.calls['open_session'] += 1
        raise AssertionError('capability must not open a session')


def _host(capability):
    return CapabilityHost(build_registry([capability]), (CAPABILITY_ID,))


def _call(host, operation, request=None):
    context = RequestContext({'id': 'gap-g2-test'}, operation.rsplit('.', 1)[-1] + '-request')
    return asyncio.run(host.call(operation, request or {}, context))


def _list(capability):
    return _call(_host(capability), LIST)


def _describe(capability, pin):
    return _call(_host(capability), DESCRIBE, {'definitionRef': pin})


def _assert_refused_unsupported(result, message):
    assert result.status == 'refused'
    assert result.error is not None
    assert result.error.code == 'CAPABILITY_UNSUPPORTED'
    assert result.error.message == message
    validate_result(result)


# --- descriptor shape -------------------------------------------------------

def test_descriptor_operations_are_stable_and_owned_by_the_capability():
    first, second = descriptor(), descriptor()
    assert first == second
    assert first.id == CAPABILITY_ID == 'agents.harness'
    assert first.version == 'harness-catalog/1'
    assert tuple(operation.id for operation in first.operations) == (LIST, DESCRIBE)
    assert first.descriptor_digest.startswith('sha256:')
    assert first.descriptor_digest == compute_descriptor_digest(first)

    listed, described = first.operations
    assert listed.input_schema == {
        'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
    assert described.input_schema == {
        'type': 'object', 'required': ['definitionRef'], 'additionalProperties': False,
        'properties': {'definitionRef': {'type': 'object'}}}
    for operation in first.operations:
        assert operation.output_schema == {'type': 'object'}
        assert operation.scopes == ()
        assert operation.cli['command'] == 'agents harness'

    assert listed.cli == {'command': 'agents harness', 'operation': 'list', 'args': ()}
    assert described.cli['operation'] == 'describe'
    assert described.cli['args'] == (
        {'name': 'definitionRef', 'flags': ('--definition-ref',), 'type': 'json-file'},)


def test_built_capability_publishes_exactly_the_declared_operations():
    capability = build_harness_capability(HarnessCatalog([]))
    published = validate_capability(capability)
    assert published == descriptor()
    assert set(capability.handlers) == {LIST, DESCRIBE}
    assert all(callable(handler) for handler in capability.handlers.values())


def test_list_accepts_empty_input_and_describe_requires_definition_ref():
    capability = build_harness_capability(HarnessCatalog([FakeProvider('brand-a')]))
    host = _host(capability)
    assert _call(host, LIST).status == 'completed'

    unknown_key = _call(host, LIST, {'unexpected': True})
    assert unknown_key.status == 'refused'
    assert unknown_key.error.code == 'INVALID_INPUT'
    assert unknown_key.error.message == 'request does not match the declared input schema'

    missing = _call(host, DESCRIBE, {})
    assert missing.status == 'refused'
    assert missing.error.code == 'INVALID_INPUT'

    wrong_shape = _call(host, DESCRIBE, {'definitionRef': 'not-a-pin'})
    assert wrong_shape.status == 'refused'
    assert wrong_shape.error.code == 'INVALID_INPUT'


# --- construction guard -----------------------------------------------------

@pytest.mark.parametrize('catalog', [None, object(), {}, [], 'catalog', HarnessCatalog])
def test_build_requires_the_original_pinned_catalog_type(catalog):
    with pytest.raises(TypeError, match='HarnessCatalog'):
        build_harness_capability(catalog)


def test_build_rejects_a_catalog_subclass_by_exact_type():
    class DerivedCatalog(HarnessCatalog):
        pass

    with pytest.raises(TypeError, match='HarnessCatalog'):
        build_harness_capability(DerivedCatalog([]))


# --- listing ----------------------------------------------------------------

def test_empty_catalog_refuses_instead_of_reporting_an_empty_success():
    result = _list(build_harness_capability(HarnessCatalog([])))
    _assert_refused_unsupported(result, 'no harness provider is installed')
    assert result.data is not None
    assert result.data['harnesses'] == []
    assert result.data['notAdmitted'] == []


def test_list_projects_every_pinned_descriptor_without_launching_anything():
    first = FakeProvider('brand-a')
    second = FakeProvider('brand-b', revision='2', protocol_id=None)
    capability = build_harness_capability(HarnessCatalog([first, second]))

    result = _list(capability)
    assert result.status == 'completed'
    validate_result(result)
    harnesses = result.data['harnesses']
    assert harnesses == [first.descriptor.projection(), second.descriptor.projection()]
    assert result.data['notAdmitted'] == []

    projected = harnesses[0]
    assert set(projected) == {
        'schemaVersion', 'providerId', 'definitionRef', 'implementationDigest',
        'protocolId', 'requiredRoots', 'configurationKinds'}
    assert projected == {
        'schemaVersion': 'harness-descriptor/1',
        'providerId': 'brand-a',
        'definitionRef': {'environmentNamespace': NAMESPACE,
                          'definitionId': 'brand-a', 'revision': '1'},
        'implementationDigest': 'sha256:' + 'a' * 64,
        'protocolId': 'acp/v1',
        'requiredRoots': ['config', 'workspace'],
        'configurationKinds': ['model'],
    }
    assert harnesses[1]['protocolId'] is None
    assert harnesses[1]['definitionRef']['revision'] == '2'
    assert canonical_json(result.data)

    assert first.calls == {'validate_profile': 0, 'prepare': 0, 'open_session': 0}
    assert second.calls == {'validate_profile': 0, 'prepare': 0, 'open_session': 0}


def test_list_result_is_detached_from_the_pinned_descriptor():
    provider = FakeProvider('brand-a')
    capability = build_harness_capability(HarnessCatalog([provider]))
    harnesses = _list(capability).data['harnesses']
    harnesses[0]['definitionRef']['revision'] = 'forged'
    harnesses[0]['providerId'] = 'forged'
    assert _list(capability).data['harnesses'] == [provider.descriptor.projection()]
    assert provider.descriptor.definition_ref['revision'] == '1'


# --- describe ---------------------------------------------------------------

def test_describe_resolves_a_listed_pin_to_the_same_projection():
    providers = [FakeProvider('brand-a'), FakeProvider('brand-b', revision='2')]
    capability = build_harness_capability(HarnessCatalog(providers))
    listed = _list(capability).data['harnesses']
    assert len(listed) == 2

    for projection in listed:
        result = _describe(capability, projection['definitionRef'])
        assert result.status == 'completed'
        validate_result(result)
        assert result.data['harness'] == projection


def test_describe_unknown_pin_is_capability_unsupported():
    capability = build_harness_capability(HarnessCatalog([FakeProvider('brand-a')]))
    for pin in (
        {'environmentNamespace': NAMESPACE, 'definitionId': 'brand-z', 'revision': '1'},
        {'environmentNamespace': 'other', 'definitionId': 'brand-a', 'revision': '1'},
        {'environmentNamespace': NAMESPACE, 'definitionId': 'brand-a', 'revision': '9'},
        {},
    ):
        _assert_refused_unsupported(_describe(capability, pin), 'harness pin is not installed')


# --- zero side effects ------------------------------------------------------

def test_list_and_describe_have_no_process_or_session_side_effects(monkeypatch):
    provider = FakeProvider('brand-a')
    capability = build_harness_capability(HarnessCatalog([provider]))

    def forbidden(*_args, **_kwargs):
        raise AssertionError('agents.harness must not launch a process')

    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(os, 'posix_spawn', forbidden)
    if hasattr(os, 'fork'):
        monkeypatch.setattr(os, 'fork', forbidden)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)

    listed = _list(capability)
    described = _describe(capability, listed.data['harnesses'][0]['definitionRef'])
    assert listed.status == 'completed'
    assert described.status == 'completed'
    assert provider.calls == {'validate_profile': 0, 'prepare': 0, 'open_session': 0}


# --- catalog failures -------------------------------------------------------

def test_catalog_error_is_reported_as_unsupported_instead_of_escaping():
    provider = FakeProvider('brand-a')
    catalog = HarnessCatalog([provider])
    # A pin that changes after construction is a real catalog failure, not a
    # fake injected exception: descriptors() re-resolves the current pin.
    provider.descriptor = _descriptor('brand-a', revision='2')
    with pytest.raises(HarnessError) as raised:
        catalog.descriptors()
    assert raised.value.code == 'HARNESS_UNAVAILABLE'

    _assert_refused_unsupported(
        _list(build_harness_capability(catalog)),
        'installed harness catalog is unavailable')


# --- admission reporting (current implementation) ---------------------------

def test_admission_failures_are_reported_without_claiming_success():
    capability = build_harness_capability(
        HarnessCatalog([]), admission={'brand-z': 'not admitted by the harness allowlist'})
    result = _list(capability)
    _assert_refused_unsupported(result, 'no harness provider is admitted')
    assert result.data['harnesses'] == []
    assert result.data['notAdmitted'] == [
        {'definitionId': 'brand-z', 'reason': 'not admitted by the harness allowlist'}]


def test_admission_failures_accompany_a_successful_list():
    provider = FakeProvider('brand-a')
    capability = build_harness_capability(
        HarnessCatalog([provider]),
        admission={'brand-z': 'allowlisted provider is not installed',
                   'brand-y': 'implementation module unavailable'})
    result = _list(capability)
    assert result.status == 'completed'
    assert result.data['harnesses'] == [provider.descriptor.projection()]
    assert result.data['notAdmitted'] == [
        {'definitionId': 'brand-y', 'reason': 'implementation module unavailable'},
        {'definitionId': 'brand-z', 'reason': 'allowlisted provider is not installed'}]


def test_absent_admission_is_an_empty_reported_list():
    provider = FakeProvider('brand-a')
    for admission in (None, {}):
        result = _list(build_harness_capability(HarnessCatalog([provider]), admission=admission))
        assert result.status == 'completed'
        assert result.data['notAdmitted'] == []
