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

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'docs/implementation/agent-tools/evidence/agent-unit-model'))
from test_management import setup, node_fixture, explicit_capabilities  # noqa: F401

from pacthold.agents.public import agent_services, encode_node_ref, wire_contract
from ordessa_server.agent_core_wire import agent_core_methods
from server_plugin_api import WireError

from test_operation_read_cli import (
    BUILDERS, SECRET, config as service_config, envelope, wire_server, without,
)
from ordessa_agent_tools.cli import main


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
    services = agent_services(setup[1], invocation_issuer=setup[10])
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


CLI_SCENARIOS = {
    'configuration-describe-unadvertised': (
        {'capabilities': without('agents.nodes.configuration.describe')},
        'configuration-describe', 4, 'NODE_CONFIGURATION_UNAVAILABLE', 2, 0),
    'configuration-inspect-unadvertised': (
        {'capabilities': without('agents.nodes.configuration.inspect')},
        'configuration-inspect', 4, 'NODE_CONFIGURATION_UNAVAILABLE', 2, 0),
    'configuration-query-unadvertised': (
        {'capabilities': without('agents.nodes.configuration.query')},
        'configuration-query', 4, 'NODE_CONFIGURATION_UNAVAILABLE', 2, 0),
    'configuration-describe-foreign-node': (
        {}, 'configuration-describe-foreign-node', 2, 'PARAMETER_INVALID', 2, 0),
    'configuration-query-foreign-node': (
        {}, 'configuration-query-foreign-node', 2, 'PARAMETER_INVALID', 2, 0),
    'configuration-describe-forbidden': (
        {'errors': {'agents.nodes.configuration.describe': 'FORBIDDEN'}},
        'configuration-describe', 3, 'AUTHORIZATION_REFUSED', 3, 1),
    'providers-describe-unadvertised': (
        {'capabilities': without('agents.providers.describe')},
        'providers-describe', 4, 'PROVIDER_DISCOVERY_UNAVAILABLE', 2, 0),
    'providers-list-unadvertised': (
        {'capabilities': without('agents.providers.list')},
        'providers-list', 4, 'PROVIDER_DISCOVERY_UNAVAILABLE', 2, 0),
    'providers-describe-foreign-definition': (
        {}, 'providers-describe-foreign-definition', 2, 'PARAMETER_INVALID', 2, 0),
    'providers-describe-forbidden': (
        {'errors': {'agents.providers.describe': 'FORBIDDEN'}},
        'providers-describe', 3, 'AUTHORIZATION_REFUSED', 3, 1),
}


@pytest.mark.parametrize('mode', sorted(CLI_SCENARIOS))
def test_cli_configuration_provider_boundaries_refuse_with_documented_exits(tmp_path, monkeypatch, capsys, mode):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    server_kwargs, builder_key, expected_exit, expected_code, expected_calls, expected_target = CLI_SCENARIOS[mode]
    builder, target_method = BUILDERS[builder_key]
    with wire_server(**server_kwargs) as (endpoint, calls):
        actual = main(builder(service_config(tmp_path, endpoint)))
    body = envelope(capsys)
    assert actual == expected_exit and body['error']['code'] == expected_code
    assert body['error']['retryable'] is False
    methods = [call['request']['method'] for call in calls]
    assert len(calls) == expected_calls, methods
    assert sum(name == target_method for name in methods) == expected_target, methods


def test_cli_local_configuration_and_provider_inputs_refuse_without_http(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    # Closed loopback port: a network attempt would surface a transport refusal
    # instead of the local PARAMETER_INVALID exit.
    path = service_config(tmp_path, 'http://127.0.0.1:1')
    malformed_change = tmp_path / 'change.json'
    malformed_change.write_text(json.dumps({'requestId': 'request-1'}))
    actual = main(['nodes', 'configuration', 'apply', json.dumps(NODE_REF),
                   '--file', str(malformed_change), '--config', str(path),
                   '--service', 'local', '--json'])
    body = envelope(capsys)
    assert actual == 2 and body['error']['code'] == 'PARAMETER_INVALID'
    assert body['data'] is None
    actual = main(['providers', 'describe', '{"environmentNamespace":"env"}',
                   '--config', str(path), '--service', 'local', '--json'])
    body = envelope(capsys)
    assert actual == 2 and body['error']['code'] == 'PARAMETER_INVALID'
    assert body['data'] is None


def test_cli_foreign_configuration_material_refused_after_discovery_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    foreign_change = {'requestId': 'request-1', 'expectedConfigurationRevision': 'native-1',
                      'declarations': [{'declarationId': 'model', 'configurationKind': 'model',
                                        'schemaVersion': '1', 'action': 'value',
                                        'requirement': 'required',
                                        'payload': {'modelId': 'new'},
                                        'resourceRefs': [{'environmentNamespace': 'foreign',
                                                          'ref': 'material'}]}],
                      'applicationPolicy': {'allowDeferred': False, 'allowRestart': False}}
    change_file = tmp_path / 'change.json'
    change_file.write_text(json.dumps(foreign_change))
    with wire_server() as (endpoint, calls):
        actual = main(['nodes', 'configuration', 'apply', json.dumps(NODE_REF),
                       '--file', str(change_file), '--config', str(service_config(tmp_path, endpoint)),
                       '--service', 'local', '--json'])
    body = envelope(capsys)
    assert actual == 2 and body['error']['code'] == 'PARAMETER_INVALID'
    methods = [call['request']['method'] for call in calls]
    assert len(calls) == 2, methods
    assert 'agents.nodes.configuration.apply' not in methods


def test_cli_configuration_and_provider_actions_stay_inside_frozen_contract():
    contract = set(wire_contract('agent-assembly/3')['methods'])
    for action in ('describe', 'inspect', 'apply', 'query'):
        assert 'agents.nodes.configuration.' + action in contract
    for action in ('list', 'describe'):
        assert 'agents.providers.' + action in contract
    source = ''
    for name in ('cli.py', 'client.py'):
        from importlib.resources import files
        source += files('ordessa_agent_tools').joinpath(name).read_text(encoding='utf-8')
    for uncontracted in ('agents.operations.list', 'agents.nodes.resolveMaterial',
                         'agents.nodes.compile', 'agents.materials'):
        assert uncontracted not in source
