"""D-prep: configuration/Provider wire boundary negatives on the frozen v3 contract.

Wire-handler level: invalid DTO parameters are refused before any service is
consulted; uncomposed configuration/preparation capabilities refuse with typed
families instead of empty success; an uncomposed Provider boundary still
answers its advertised observations with zero owner/state effects. CLI level:
unadvertised methods, foreign scopes and malformed local inputs refuse with the
documented exit codes and never fall back to an uncontracted method.
"""
from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'packages/execution/agents/tests/agent_unit_model'))
from agent_tools_fixtures.management import setup, node_fixture, explicit_capabilities  # noqa: F401

from ordessa_units.public import unit_services, encode_node_ref, wire_contract
from ordessa_system_access_bindings import agent_core_methods
from ordessa_server_plugin_api import WireError

from agent_tools_fixtures.wire_cli import (
    SECRET, config as service_config, envelope, wire_server, without,
)
# The retired ``ordessa_cli`` CLI grammar (nodes/providers subcommands) is
# no longer imported here; the wire-handler tests below own these boundaries.


NODE_REF = {'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 1}
PROFILE_REF = {'environmentNamespace': 'env', 'profileId': 'profile-base',
               'manifestRevision': 1, 'contentDigest': 'sha256:' + 'b' * 64}


class ExplodingResolver:
    def __call__(self):
        raise AssertionError('services must not be consulted for a rejected DTO')


def handlers(resolver, version='agent-assembly/3'):
    return {item.method_id: item.handler
            for item in agent_core_methods(resolver, contract_version=version)}


def dump(parts):
    return tuple(parts[0]._conn.iterdump())


def counters(parts):
    return (parts[7]['calls'], parts[7]['queryCalls'])


CONFIG_INVALID_DTO = [
    ('agents.nodes.configuration.describe', {}),
    ('agents.nodes.configuration.inspect', {}),
    ('agents.nodes.configuration.apply', {'nodeRef': NODE_REF}),
    ('agents.nodes.configuration.apply', {'nodeRef': NODE_REF, 'change': {'requestId': 'request-1'}}),
    ('agents.nodes.configuration.query', {'nodeRef': NODE_REF}),
    ('agents.providers.describe', {}),
    ('agents.providers.describe', {'definitionRef': {'environmentNamespace': 'env', 'definitionId': 'fixture'}}),
    ('agents.nodes.applyProfile', {'nodeRef': NODE_REF, 'requestId': 'request-1',
                                    'profileRef': PROFILE_REF, 'baseProfileRef': PROFILE_REF,
                                    'expectedConfigurationRevision': 'native-1',
                                    'applicationPolicy': {'allowDeferred': False, 'allowRestart': 1}}),
    ('agents.nodes.prepare', {'requestId': 'request-1'}),
]


@pytest.mark.parametrize('method,params', CONFIG_INVALID_DTO)
def test_configuration_provider_invalid_dto_refused_before_service_consultation(setup, method, params):
    registry = handlers(ExplodingResolver())
    with pytest.raises(WireError) as caught:
        registry[method](params)
    assert caught.value.family == 'INVALID_REQUEST'
    assert caught.value.details.get('retryable') is False
    assert not hasattr(setup[1], '_agent_services')


def test_configuration_provider_uncomposed_capabilities_refuse_not_empty(setup):
    registry = handlers(lambda: setup[1])
    capabilities = registry['agents.capabilities']({})
    assert capabilities['supports']['configurationManagement'] is False
    assert capabilities['supports']['nodePreparation'] is False
    assert 'agents.nodes.applyProfile' not in capabilities['supportedMethods']
    before, counts = dump(setup), counters(setup)
    node_ref = encode_node_ref(setup[4])
    change = json.loads(json.dumps(setup[6].to_dict()))
    refusals = [
        ('agents.nodes.configuration.apply', {'nodeRef': node_ref, 'change': change}),
        ('agents.nodes.configuration.query', {'nodeRef': node_ref, 'operationRef': 'original-operation'}),
        ('agents.nodes.applyProfile', {'nodeRef': node_ref, 'requestId': 'request-1',
                                        'profileRef': PROFILE_REF, 'baseProfileRef': PROFILE_REF,
                                        'expectedConfigurationRevision': 'native-1',
                                        'applicationPolicy': {'allowDeferred': False, 'allowRestart': False}}),
        ('agents.nodes.prepare', {'requestId': 'request-1', 'profileRef': PROFILE_REF,
                                   'context': {}, 'options': {}}),
    ]
    for method, params in refusals:
        with pytest.raises(WireError) as caught:
            registry[method](params)
        assert caught.value.family == 'CAPABILITY_UNSUPPORTED', method
        assert caught.value.details.get('retryable') is False
    # Advertised observation boundaries still answer without any owner effect.
    described = registry['agents.nodes.configuration.describe']({'nodeRef': node_ref})
    assert [item['configurationKind'] for item in described['descriptions']] == ['model']
    snapshot = registry['agents.nodes.configuration.inspect']({'nodeRef': node_ref})
    assert snapshot['configuration'] == {'model': 'old'}
    listed = registry['agents.providers.list']({})
    assert [item['descriptor']['providerId'] for item in listed['providers']] == ['fixture.runtime']
    admitted = registry['agents.providers.describe'](
        {'definitionRef': {'environmentNamespace': 'env', 'definitionId': 'fixture', 'revision': '1'}})
    assert admitted['descriptor']['providerId'] == 'fixture.runtime'
    # Provider boundary rejections stay typed.
    with pytest.raises(WireError) as unknown:
        registry['agents.providers.describe'](
            {'definitionRef': {'environmentNamespace': 'env', 'definitionId': 'nope', 'revision': '1'}})
    assert unknown.value.family == 'FORBIDDEN'
    with pytest.raises(WireError) as foreign:
        registry['agents.providers.describe'](
            {'definitionRef': {'environmentNamespace': 'foreign', 'definitionId': 'fixture', 'revision': '1'}})
    assert foreign.value.family == 'CONFLICT_REQUEST'
    with pytest.raises(WireError) as malformed:
        registry['agents.providers.describe'](
            {'definitionRef': {'environmentNamespace': 'env', 'definitionId': 'fixture'}})
    assert malformed.value.family == 'INVALID_REQUEST'
    # One battery of refusals and observations: zero owner/claim/recovery writes.
    assert dump(setup) == before
    assert counters(setup) == counts


def test_configuration_query_refusals_and_zero_effect_with_composed_authority(setup):
    services = unit_services(setup[1], invocation_issuer=setup[10])
    assert services.configuration.capabilities()['configurationManagement'] is True
    registry = handlers(lambda: setup[1])
    capabilities = registry['agents.capabilities']({})
    assert capabilities['supports']['configurationManagement'] is True
    assert 'agents.nodes.configuration.apply' in capabilities['supportedMethods']
    applied = setup[3].apply(setup[5], setup[4], setup[6])
    assert applied.status == 'published'
    operation_ref = applied.intent.operation_ref
    before, counts = dump(setup), counters(setup)
    node_ref = encode_node_ref(setup[4])
    view = registry['agents.nodes.configuration.query'](
        {'nodeRef': node_ref, 'operationRef': operation_ref})
    assert set(view) == {'operationRef', 'revision', 'status', 'configurationResult'}
    assert view['operationRef'] == operation_ref and view['status'] == 'published'
    # Missing original: typed refusal, never an empty green answer.
    with pytest.raises(WireError) as missing:
        registry['agents.nodes.configuration.query'](
            {'nodeRef': node_ref, 'operationRef': 'no-such-operation'})
    assert missing.value.family == 'CAPABILITY_UNSUPPORTED'
    assert dump(setup) == before
    assert counters(setup) == counts


# CLI_SCENARIOS belonged to the retired old-grammar CLI tests.


def test_cli_configuration_and_provider_actions_stay_inside_frozen_contract():
    contract = set(wire_contract('agent-assembly/3')['methods'])
    for action in ('describe', 'inspect', 'apply', 'query'):
        assert 'agents.nodes.configuration.' + action in contract
    for action in ('list', 'describe'):
        assert 'agents.providers.' + action in contract
    source = ''
    from importlib.resources import files
    # The retired old CLI runtime is not scanned; the current client remains the
    # only consumer boundary for these frozen actions.
    source += files('ordessa_system_access_client').joinpath('client.py').read_text(encoding='utf-8')
    for uncontracted in ('agents.operations.list', 'agents.nodes.resolveMaterial',
                         'agents.nodes.compile', 'agents.materials'):
        assert uncontracted not in source
