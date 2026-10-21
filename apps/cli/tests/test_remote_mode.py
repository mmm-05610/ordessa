"""Remote mode: the same channel/metadata over CapabilityClient.

The fake server is a controlled peer for the wire contract. It is not the
production Server: it replays the original request ledger, returns the same
envelope shapes, can lose a committed response, and can revoke access.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import threading
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ordessa_cli.cli import main

TOKEN = 'test-remote-token'


def _text(limit=512):
    return {'type': 'string', 'minLength': 1, 'maxLength': limit}


def _closed(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required),
            'additionalProperties': False}


OPERATIONS = {
    'agents.profiles.capabilities': (_closed({}), None),
    'agents.profiles.list': (_closed({'includeArchived': {'type': 'boolean'}}),
                      {'command': 'agents profiles', 'operation': 'list',
                       'args': ({'name': 'includeArchived',
                                 'flags': ('--include-archived',), 'type': 'boolean'},)}),
    'agents.profiles.read': (_closed({'profileRef': {'type': 'object'}}, ('profileRef',)),
                      {'command': 'agents profiles', 'operation': 'read',
                       'args': ({'name': 'profileRef', 'type': 'json-file'},)}),
    'agents.profiles.preview': (_closed({'profileRef': {'type': 'object'}}, ('profileRef',)),
                         {'command': 'agents profiles', 'operation': 'preview',
                          'args': ({'name': 'profileRef', 'type': 'json-file'},)}),
    'agents.profiles.create': (_closed({'profileId': _text(), 'displayName': _text(),
                                 'manifest': {'type': 'object'}},
                                ('profileId', 'displayName', 'manifest')),
                        {'command': 'agents profiles', 'operation': 'create',
                         'args': ({'name': 'profileId', 'type': 'string'},
                                  {'name': 'displayName', 'flags': ('--name',), 'type': 'string'},
                                  {'name': 'manifest', 'flags': ('--manifest',), 'type': 'json-file'})}),
    'agents.profiles.rename': (_closed({'profileId': _text(), 'displayName': _text(),
                                 'expectedCatalogRevision': {'type': 'integer'}},
                                ('profileId', 'displayName', 'expectedCatalogRevision')),
                        {'command': 'agents profiles', 'operation': 'rename',
                         'args': ({'name': 'profileId', 'type': 'string'},
                                  {'name': 'displayName', 'flags': ('--name',), 'type': 'string'},
                                  {'name': 'expectedCatalogRevision',
                                   'flags': ('--expected-catalog-revision',),
                                   'type': 'integer'})}),
}


def _descriptor(operation_id):
    schema, cli = OPERATIONS[operation_id]
    return {'id': operation_id, 'inputSchema': schema, 'outputSchema': {'type': 'object'},
            'scopes': [operation_id], 'cli': cli, 'mcp': None}


class State:
    def __init__(self):
        self.profiles = {}
        self.ledger = {}
        self.calls = []
        self.lose_next = False
        self.revoke = False

    def ref(self, profile):
        manifest = profile['manifest']
        digest = 'sha256:' + hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return {'environmentNamespace': 'remote-ns', 'profileId': profile['profileId'],
                'manifestRevision': profile['catalogRevision'], 'contentDigest': digest}


STATE = State()


def _envelope(request_id, command, status='completed', data=None, error=None):
    return {'apiVersion': 'agent-tools/1', 'requestId': request_id, 'command': command,
            'status': status, 'data': data, 'error': error, 'operationRef': None,
            'evidenceRefs': []}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def _send(self, body, status=200):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = json.loads(self.rfile.read(length) or b'{}')
        State = STATE
        if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
            self._send({'jsonrpc': '2.0', 'id': body.get('id'),
                        'error': {'code': 'UNAUTHENTICATED', 'message': 'denied'}}, 403)
            return
        method = body['method']
        if method == 'capabilities.list':
            self._send({'jsonrpc': '2.0', 'id': body['id'], 'result': _envelope(
                body['id'], 'capabilities.list', data={
                    'capabilities': [{'id': 'profiles', 'version': 'remote/1',
                                      'digest': 'sha256:' + '0' * 64,
                                      'operations': sorted(OPERATIONS)}],
                    'operations': [{'id': name, 'scopes': [name],
                                    'cli': OPERATIONS[name][1], 'mcp': None}
                                   for name in sorted(OPERATIONS)]})})
            return
        if method == 'operations.describe':
            operation = body['params']['operationId']
            self._send({'jsonrpc': '2.0', 'id': body['id'], 'result': _envelope(
                body['id'], operation, data={'capability': 'agents',
                                             'operation': _descriptor(operation)})})
            return
        assert method == 'operations.call', method
        operation = body['params']['operationId']
        inputs = body['params']['input']
        State.calls.append((operation, inputs))
        if State.revoke and operation in ('agents.profiles.create', 'agents.profiles.rename'):
            self._send({'jsonrpc': '2.0', 'id': body['id'],
                        'error': {'code': 'FORBIDDEN', 'message': 'denied'}}, 403)
            return
        key = body['id']
        if key in State.ledger:
            recorded_operation, recorded_input, envelope = State.ledger[key]
            if (recorded_operation, recorded_input) != (operation, json.dumps(inputs, sort_keys=True)):
                self._send({'jsonrpc': '2.0', 'id': key,
                            'error': {'code': 'CONFLICT_REQUEST', 'message': 'conflict'}})
                return
            self._send({'jsonrpc': '2.0', 'id': key, 'result': envelope})
            return
        if operation == 'agents.profiles.capabilities':
            envelope = _envelope(key, operation, data={
                'contractVersion': 'profile-json/1', 'schema': {}, 'schemaDigest': 'sha256:' + '0' * 64,
                'environmentNamespace': 'remote-ns',
                'supports': {'profileCatalog': True, 'nodes': False, 'managedInput': False},
                'supportedMethods': sorted(OPERATIONS)})
        elif operation == 'agents.profiles.list':
            entries = [{'profileId': p['profileId'], 'catalogRevision': p['catalogRevision'],
                        'displayName': p['displayName'], 'archivedAt': None,
                        'currentManifestRef': State.ref(p)}
                       for p in State.profiles.values()]
            envelope = _envelope(key, operation, data={'entries': entries})
        elif operation in ('agents.profiles.read', 'agents.profiles.preview'):
            ref = inputs['profileRef']
            profile = State.profiles.get(ref.get('profileId'))
            if profile is None or ref != State.ref(profile):
                envelope = _envelope(key, operation, status='refused', error={
                    'code': 'INVALID_INPUT', 'message': 'Profile reference is invalid', 'retryable': False})
            elif operation == 'agents.profiles.read':
                envelope = _envelope(key, operation, data={
                    'ref': State.ref(profile),
                    'content': {'schemaVersion': '1',
                                'harnessDefinitionRef': profile['manifest']['harnessDefinitionRef'],
                                'declarations': []}})
            else:
                envelope = _envelope(key, operation, status='refused',
                                     data={'profileRef': ref, 'status': 'unresolved',
                                           'referenceCoverage': 'unknown', 'ready': False,
                                           'error': {'code': 'providerUnavailable', 'retryable': False}},
                                     error={'code': 'CAPABILITY_UNSUPPORTED',
                                            'message': 'Profile preview remains unresolved',
                                            'retryable': False})
        elif operation == 'agents.profiles.create':
            profile = {'profileId': inputs['profileId'], 'catalogRevision': 1,
                       'displayName': inputs['displayName'], 'manifest': inputs['manifest']}
            State.profiles[profile['profileId']] = profile
            envelope = _envelope(key, operation, data={
                'profileId': profile['profileId'], 'catalogRevision': 1,
                'displayName': profile['displayName'], 'archivedAt': None,
                'currentManifestRef': State.ref(profile)})
        elif operation == 'agents.profiles.rename':
            profile = State.profiles.get(inputs['profileId'])
            if profile is None or profile['catalogRevision'] != inputs['expectedCatalogRevision']:
                envelope = _envelope(key, operation, status='refused', error={
                    'code': 'CONFLICT', 'message': 'revision conflict', 'retryable': False})
            else:
                profile['catalogRevision'] += 1
                profile['displayName'] = inputs['displayName']
                envelope = _envelope(key, operation, data={
                    'profileId': profile['profileId'],
                    'catalogRevision': profile['catalogRevision'],
                    'displayName': profile['displayName'], 'archivedAt': None,
                    'currentManifestRef': State.ref(profile)})
        else:
            envelope = _envelope(key, operation, status='refused', error={
                'code': 'CAPABILITY_UNSUPPORTED', 'message': 'unsupported', 'retryable': False})
        State.ledger[key] = (operation, json.dumps(inputs, sort_keys=True), envelope)
        if State.lose_next:
            State.lose_next = False
            self.close_connection = True
            return
        self._send({'jsonrpc': '2.0', 'id': key, 'result': envelope})


def _run(argv, stdin=b''):
    out, err = io.StringIO(), io.StringIO()
    import sys
    previous = sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO(stdin), encoding='utf-8')
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = main([str(item) for item in argv])
    finally:
        sys.stdin = previous
    return code, out.getvalue(), err.getvalue()


def _server(tmp_path, monkeypatch):
    STATE.__init__()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('ORDESSA_REMOTE_TOKEN', TOKEN)
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'services': {'local': {
        'endpoint': 'http://127.0.0.1:' + str(server.server_port),
        'tokenEnv': 'ORDESSA_REMOTE_TOKEN'}}}))
    os.chmod(config, 0o600)
    return server, ['--config', str(config), '--service', 'local']


def test_remote_mode_uses_the_same_channel_and_metadata(tmp_path, monkeypatch):
    server, mode = _server(tmp_path, monkeypatch)
    try:
        code, output, error = _run(mode + ['agents', 'profiles', 'list', '--json'])
        assert code == 0, error
        envelope = json.loads(output)
        assert envelope['status'] == 'completed'
        assert envelope['data'] == {'entries': []}
        assert envelope['command'] == 'agents profiles list'
        code, output, _ = _run(mode + ['unknown', 'thing', '--json'])
        assert code == 4 and json.loads(output)['error']['code'] == 'CAPABILITY_UNSUPPORTED'
    finally:
        server.shutdown()
        server.server_close()


def test_remote_profile_create_read_preview_replay_lost_response_and_revocation(tmp_path, monkeypatch):
    server, mode = _server(tmp_path, monkeypatch)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'schemaVersion': '1', 'harnessDefinitionRef': {
        'environmentNamespace': 'remote-ns', 'definitionId': 'kilo', 'revision': '1'},
        'declarations': []}))
    try:
        code, output, _ = _run(mode + ['agents', 'profiles', 'create', 'peer',
                                       '--name', 'Peer', '--manifest', manifest,
                                       '--request-id', 'create-1', '--json'])
        created = json.loads(output)
        assert code == 0 and created['data']['profileId'] == 'peer'
        ref = created['data']['currentManifestRef']
        ref_file = tmp_path / 'ref.json'
        ref_file.write_text(json.dumps(ref))

        code, output, _ = _run(mode + ['agents', 'profiles', 'read', ref_file, '--json'])
        assert code == 0 and json.loads(output)['data']['ref'] == ref

        code, output, _ = _run(mode + ['agents', 'profiles', 'preview', ref_file, '--json'])
        preview = json.loads(output)
        assert code == 4 and preview['status'] == 'refused'
        assert preview['data']['ready'] is False and preview['data']['status'] == 'unresolved'

        code, output, _ = _run(mode + ['call', 'agents.profiles.capabilities', '--input', '-',
                                       '--json'], stdin=b'{}')
        assert code == 0 and 'agents.profiles.create' in json.loads(output)['data']['supportedMethods']

        # Replaying the same request id and input reads the original result.
        revisions = STATE.profiles['peer']['catalogRevision']
        code, output, _ = _run(mode + ['agents', 'profiles', 'create', 'peer',
                                       '--name', 'Peer', '--manifest', manifest,
                                       '--request-id', 'create-1', '--json'])
        assert code == 0 and json.loads(output)['data'] == created['data']
        assert STATE.profiles['peer']['catalogRevision'] == revisions

        # Same request id with different input is a conflict, not a new mutation.
        code, output, _ = _run(mode + ['agents', 'profiles', 'create', 'peer',
                                       '--name', 'Other', '--manifest', manifest,
                                       '--request-id', 'create-1', '--json'])
        assert code == 5 and json.loads(output)['error']['code'] == 'CONFLICT'

        # A committed mutation whose response is lost is UNKNOWN, never a safe retry;
        # the explicit retry with the same id reads the committed result.
        STATE.lose_next = True
        args = mode + ['agents', 'profiles', 'rename', 'peer', '--name', 'Committed',
                       '--expected-catalog-revision', '1', '--request-id', 'lost-1', '--json']
        code, output, _ = _run(args)
        assert code == 6 and json.loads(output)['error']['code'] == 'EFFECT_UNKNOWN'
        assert STATE.profiles['peer']['displayName'] == 'Committed'
        code, output, _ = _run(args)
        assert code == 0 and json.loads(output)['data']['catalogRevision'] == 2
        assert STATE.profiles['peer']['catalogRevision'] == 2

        STATE.revoke = True
        code, output, _ = _run(mode + ['agents', 'profiles', 'rename', 'peer',
                                       '--name', 'Revoked',
                                       '--expected-catalog-revision', '2',
                                       '--request-id', 'revoked-1', '--json'])
        assert code == 2 and json.loads(output)['error']['code'] == 'PERMISSION_DENIED'
        assert STATE.profiles['peer']['displayName'] == 'Committed'
        assert all(operation.startswith('agents.profiles.') for operation, _ in STATE.calls)
    finally:
        server.shutdown()
        server.server_close()
