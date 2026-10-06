"""Counterexamples for the thin CLI lifecycle commands (stop/release/recover/apply-profile).

The CLI lifecycle wiring checkpoint is registered without independent
counterexample coverage (docs/implementation/agent-tools/status.md,
2026-10-06). This file exercises the controlled HTTP wire over the reviewed
real temporary SQLite Core/Node publication/Issuer lifecycle fixture
(evidence/agent-unit-model/test_lifecycle.py) with its controlled provider and
owner receipt observer. No native process, no model, no user data, no live
service.

Covered counterexamples: fixed request file shape (missing/extra/wrong types,
bool-as-generation, float-as-revision, corrupt JSON, invalid UTF-8), the
precondition whitelist, apply-profile bodies that try to carry declarations,
capability gating of an unassembled lifecycle deployment, requestId idempotency
and conflicts, lost or unreadable receipts (exit 6, never resent, never
promoted to a derived operation identity), cross-environment/forged references,
and A17 token non-echo.
"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'docs/implementation/agent-tools/evidence/agent-unit-model'))
from test_lifecycle import lifecycle as core_lifecycle  # noqa: F401 - pytest fixture
from test_discovery import SECRET, config
from pacthold.agents.public import (AGENT_MANAGEMENT_CONTRACT_VERSION, agent_services, encode_node_ref)
from ordessa_environment_api import RequestKey
from ordessa_server.agent_core_wire import agent_core_methods
from server_plugin_api import WireError
from ordessa_agent_tools.cli import main
from ordessa_agent_tools.client import core_schema
from ordessa_agent_tools.lifecycle import (application_request_valid, disposition,
                                           preconditions_valid,
                                           request_valid as lifecycle_request_valid,
                                           view_valid)

ACTIONS = ('stop', 'release', 'recover')
LIFECYCLE_METHODS = {'agents.nodes.' + action for action in ACTIONS}
PROFILE_REF = {'environmentNamespace': 'env', 'profileId': 'profile', 'manifestRevision': 1,
               'contentDigest': 'sha256:' + 'a' * 64}
PRIVATE_SENTINEL = 'must-not-emit'


@pytest.fixture
def parts(core_lifecycle):
    lifecycle, owner, provider, node_ref, node, env, store, stop_request, provider_ref, current = core_lifecycle
    return SimpleNamespace(coordinator=lifecycle, owner=owner, provider=provider, node_ref=node_ref,
                           node=node, env=env, store=store, issuer=lifecycle._issuer)


def native_calls(parts):
    """Provider lifecycle dispatches only (the fixture also records unit/binding tuples)."""
    return [call for call in parts.provider.lifecycle_calls if type(call) is str]


RECEIPT_MUTATIONS = {
    'extra': lambda value: {**value, 'extra': True},
    'bool-revision': lambda value: {**value, 'revision': True},
    'float-revision': lambda value: {**value, 'revision': 1.0},
    'zero-revision': lambda value: {**value, 'revision': 0},
    'wrong-action': lambda value: {**value, 'action': 'release' if value['action'] != 'release' else 'stop'},
    'node-present': lambda value: {**value, 'node': {'ready': True}},
    'empty-ref': lambda value: {**value, 'operationRef': ''},
    'long-ref': lambda value: {**value, 'operationRef': 'x' * 257},
    'secret-key': lambda value: {**value, 'token': PRIVATE_SENTINEL},
    'token': lambda value: {**value, 'operationRef': SECRET},
    'malformed': lambda value: [],
    'refused': lambda value: {**value, 'status': 'refused'},
    'cancelled': lambda value: {**value, 'status': 'cancelled'},
    'reserved': lambda value: {**value, 'status': 'reserved'},
    'unknown-status': lambda value: {**value, 'status': 'unknown'},
    'published-status': lambda value: {**value, 'status': 'published'},
}


@contextmanager
def server(parts, mode='healthy', *, wired=True, action='stop'):
    token = os.environ['TOOLS_TEST_TOKEN']
    parts.provider.fail_lifecycle = action if mode == 'native-fail' else None
    if mode == 'configuration-unassembled':
        # This fixture starts from AgentLifecycle only; do not replace an
        # already-composed authority. Configuration is composed once with the
        # environment's absent issuer, matching an unassembled deployment.
        assert getattr(parts.env, '_agent_services', None) is None
        kwargs = {}
    else:
        kwargs = {'invocation_issuer': parts.issuer}
        if wired:
            kwargs['lifecycle_observation_port'] = parts.owner
    agent_services(parts.env, **kwargs)
    handlers = {item.method_id: item.handler for item in agent_core_methods(
        lambda: parts.env, contract_version=AGENT_MANAGEMENT_CONTRACT_VERSION)}
    calls, seen = [], {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, body):
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(request)
            assert self.headers['Authorization'] == 'Bearer ' + token
            method = request['method']
            if method == 'server.hello':
                self.respond({'jsonrpc': '2.0', 'id': request['id'], 'result': {
                    'serverId': 'controlled-core', 'protocolVersion': 'wire/1',
                    'auth': {'required': True, 'schemes': ['session_token']},
                    'capabilities': [{'id': name, 'supported': True} for name in handlers]}})
                return
            if mode == 'wire-unknown' and method in LIFECYCLE_METHODS:
                self.respond({'jsonrpc': '2.0', 'id': request['id'],
                              'error': {'code': 'OUTCOME_UNKNOWN', 'message': SECRET}})
                return
            if mode == 'lost-receipt' and method in LIFECYCLE_METHODS:
                handlers[method](request['params'])
                self.close_connection = True
                self.connection.close()
                return
            try:
                result = handlers[method](request['params'])
            except WireError as error:
                self.respond({'jsonrpc': '2.0', 'id': request['id'],
                              'error': {'code': error.family, 'message': SECRET}})
                return
            if method == 'agents.capabilities' and mode == 'missing-method':
                result = dict(result)
                result['supportedMethods'] = [name for name in result['supportedMethods']
                                              if name not in LIFECYCLE_METHODS]
            if method in LIFECYCLE_METHODS:
                result = RECEIPT_MUTATIONS.get(mode, lambda value: value)(result)
            if method == 'agents.capabilities':
                seen['capabilities'] = result
            self.respond({'jsonrpc': '2.0', 'id': request['id'], 'result': result})

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(httpd.server_port), calls, seen
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def lifecycle_file(parts, action, **overrides):
    value = {'requestId': 'request-' + action, 'nodeRef': encode_node_ref(parts.node_ref), 'preconditions': {}}
    value.update(overrides)
    return value


def application_file(**overrides):
    value = {'requestId': 'request-apply-profile', 'profileRef': dict(PROFILE_REF),
             'expectedConfigurationRevision': 'native-1',
             'applicationPolicy': {'allowDeferred': False, 'allowRestart': False}}
    value.update(overrides)
    return value


def write(path, content):
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, str):
        path.write_text(content)
    else:
        path.write_text(json.dumps(content))
    return path


def cli_args(tmp_path, endpoint, action, path=None, node=None):
    args = ['nodes', action, '--config', str(config(tmp_path, endpoint)), '--service', 'local', '--json']
    if action == 'apply-profile':
        args.append(json.dumps(encode_node_ref(node) if not isinstance(node, dict) else node))
    if path is not None:
        args += ['--file', str(path)]
    return args


def command(args, capsys, token=SECRET):
    code = main(args)
    output = capsys.readouterr()
    assert output.out, output.err
    assert token not in output.out + output.err
    assert PRIVATE_SENTINEL not in output.out + output.err
    return code, json.loads(output.out)


def key(parts, request_id):
    return RequestKey('env', 'principal', request_id)


OPERATION_KINDS = {'stop': 'agent-stop', 'release': 'agent-release', 'recover': 'agent-recovery'}


def discovery_only(item):
    """A refused/unknown command never adopts a lifecycle receipt as data."""
    return item['operationRef'] is None and set(item['data']) == {'discovery', 'coreAgent'}


# ---------------------------------------------------------------------------
# 1. Fixed request file shape, refused before any wire call.
# ---------------------------------------------------------------------------

SHAPE_CASES = {
    'missing-preconditions': lambda value: value.pop('preconditions'),
    'extra-field': lambda value: value.update({'context': {}}),
    'requestid-not-string': lambda value: value.update({'requestId': 7}),
    'requestid-pattern': lambda value: value.update({'requestId': 'Bad:request'}),
    'node-not-object': lambda value: value.update({'nodeRef': 'env:node:1'}),
    'node-missing-generation': lambda value: value['nodeRef'].pop('generation'),
    'node-extra-field': lambda value: value['nodeRef'].update({'nativeSessionId': 'wrong'}),
    'node-bool-generation': lambda value: value['nodeRef'].update({'generation': True}),
    'node-float-generation': lambda value: value['nodeRef'].update({'generation': 1.0}),
    'node-zero-generation': lambda value: value['nodeRef'].update({'generation': 0}),
    'node-negative-generation': lambda value: value['nodeRef'].update({'generation': -1}),
    'node-bad-instance': lambda value: value['nodeRef'].update({'instanceId': 'Bad'}),
    'preconditions-list': lambda value: value.update({'preconditions': []}),
    'preconditions-string': lambda value: value.update({'preconditions': 'none'}),
    'preconditions-unknown-key': lambda value: value.update({'preconditions': {'acquireAccess': True}}),
    'preconditions-private-key': lambda value: value.update({'preconditions': {'password': PRIVATE_SENTINEL}}),
    'revision-bool': lambda value: value.update({'preconditions': {'expectedPublicationRevision': True}}),
    'revision-float': lambda value: value.update({'preconditions': {'expectedPublicationRevision': 1.0}}),
    'revision-zero': lambda value: value.update({'preconditions': {'expectedPublicationRevision': 0}}),
    'revision-string': lambda value: value.update({'preconditions': {'expectedPublicationRevision': '1'}}),
}

RAW_CASES = {
    'top-level-list': b'[]',
    'top-level-string': b'"request-stop"',
    'empty-file': b'',
    'truncated-json': b'{"requestId": "request-stop", "nodeRef":',
    'duplicate-member': b'{"requestId": "request-stop", "requestId": "other", "nodeRef": {}, "preconditions": {}}',
    'non-finite-number': (b'{"requestId": "request-stop", "nodeRef": {"environmentNamespace": "env", '
                          b'"instanceId": "node", "generation": NaN}, "preconditions": {}}'),
    'invalid-utf8': (b'{"requestId": "request-stop", "nodeRef": {"environmentNamespace": "env", '
                     b'"instanceId": "no\xffde", "generation": 1}, "preconditions": {}}'),
    'oversized': b'{"padding": "' + b'a' * (1024 * 1024) + b'"}',
}


@pytest.mark.parametrize('case', sorted(SHAPE_CASES))
def test_fixed_lifecycle_request_shape_is_refused_before_any_wire_call(parts, tmp_path, monkeypatch, capsys, case):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    value = lifecycle_file(parts, 'stop')
    SHAPE_CASES[case](value)
    path = write(tmp_path / 'request.json', value)
    with server(parts, 'healthy') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
    assert code == 2 and item['status'] == 'refused' and item['error']['code'] == 'PARAMETER_INVALID'
    assert item['operationRef'] is None and item['data'] is None and item['evidence'] == {'level': 'unobserved'}
    assert calls == [] and native_calls(parts) == []
    assert parts.store.read_operation(key(parts, 'request-stop')) is None


@pytest.mark.parametrize('case', sorted(RAW_CASES))
def test_corrupt_or_unreadable_lifecycle_request_file_is_refused_locally(parts, tmp_path, monkeypatch, capsys, case):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    path = write(tmp_path / 'request.json', RAW_CASES[case])
    with server(parts, 'healthy') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
    assert code == 2 and item['error']['code'] == 'PARAMETER_INVALID' and item['status'] == 'refused'
    assert item['operationRef'] is None and calls == [] and native_calls(parts) == []


def test_absent_or_directory_request_file_is_refused_locally(parts, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with server(parts, 'healthy') as (endpoint, calls, seen):
        first = command(cli_args(tmp_path, endpoint, 'stop', tmp_path / 'absent.json'), capsys)
        second = command(cli_args(tmp_path, endpoint, 'stop', tmp_path), capsys)
    assert first[0] == second[0] == 2
    assert first[1]['error']['code'] == second[1]['error']['code'] == 'PARAMETER_INVALID'
    assert calls == [] and native_calls(parts) == []


APPLY_SHAPE_CASES = {
    'missing-policy': lambda value: value.pop('applicationPolicy'),
    'missing-revision': lambda value: value.pop('expectedConfigurationRevision'),
    'extra-declarations': lambda value: value.update({'declarations': []}),
    'extra-native-field': lambda value: value.update({'native': True}),
    'policy-extra-declarations': lambda value: value['applicationPolicy'].update({'declarations': []}),
    'policy-wrong-type': lambda value: value['applicationPolicy'].update({'allowRestart': 1}),
    'policy-string': lambda value: value['applicationPolicy'].update({'allowDeferred': 'false'}),
    'policy-missing-member': lambda value: value['applicationPolicy'].pop('allowRestart'),
    'policy-not-object': lambda value: value.update({'applicationPolicy': []}),
    'revision-bool': lambda value: value.update({'expectedConfigurationRevision': True}),
    'revision-float': lambda value: value.update({'expectedConfigurationRevision': 1.0}),
    'revision-empty': lambda value: value.update({'expectedConfigurationRevision': ''}),
    'requestid-pattern': lambda value: value.update({'requestId': 'Bad:request'}),
    'profile-missing-field': lambda value: value['profileRef'].pop('contentDigest'),
    'profile-bool-revision': lambda value: value['profileRef'].update({'manifestRevision': True}),
    'profile-float-revision': lambda value: value['profileRef'].update({'manifestRevision': 1.0}),
    'profile-bad-digest': lambda value: value['profileRef'].update({'contentDigest': 'sha256:xyz'}),
    'profile-extra-field': lambda value: value['profileRef'].update({'principal': 'forged'}),
}


@pytest.mark.parametrize('case', sorted(APPLY_SHAPE_CASES))
def test_fixed_apply_profile_request_shape_is_refused_before_any_wire_call(parts, tmp_path, monkeypatch, capsys, case):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    value = application_file()
    APPLY_SHAPE_CASES[case](value)
    path = write(tmp_path / 'application.json', value)
    with server(parts, 'healthy') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'apply-profile', path, node=parts.node_ref), capsys)
    assert code == 2 and item['status'] == 'refused' and item['error']['code'] == 'PARAMETER_INVALID'
    assert item['operationRef'] is None and calls == [] and native_calls(parts) == []
    assert parts.store.read_operation(key(parts, 'request-apply-profile')) is None


@pytest.mark.parametrize('node', [
    {'environmentNamespace': 'env', 'instanceId': 'node', 'generation': True},
    {'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 1.0},
    {'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 0},
    {'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 1, 'principal': 'forged'},
    {'environmentNamespace': 'env', 'instanceId': 'Bad', 'generation': 1},
])
def test_apply_profile_node_reference_is_checked_before_any_wire_call(parts, tmp_path, monkeypatch, capsys, node):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    path = write(tmp_path / 'application.json', application_file())
    with server(parts, 'healthy') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'apply-profile', path, node=node), capsys)
    assert code == 2 and item['error']['code'] == 'PARAMETER_INVALID' and calls == []
    assert native_calls(parts) == []


@pytest.mark.parametrize('action', ACTIONS + ('apply-profile',))
def test_missing_file_argument_is_refused_without_discovery(parts, tmp_path, monkeypatch, capsys, action):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with server(parts, 'healthy') as (endpoint, calls, seen):
        node = parts.node_ref if action == 'apply-profile' else None
        code, item = command(cli_args(tmp_path, endpoint, action, None, node=node), capsys)
    assert code == 2 and item['error']['code'] == 'PARAMETER_INVALID' and calls == []
    assert native_calls(parts) == []


# ---------------------------------------------------------------------------
# 2. Precondition whitelist and the declarations-free apply-profile body.
# ---------------------------------------------------------------------------

def test_precondition_values_are_whitelisted_and_typed():
    assert preconditions_valid({})
    assert preconditions_valid({'expectedPublicationRevision': 1})
    assert preconditions_valid({'expectedPublicationRevision': 99})
    for bad in (None, [], 'expectedPublicationRevision', 1, {'expectedPublicationRevision': True},
                {'expectedPublicationRevision': 1.0}, {'expectedPublicationRevision': 0},
                {'expectedPublicationRevision': '1'}, {'expectedPublicationRevision': -1}, {'unknown': 1}):
        assert not preconditions_valid(bad)


def test_lifecycle_request_requires_the_complete_fixed_file_and_known_scope():
    base = {'requestId': 'request-stop',
            'nodeRef': {'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 1},
            'preconditions': {}}
    assert lifecycle_request_valid(base) and lifecycle_request_valid(base, 'env')
    assert lifecycle_request_valid({**base, 'preconditions': {'expectedPublicationRevision': 1}})
    assert not lifecycle_request_valid({**base, 'context': {}})
    assert not lifecycle_request_valid({**base, 'preconditions': {'acquireAccess': True}})
    assert not lifecycle_request_valid({**base, 'nodeRef': {**base['nodeRef'], 'generation': True}})
    assert not lifecycle_request_valid({**base, 'nodeRef': {**base['nodeRef'], 'generation': 1.0}})
    assert not lifecycle_request_valid({**base, 'nodeRef': {**base['nodeRef'], 'environmentNamespace': 'foreign'}}, 'env')
    assert lifecycle_request_valid({**base, 'nodeRef': {**base['nodeRef'], 'environmentNamespace': 'foreign'}})


def test_apply_profile_request_never_carries_declarations_and_checks_scope():
    base = application_file()
    assert application_request_valid(base) and application_request_valid(base, 'env')
    assert not application_request_valid({**base, 'declarations': []})
    assert not application_request_valid({**base, 'applicationPolicy': {**base['applicationPolicy'], 'declarations': []}})
    assert not application_request_valid({**base, 'applicationPolicy': {'allowDeferred': False}})
    assert not application_request_valid({**base, 'applicationPolicy': {'allowDeferred': 0, 'allowRestart': False}})
    assert not application_request_valid({**base, 'expectedConfigurationRevision': True})
    assert not application_request_valid({**base, 'profileRef': {**base['profileRef'], 'manifestRevision': True}})
    assert not application_request_valid({**base, 'profileRef': {**base['profileRef'], 'manifestRevision': 1.0}})
    assert not application_request_valid({**base, 'profileRef': {**base['profileRef'], 'environmentNamespace': 'foreign'}}, 'env')
    assert application_request_valid({**base, 'profileRef': {**base['profileRef'], 'environmentNamespace': 'foreign'}})


# ---------------------------------------------------------------------------
# 3. Projection shape against the shipped management schema + disposition map.
# ---------------------------------------------------------------------------

def test_lifecycle_operation_view_and_disposition_follow_the_shipped_management_schema():
    from importlib.resources import files
    shipped = json.loads(files('ordessa_agent_tools').joinpath('schema-management.json').read_bytes())['schema']['results']['lifecycleOperation']
    assert shipped == {'required': ['operationRef', 'revision', 'status', 'action'],
                       'additionalProperties': False,
                       'statuses': ['reserved', 'running', 'unknown', 'published', 'refused', 'cancelled']}
    schema = core_schema('agent-assembly/3')['schema']
    assert schema['results']['lifecycleOperation'] == shipped
    base = {'operationRef': 'lifecycle-stop-abcd', 'revision': 2, 'status': 'running', 'action': 'stop', 'node': None}
    assert view_valid(base, 'stop', schema)
    assert view_valid({name: base[name] for name in ('operationRef', 'revision', 'status', 'action')}, 'stop', schema)
    assert not view_valid({**base, 'extra': True}, 'stop', schema)
    assert not view_valid({name: base[name] for name in ('operationRef', 'revision', 'status')}, 'stop', schema)
    assert not view_valid({**base, 'revision': True}, 'stop', schema)
    assert not view_valid({**base, 'revision': 1.0}, 'stop', schema)
    assert not view_valid({**base, 'revision': 0}, 'stop', schema)
    assert not view_valid({**base, 'status': 'ready'}, 'stop', schema)
    assert not view_valid({**base, 'action': 'release'}, 'stop', schema)
    assert not view_valid({**base, 'operationRef': ''}, 'stop', schema)
    assert not view_valid({**base, 'operationRef': 'x' * 257}, 'stop', schema)
    assert not view_valid({**base, 'node': {'ready': True}}, 'stop', schema)
    assert not view_valid({**base, 'node': False}, 'stop', schema)
    expected = {'running': ('confirmed', 0, None), 'published': ('confirmed', 0, None),
                'refused': ('refused', 4, 'LIFECYCLE_REFUSED'),
                'cancelled': ('refused', 4, 'LIFECYCLE_REFUSED'),
                'reserved': ('unknown', 6, 'OUTCOME_UNKNOWN'),
                'unknown': ('unknown', 6, 'OUTCOME_UNKNOWN')}
    assert set(expected) == set(shipped['statuses'])
    assert {status: disposition({'status': status}) for status in shipped['statuses']} == expected


# ---------------------------------------------------------------------------
# 4. Healthy projection per action.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('action', ACTIONS)
def test_lifecycle_action_projects_the_original_operation_and_concludes_one_step(parts, tmp_path, monkeypatch, capsys, action):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    request = lifecycle_file(parts, action)
    path = write(tmp_path / (action + '.json'), request)
    with server(parts, 'healthy', action=action) as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, action, path), capsys)
    assert code == 0 and item['status'] == 'confirmed' and item['error'] is None
    assert item['requestId'] == request['requestId']
    data = item['data']
    assert set(data) == {'operationRef', 'revision', 'status', 'action', 'node'} and data['node'] is None
    assert data['action'] == action and data['status'] == 'running'
    assert type(data['revision']) is int and data['revision'] >= 1
    assert item['operationRef'] == data['operationRef']
    operation = parts.store.read_operation(key(parts, request['requestId']))
    assert data['operationRef'] == operation.intent.operation_ref
    assert data['revision'] == operation.revision
    assert operation.intent.kind == OPERATION_KINDS[action]
    assert parts.store.read_operation_step(key(parts, request['requestId']), action).outcome == 'concluded'
    assert native_calls(parts) == [action]
    assert [call['method'] for call in calls] == ['server.hello', 'agents.capabilities', 'agents.nodes.' + action]
    assert calls[-1]['params'] == request
    assert item['evidence'] == {'level': 'lifecycleOperationObserved', 'runtimeVerified': False,
                                'operationStatus': 'running'}


# ---------------------------------------------------------------------------
# 5. Idempotency: replay reads the original operation, conflicts never re-dispatch.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('action', ACTIONS)
def test_same_request_replays_the_original_receipt_without_second_dispatch(parts, tmp_path, monkeypatch, capsys, action):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    request = lifecycle_file(parts, action)
    path = write(tmp_path / (action + '.json'), request)
    with server(parts, 'healthy', action=action) as (endpoint, calls, seen):
        first = command(cli_args(tmp_path, endpoint, action, path), capsys)
        second = command(cli_args(tmp_path, endpoint, action, path), capsys)
    assert first[0] == second[0] == 0
    assert first[1]['data'] == second[1]['data']
    assert first[1]['operationRef'] == second[1]['operationRef']
    assert native_calls(parts) == [action]
    assert sum(call['method'] == 'agents.nodes.' + action for call in calls) == 2
    assert parts.store.read_operation_step(key(parts, request['requestId']), action).outcome == 'concluded'


@pytest.mark.parametrize('flip', [False, True])
def test_spent_request_with_changed_preconditions_conflicts_without_effect(parts, tmp_path, monkeypatch, capsys, flip):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    # The precondition CAS only admits the Node's actual publication revision;
    # omission and the exact value stay individually valid in both orders.
    exact = {'expectedPublicationRevision': parts.node['publicationRevision']}
    first, second = ({}, dict(exact)) if not flip else (dict(exact), {})
    path = write(tmp_path / 'stop.json', lifecycle_file(parts, 'stop', preconditions=dict(first)))
    with server(parts, 'healthy') as (endpoint, calls, seen):
        accepted = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
        changed = write(tmp_path / 'changed.json', lifecycle_file(parts, 'stop', preconditions=dict(second)))
        conflict = command(cli_args(tmp_path, endpoint, 'stop', changed), capsys)
        fresh = write(tmp_path / 'fresh.json', lifecycle_file(parts, 'stop', requestId='request-stop-second',
                                                              preconditions=dict(second)))
        accepted_again = command(cli_args(tmp_path, endpoint, 'stop', fresh), capsys)
    assert accepted[0] == 0 and accepted_again[0] == 0
    assert conflict[0] == 5 and conflict[1]['status'] == 'refused'
    assert conflict[1]['error']['code'] == 'PRECONDITION_CONFLICT' and conflict[1]['error']['retryable'] is False
    assert discovery_only(conflict[1])
    original = parts.store.read_operation(key(parts, 'request-stop'))
    assert original.intent.operation_ref == accepted[1]['operationRef']
    assert accepted_again[1]['data']['operationRef'] != accepted[1]['operationRef']
    assert native_calls(parts) == ['stop', 'stop']
    assert sum(call['method'] == 'agents.nodes.stop' for call in calls) == 3


def test_stale_expected_publication_revision_conflicts_without_effect(parts, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    stale = {'expectedPublicationRevision': parts.node['publicationRevision'] + 1}
    path = write(tmp_path / 'stale.json', lifecycle_file(parts, 'stop', preconditions=stale))
    with server(parts, 'healthy') as (endpoint, calls, seen):
        conflict = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
    assert conflict[0] == 5 and conflict[1]['error']['code'] == 'PRECONDITION_CONFLICT'
    assert conflict[1]['error']['retryable'] is False
    assert discovery_only(conflict[1])
    assert native_calls(parts) == []
    assert sum(call['method'] == 'agents.nodes.stop' for call in calls) == 1


# ---------------------------------------------------------------------------
# 6. Lost receipt / unknown receipt: exit 6, never resent, never derived.
# ---------------------------------------------------------------------------

def test_lost_lifecycle_receipt_is_unknown_without_resend_or_derived_identity(parts, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    request = lifecycle_file(parts, 'stop')
    path = write(tmp_path / 'stop.json', request)
    with server(parts, 'lost-receipt', action='stop') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
        assert code == 6 and item['status'] == 'unknown' and item['error']['code'] == 'OUTCOME_UNKNOWN'
        assert item['error']['retryable'] is False
        assert item['operationRef'] is None and discovery_only(item)
        assert native_calls(parts) == ['stop']
        assert parts.store.read_operation_step(key(parts, 'request-stop'), 'stop').outcome == 'concluded'
        original = parts.store.read_operation(key(parts, 'request-stop')).intent.operation_ref
    with server(parts, 'healthy', action='stop') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
    assert code == 0 and item['operationRef'] == original and item['data']['status'] == 'running'
    assert native_calls(parts) == ['stop']
    assert sum(call['method'] == 'agents.nodes.stop' for call in calls) == 1


def test_native_failure_is_unknown_receipt_with_original_identity_and_no_resend(parts, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    request = lifecycle_file(parts, 'stop')
    path = write(tmp_path / 'stop.json', request)
    with server(parts, 'native-fail', action='stop') as (endpoint, calls, seen):
        first = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
        second = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
    original = parts.store.read_operation(key(parts, 'request-stop')).intent.operation_ref
    assert first[0] == second[0] == 6
    assert first[1]['status'] == second[1]['status'] == 'unknown'
    assert first[1]['error']['code'] == second[1]['error']['code'] == 'OUTCOME_UNKNOWN'
    assert first[1]['operationRef'] == second[1]['operationRef'] == original
    assert first[1]['data']['status'] == 'unknown'
    assert parts.store.read_operation_step(key(parts, 'request-stop'), 'stop').outcome == 'unknown'
    assert native_calls(parts) == ['stop']
    assert sum(call['method'] == 'agents.nodes.stop' for call in calls) == 2


@pytest.mark.parametrize('mode', ['extra', 'bool-revision', 'float-revision', 'zero-revision', 'wrong-action',
                                  'node-present', 'empty-ref', 'long-ref', 'secret-key', 'token', 'malformed'])
def test_unreadable_committed_receipt_is_unknown_and_never_resent(parts, tmp_path, monkeypatch, capsys, mode):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    path = write(tmp_path / 'stop.json', lifecycle_file(parts, 'stop'))
    with server(parts, mode, action='stop') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
    assert code == 6 and item['status'] == 'unknown' and item['error']['code'] == 'OUTCOME_UNKNOWN'
    assert item['error']['retryable'] is False
    assert item['operationRef'] is None and discovery_only(item)
    assert item['evidence']['level'] == 'coreCapabilitiesObserved'
    assert native_calls(parts) == ['stop']
    assert sum(call['method'] == 'agents.nodes.stop' for call in calls) == 1
    assert parts.store.read_operation_step(key(parts, 'request-stop'), 'stop').outcome == 'concluded'


def test_wire_level_unknown_error_never_echoes_the_server_message_or_resends(parts, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    path = write(tmp_path / 'stop.json', lifecycle_file(parts, 'stop'))
    with server(parts, 'wire-unknown', action='stop') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
    assert code == 6 and item['status'] == 'unknown' and item['error']['code'] == 'OUTCOME_UNKNOWN'
    assert item['operationRef'] is None and discovery_only(item)
    assert native_calls(parts) == []
    assert sum(call['method'] == 'agents.nodes.stop' for call in calls) == 1


@pytest.mark.parametrize('status,exit_code,envelope,error', [
    ('refused', 4, 'refused', 'LIFECYCLE_REFUSED'),
    ('cancelled', 4, 'refused', 'LIFECYCLE_REFUSED'),
    ('reserved', 6, 'unknown', 'OUTCOME_UNKNOWN'),
    ('unknown', 6, 'unknown', 'OUTCOME_UNKNOWN'),
])
def test_disposition_projection_decides_envelope_status_and_exit(parts, tmp_path, monkeypatch, capsys, status, exit_code, envelope, error):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    path = write(tmp_path / 'stop.json', lifecycle_file(parts, 'stop'))
    mode = {'refused': 'refused', 'cancelled': 'cancelled', 'reserved': 'reserved', 'unknown': 'unknown-status'}[status]
    with server(parts, mode, action='stop') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
    assert code == exit_code and item['status'] == envelope and item['error']['code'] == error
    assert item['error']['retryable'] is False
    assert item['data']['status'] == status
    assert item['operationRef'] == item['data']['operationRef']
    assert item['evidence']['operationStatus'] == status


# ---------------------------------------------------------------------------
# 7. Capability gating and cross-environment references.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('action', ACTIONS)
def test_unassembled_lifecycle_is_typed_unsupported_and_never_reserved(parts, tmp_path, monkeypatch, capsys, action):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    path = write(tmp_path / (action + '.json'), lifecycle_file(parts, action))
    with server(parts, 'healthy', wired=False, action=action) as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, action, path), capsys)
    assert code == 4 and item['status'] == 'refused' and item['error']['code'] == 'CAPABILITY_UNSUPPORTED'
    assert item['error']['retryable'] is False and discovery_only(item)
    assert [call['method'] for call in calls] == ['server.hello', 'agents.capabilities']
    assert seen['capabilities']['supports']['nodeLifecycle'] is False
    assert 'agents.nodes.' + action not in seen['capabilities']['supportedMethods']
    assert native_calls(parts) == []
    assert parts.store.read_operation(key(parts, 'request-' + action)) is None


@pytest.mark.parametrize('action', ACTIONS)
def test_capabilities_without_lifecycle_methods_gate_before_dispatch(parts, tmp_path, monkeypatch, capsys, action):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    path = write(tmp_path / (action + '.json'), lifecycle_file(parts, action))
    with server(parts, 'missing-method', action=action) as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, action, path), capsys)
    assert code == 4 and item['error']['code'] == 'CAPABILITY_UNSUPPORTED' and item['status'] == 'refused'
    assert seen['capabilities']['supports']['nodeLifecycle'] is True
    assert 'agents.nodes.' + action not in seen['capabilities']['supportedMethods']
    assert [call['method'] for call in calls] == ['server.hello', 'agents.capabilities']
    assert native_calls(parts) == []
    assert parts.store.read_operation(key(parts, 'request-' + action)) is None


def test_foreign_environment_node_is_refused_before_reservation(parts, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    request = lifecycle_file(parts, 'stop')
    request['nodeRef']['environmentNamespace'] = 'foreign'
    path = write(tmp_path / 'stop.json', request)
    with server(parts, 'healthy', action='stop') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'stop', path), capsys)
    assert code == 2 and item['error']['code'] == 'PARAMETER_INVALID' and item['status'] == 'refused'
    assert item['operationRef'] is None and discovery_only(item)
    assert [call['method'] for call in calls] == ['server.hello', 'agents.capabilities']
    assert native_calls(parts) == []
    assert parts.store.read_operation(key(parts, 'request-stop')) is None


def test_apply_profile_body_declarations_are_refused_before_discovery(parts, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    value = application_file(declarations=[{'declarationId': 'model', 'configurationKind': 'model',
                                            'schemaVersion': '1', 'action': 'value', 'requirement': 'required'}])
    path = write(tmp_path / 'application.json', value)
    with server(parts, 'healthy') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'apply-profile', path, node=parts.node_ref), capsys)
    assert code == 2 and item['error']['code'] == 'PARAMETER_INVALID' and item['status'] == 'refused'
    assert calls == [] and native_calls(parts) == []
    assert parts.store.read_operation(key(parts, 'request-apply-profile')) is None


def test_configuration_unassembled_does_not_advertise_apply_profile_or_reserve(parts, tmp_path, monkeypatch, capsys):
    # The fixture composes AgentServices for the first time without an issuer.
    # This is a real missing-configuration counterexample, not a healthy
    # deployment with its advertised methods artificially removed.
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    path = write(tmp_path / 'application.json', application_file())
    with server(parts, 'configuration-unassembled') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'apply-profile', path, node=parts.node_ref), capsys)
    assert code == 4 and item['status'] == 'refused' and item['error']['code'] == 'CAPABILITY_UNSUPPORTED'
    assert item['error']['retryable'] is False and discovery_only(item)
    assert [call['method'] for call in calls] == ['server.hello', 'agents.capabilities']
    assert seen['capabilities']['supports']['configurationManagement'] is False
    assert 'agents.nodes.applyProfile' not in seen['capabilities']['supportedMethods']
    assert parts.provider.lifecycle_calls == []
    assert native_calls(parts) == []
    assert parts.store.read_operation(key(parts, 'request-apply-profile')) is None


def test_healthy_wire_advertises_apply_profile_but_cli_old_shape_fails_client_schema(parts, tmp_path, monkeypatch, capsys):
    # The live wire schema requires baseProfileRef; the CLI's existing
    # application request shape does not carry it. Keep this as a real CLI
    # counterexample: the client rejects locally before sending an applyProfile
    # HTTP request or reserving an operation.
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    path = write(tmp_path / 'application.json', application_file())
    with server(parts, 'healthy') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'apply-profile', path, node=parts.node_ref), capsys)
    assert code == 2 and item['status'] == 'refused' and item['error']['code'] == 'PARAMETER_INVALID'
    assert item['error']['retryable'] is False and discovery_only(item)
    assert seen['capabilities']['supports']['configurationManagement'] is True
    assert 'agents.nodes.applyProfile' in seen['capabilities']['supportedMethods']
    assert [call['method'] for call in calls] == ['server.hello', 'agents.capabilities']
    assert parts.provider.lifecycle_calls == []
    assert native_calls(parts) == []
    assert parts.store.read_operation(key(parts, 'request-apply-profile')) is None


# ---------------------------------------------------------------------------
# 8. A17: authentication material never enters requests or output.
# ---------------------------------------------------------------------------

def test_request_identity_carrying_authentication_material_is_refused_before_wire(parts, tmp_path, monkeypatch, capsys):
    token = 'fixturetoken'
    monkeypatch.setenv('TOOLS_TEST_TOKEN', token)
    request = lifecycle_file(parts, 'stop', requestId=token + '-stop')
    path = write(tmp_path / 'stop.json', request)
    with server(parts, 'healthy', action='stop') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'stop', path), capsys, token=token)
    assert code == 2 and item['error']['code'] == 'PARAMETER_INVALID' and item['status'] == 'refused'
    assert calls == [] and native_calls(parts) == []
    assert parts.store.read_operation(key(parts, token + '-stop')) is None


def test_request_material_carrying_authentication_material_is_refused_before_dispatch(parts, tmp_path, monkeypatch, capsys):
    token = 'fixturetoken'
    monkeypatch.setenv('TOOLS_TEST_TOKEN', token)
    request = lifecycle_file(parts, 'stop')
    request['nodeRef']['instanceId'] = token
    path = write(tmp_path / 'stop.json', request)
    with server(parts, 'healthy', action='stop') as (endpoint, calls, seen):
        code, item = command(cli_args(tmp_path, endpoint, 'stop', path), capsys, token=token)
    assert code == 2 and item['error']['code'] == 'PARAMETER_INVALID' and item['status'] == 'refused'
    assert [call['method'] for call in calls] == ['server.hello', 'agents.capabilities']
    assert native_calls(parts) == []
    assert parts.store.read_operation(key(parts, 'request-stop')) is None
