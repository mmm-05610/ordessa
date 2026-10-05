"""C: CLI + actual Core/SQLite publication + controlled HTTP, no native task."""
import json
from types import SimpleNamespace
import pytest

import test_configuration_cli as peer
from test_configuration_cli import setup, node_fixture, explicit_capabilities
from test_discovery import SECRET, config
from pacthold.agents.public import encode_node_ref
from ordessa_agent_tools.cli import main
from server_plugin_api import WireError


def invoke(parts, tmp_path, monkeypatch, capsys, action='inspect', mode='healthy', ref=None, file=False):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    original = peer.agent_core_methods
    def bind(*args, **kwargs):
        def wrap(method):
            def handler(params):
                if method.method_id in ('agents.nodes.read', 'agents.nodes.list') and mode == 'forbidden':
                    parts[2].allowed = False
                if method.method_id in ('agents.nodes.read', 'agents.nodes.list') and mode == 'unknown':
                    raise WireError('OUTCOME_UNKNOWN', SECRET, {'retryable': False})
                result = method.handler(params)
                if method.method_id == 'agents.capabilities' and mode == 'missing-method':
                    result['supportedMethods'] = [name for name in result['supportedMethods'] if name not in ('agents.nodes.read', 'agents.nodes.list')]
                if method.method_id in ('agents.nodes.read', 'agents.nodes.list'):
                    records = result['nodes'] if 'nodes' in result else [result['node']] if result['node'] else []
                    if mode == 'wrapper': return {'invented': records}
                    if mode == 'duplicate': result['nodes'] += result['nodes']
                    for item in records:
                        if mode == 'ready': item['ready'] = True
                        if mode == 'bool-revision': item['publicationRevision'] = True
                        if mode == 'float-generation': item['nodeRef']['generation'] = 1.0
                        if mode == 'foreign-node': item['nodeRef']['environmentNamespace'] = 'foreign'
                        if mode == 'wrong-node': item['nodeRef']['instanceId'] = 'other'
                        if mode == 'foreign-unit': item['binding']['harnessUnitRef']['environmentNamespace'] = 'foreign'
                        if mode == 'owner-proof': item['binding']['harnessUnitRef']['ownerProviderRef'] = {'environmentNamespace': 'env', 'ref': 'fabricated'}
                        if mode == 'no-source': item['binding']['configurationTargetRef']['sourceRevision'] = None
                        if mode == 'lineage': item['lineage']['profileSnapshotRef']['manifestRevision'] += 1
                        if mode == 'no-access': item['accessSurfaceRefs'] = []
                        if mode == 'bad-surface': item['managementSurfaceRefs'][0]['nodeRef']['generation'] = True
                        if mode == 'private': item['binding']['harnessUnitRef']['stdout'] = 'must-not-emit'
                        if mode == 'token': item['binding']['harnessUnitRef']['ref'] = SECRET
                return result
            return SimpleNamespace(method_id=method.method_id, handler=handler)
        return tuple(wrap(item) for item in original(*args, **kwargs))
    monkeypatch.setattr(peer, 'agent_core_methods', bind)
    with peer.observation_server(parts) as (endpoint, calls):
        args = ['nodes', action, '--config', str(config(tmp_path, endpoint)), '--service', 'local', '--json']
        if action == 'inspect':
            node = encode_node_ref(parts[4]) if ref is None else ref
            if file:
                path = tmp_path / 'node.json'; path.write_text(json.dumps(node))
                args.append('@' + str(path))
            else: args.append(json.dumps(node))
        code = main(args)
        output = capsys.readouterr()
        assert SECRET not in output.out + output.err and 'must-not-emit' not in output.out
        assert parts[7]['calls'] == parts[7]['queryCalls'] == 0
        assert parts[0].read_operation(parts[5]) is None
        return code, json.loads(output.out), calls


@pytest.mark.parametrize('action', ['list', 'inspect'])
def test_publication_read_without_issuer_is_not_native_runtime_readiness(setup, tmp_path, monkeypatch, capsys, action):
    code, envelope, calls = invoke(setup, tmp_path, monkeypatch, capsys, action=action, file=True)
    assert code == 0 and envelope['status'] == 'confirmed'
    node = envelope['data']['node'] if action == 'inspect' else envelope['data']['nodes'][0]
    assert node['nodeRef'] == encode_node_ref(setup[4])
    assert 'ready' not in node and 'state' not in node
    assert envelope['evidence'] == {'level': 'nodePublicationObserved', 'runtimeVerified': False}
    assert len(calls) == 3


def test_missing_node_is_resource_absence_not_green(setup, tmp_path, monkeypatch, capsys):
    ref = encode_node_ref(setup[4]); ref['instanceId'] = 'absent'
    code, envelope, calls = invoke(setup, tmp_path, monkeypatch, capsys, ref=ref)
    assert code == 4 and envelope['error']['code'] == 'NODE_NOT_FOUND'
    assert envelope['data'] == {'node': None} and envelope['status'] == 'refused'
    assert len(calls) == 3


@pytest.mark.parametrize('mode', ['wrapper', 'ready', 'bool-revision', 'float-generation', 'foreign-node', 'wrong-node', 'foreign-unit', 'owner-proof', 'no-source', 'lineage', 'no-access', 'bad-surface', 'private', 'token'])
def test_malformed_publication_refused_without_leaking(setup, tmp_path, monkeypatch, capsys, mode):
    code, envelope, calls = invoke(setup, tmp_path, monkeypatch, capsys, mode=mode)
    assert code == 4 and envelope['error']['code'] == 'CORE_RESPONSE_INVALID'
    assert envelope['evidence']['level'] == 'coreCapabilitiesObserved'
    assert len(calls) == 3


def test_duplicate_node_list_refused(setup, tmp_path, monkeypatch, capsys):
    code, envelope, calls = invoke(setup, tmp_path, monkeypatch, capsys, action='list', mode='duplicate')
    assert code == 4 and envelope['error']['code'] == 'CORE_RESPONSE_INVALID' and len(calls) == 3


@pytest.mark.parametrize('mode, code, error, count', [('missing-method', 4, 'NODE_OBSERVATION_UNAVAILABLE', 2), ('forbidden', 3, 'AUTHORIZATION_REFUSED', 3), ('unknown', 6, 'OUTCOME_UNKNOWN', 3)])
def test_method_permission_and_unknown_do_not_fallback(setup, tmp_path, monkeypatch, capsys, mode, code, error, count):
    actual, envelope, calls = invoke(setup, tmp_path, monkeypatch, capsys, mode=mode)
    assert actual == code and envelope['error']['code'] == error
    assert envelope['error']['retryable'] is False and len(calls) == count


@pytest.mark.parametrize('change, count', [({'generation': True}, 0), ({'generation': 1.0}, 0), ({'principalScope': 'invented'}, 0), ({'environmentNamespace': 'foreign'}, 2)])
def test_invalid_or_foreign_input_not_sent(setup, tmp_path, monkeypatch, capsys, change, count):
    ref = encode_node_ref(setup[4]); ref.update(change)
    code, envelope, calls = invoke(setup, tmp_path, monkeypatch, capsys, ref=ref)
    assert code == 2 and envelope['error']['code'] == 'PARAMETER_INVALID' and len(calls) == count


@pytest.mark.parametrize('command, expected', [('capabilities', 0), ('doctor', 4), ('node-inspect', 0)])
def test_node_read_and_general_discovery_do_not_require_profile_write_fingerprint(setup, tmp_path, monkeypatch, capsys, command, expected):
    # Actual core capability becomes false; no forged HTTP capability payload.
    setup[1]._fingerprint_port = None
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with peer.observation_server(setup) as (endpoint, calls):
        args = ['nodes', 'inspect', json.dumps(encode_node_ref(setup[4]))] if command == 'node-inspect' else [command]
        code = main(args + ['--config', str(config(tmp_path, endpoint)), '--service', 'local', '--json'])
        output = capsys.readouterr(); result = json.loads(output.out)
        assert code == expected and SECRET not in output.out + output.err
        if command == 'doctor':
            assert result['error']['code'] == 'PROFILE_CATALOG_UNAVAILABLE'
        elif command == 'capabilities':
            assert result['status'] == 'confirmed'
            assert result['data']['coreAgent']['supports']['profileCatalog'] is False
            assert 'agents.nodes.read' in result['data']['coreAgent']['supportedMethods']
        else:
            assert result['data']['node']['nodeRef'] == encode_node_ref(setup[4])
        assert len(calls) == (3 if command == 'node-inspect' else 2)
        assert setup[7]['calls'] == setup[7]['queryCalls'] == 0
        assert setup[0].read_operation(setup[5]) is None
