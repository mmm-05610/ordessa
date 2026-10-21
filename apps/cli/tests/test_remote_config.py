"""Remote-mode configuration, transport and redaction negatives (GAP-G1).

Every case here is local: no Ordessa service is started and no external
network request is made. Local configuration refusals are proven to happen
before the client is constructed (the counting client records zero attempts);
the unreachable-endpoint case connects only to a loopback port that is bound
but never listening, so the kernel refuses the connection immediately.

The wire cases replace the client's opener (``opener.open``) with an in-process
response, so even a "server message" is delivered without a socket.

Where the current implementation differs from the contract one would expect,
the test records the real behaviour and says so; the deviation is reported
separately instead of being silently asserted away.
"""
from __future__ import annotations

import io
import json
import socket
from contextlib import redirect_stderr, redirect_stdout

import pytest

import ordessa_cli.cli as cli
from ordessa_system_access_client import CapabilityClient, ClientError, load_service

# A fake bearer that must never appear on a failure surface.
SECRET = 'fixture-private-bearer-do-not-print'
TOKEN_ENV = 'ORDESSA_TEST_TOKEN'
LOOPBACK = 'http://127.0.0.1:1'
COMMAND = ['agents', 'profiles', 'list']


def _write_config(tmp_path, body, *, mode=0o600, name='config.json'):
    path = tmp_path / name
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    path.chmod(mode)
    return path


def _config(tmp_path, endpoint=LOOPBACK, token_env=TOKEN_ENV, *, mode=0o600):
    return _write_config(tmp_path, {
        'services': {'local': {'endpoint': endpoint, 'tokenEnv': token_env}}},
        mode=mode)


def _mode(config):
    return ['--config', str(config), '--service', 'local']


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main([str(item) for item in argv])
    return code, out.getvalue(), err.getvalue()


def _assert_no_secret(*texts):
    assert SECRET not in ''.join(texts)


class _Response:
    """Minimal stand-in for the urllib response used by ``CapabilityClient``."""

    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self, limit=-1):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _install_client(monkeypatch, responder=None):
    """Install a counting client; returns the recorded transport attempts.

    The subclass keeps the real request construction and validation, clamps
    the timeout so nothing can hang, and counts every ``opener.open`` call so
    a retry would be visible as a second attempt. When ``responder`` is given
    the wire answer is produced in-process (``responder(decoded_body) -> bytes``)
    and no socket is touched at all.
    """
    attempts = []

    class CountingClient(CapabilityClient):
        def __init__(self, service, *, timeout=10):
            super().__init__(service, timeout=min(timeout, 0.2))
            send = self.opener.open

            def open_(request, *args, **kwargs):
                attempts.append(request.full_url)
                if responder is not None:
                    return _Response(responder(json.loads(request.data)))
                return send(request, *args, **kwargs)

            self.opener.open = open_

    monkeypatch.setattr(cli, 'CapabilityClient', CountingClient)
    return attempts


def _bound_unreachable_socket():
    """A bound, never-listening loopback socket: connects get ECONNREFUSED."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(('127.0.0.1', 0))
    return probe, probe.getsockname()[1]


# ---------------------------------------------------------------------------
# 1. symlinked configuration
# ---------------------------------------------------------------------------

def test_symlinked_config_is_refused_locally(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    target = _config(tmp_path)
    link = tmp_path / 'link.json'
    link.symlink_to(target)

    with pytest.raises(ClientError) as caught:
        load_service(str(link), 'local')
    assert (caught.value.code, caught.value.exit_code) == ('CONFIG_INVALID', 2)

    attempts = _install_client(monkeypatch)
    code, out, err = _run(COMMAND + _mode(link) + ['--json'])
    assert code == 2
    assert json.loads(out)['error']['code'] == 'INVALID_INPUT'
    assert attempts == []  # refused before the client could be constructed
    _assert_no_secret(out, err)


# ---------------------------------------------------------------------------
# 2. over-wide file permissions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('mode', [0o620, 0o602], ids=['group-write', 'other-write'])
def test_group_or_other_writable_config_is_refused_locally(tmp_path, monkeypatch, mode):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    path = _config(tmp_path, mode=mode)

    with pytest.raises(ClientError, match='group or other write access') as caught:
        load_service(str(path), 'local')
    assert (caught.value.code, caught.value.exit_code) == ('CONFIG_PERMISSIONS', 2)

    attempts = _install_client(monkeypatch)
    code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    assert code == 2
    assert json.loads(out)['error']['code'] == 'INVALID_INPUT'
    assert attempts == []
    _assert_no_secret(out, err)


# ---------------------------------------------------------------------------
# 3. plaintext secret / unknown keys / foreign shape
# ---------------------------------------------------------------------------

_ENTRY = {'endpoint': LOOPBACK, 'tokenEnv': TOKEN_ENV}
_FOREIGN_SHAPES = [
    ('plaintext-token-in-entry', {'services': {'local': {**_ENTRY, 'token': SECRET}}}),
    ('unknown-entry-key', {'services': {'local': {**_ENTRY, 'headers': {}}}}),
    ('unknown-top-level-key', {'services': {'local': _ENTRY}, 'token': SECRET}),
    ('wrong-top-level-key', {'service': {'local': _ENTRY}}),
    ('entry-is-a-string', {'services': {'local': LOOPBACK}}),
    ('missing-token-env', {'services': {'local': {'endpoint': LOOPBACK}}}),
    ('illegal-service-name', {'services': {'local': _ENTRY, 'bad name!': _ENTRY}}),
    ('services-not-an-object', {'services': []}),
    ('top-level-is-a-list', [{'services': {}}]),
    ('truncated-json', '{"services": {"local": '),
    ('duplicate-member', '{"services": {}, "services": {}}'),
]


@pytest.mark.parametrize('body', [body for _, body in _FOREIGN_SHAPES],
                         ids=[name for name, _ in _FOREIGN_SHAPES])
def test_config_with_plaintext_token_unknown_key_or_foreign_shape_is_refused(
        tmp_path, monkeypatch, body):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    path = _write_config(tmp_path, body)

    with pytest.raises(ClientError) as caught:
        load_service(str(path), 'local')
    assert (caught.value.code, caught.value.exit_code) == ('CONFIG_INVALID', 2)

    attempts = _install_client(monkeypatch)
    code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    assert code == 2
    assert json.loads(out)['error']['code'] == 'INVALID_INPUT'
    assert attempts == []
    _assert_no_secret(out, err)


def test_missing_or_non_regular_config_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    attempts = _install_client(monkeypatch)
    for path in (tmp_path / 'absent.json', tmp_path):
        with pytest.raises(ClientError) as caught:
            load_service(str(path), 'local')
        assert (caught.value.code, caught.value.exit_code) == ('CONFIG_INVALID', 2)
        code, out, err = _run(COMMAND + _mode(path) + ['--json'])
        assert code == 2
        assert json.loads(out)['error']['code'] == 'INVALID_INPUT'
        _assert_no_secret(out, err)
    assert attempts == []


# ---------------------------------------------------------------------------
# 4. endpoint shape / transport security
# ---------------------------------------------------------------------------

_REFUSED_ENDPOINTS = [
    ('non-loopback-http', 'http://example.com'),
    ('dns-name-http', 'http://localhost'),
    ('wildcard-http', 'http://0.0.0.0:8080'),
    ('userinfo', 'https://user:pass@example.com'),
    ('username-only', 'https://user@example.com'),
    ('query', 'https://example.com?token=' + SECRET),
    ('fragment', 'https://example.com#frag'),
    ('path', 'https://example.com/v1/wire'),
    ('port-out-of-range', 'https://example.com:99999'),
    ('non-numeric-port', 'http://127.0.0.1:not-a-port'),
    ('unsupported-scheme', 'ftp://127.0.0.1:1'),
    ('whitespace', 'http://127.0.0.1:1 '),
    ('relative', '127.0.0.1:1'),
]


@pytest.mark.parametrize('endpoint', [value for _, value in _REFUSED_ENDPOINTS],
                         ids=[name for name, _ in _REFUSED_ENDPOINTS])
def test_insecure_or_ambiguous_endpoint_is_refused_before_connecting(
        tmp_path, monkeypatch, endpoint):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    path = _config(tmp_path, endpoint=endpoint)

    with pytest.raises(ClientError) as caught:
        load_service(str(path), 'local')
    assert (caught.value.code, caught.value.exit_code) == ('CONFIG_INVALID', 2)

    attempts = _install_client(monkeypatch)
    code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    assert code == 2
    assert json.loads(out)['error']['code'] == 'INVALID_INPUT'
    assert attempts == []  # no connection attempt for a locally refused endpoint
    _assert_no_secret(out, err)


@pytest.mark.parametrize('endpoint', [
    'http://127.0.0.1:1',
    'http://127.0.0.1:1/',
    'http://[::1]:1',
    'https://example.com',
], ids=['loopback', 'loopback-root-path', 'loopback-ipv6', 'tls-remote'])
def test_loopback_http_and_tls_remote_endpoints_are_accepted(tmp_path, monkeypatch, endpoint):
    # Positive control: the refusals above are specific, not a blanket reject.
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    service = load_service(str(_config(tmp_path, endpoint=endpoint)), 'local')
    assert service.alias == 'local'
    assert service.token == SECRET
    assert service.endpoint == endpoint.rstrip('/')


# ---------------------------------------------------------------------------
# 5. token environment
# ---------------------------------------------------------------------------

_MISSING_OR_INVALID_TOKENS = [
    ('unset', None),
    ('empty', ''),
    ('space', 'token with space'),
    ('non-ascii', 'tökén-value'),
    ('control-char', 'token\nvalue'),
]


@pytest.mark.parametrize('value', [value for _, value in _MISSING_OR_INVALID_TOKENS],
                         ids=[name for name, _ in _MISSING_OR_INVALID_TOKENS])
def test_missing_or_invalid_token_environment_value_is_refused(tmp_path, monkeypatch, value):
    if value is None:
        monkeypatch.delenv(TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(TOKEN_ENV, value)
    path = _config(tmp_path)

    with pytest.raises(ClientError) as caught:
        load_service(str(path), 'local')
    assert (caught.value.code, caught.value.exit_code) == ('TOKEN_UNAVAILABLE', 3)

    attempts = _install_client(monkeypatch)
    code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    # The CLI contract maps the client's authorization exit (3) to 2.
    assert code == 2
    assert json.loads(out)['error']['code'] == 'PERMISSION_DENIED'
    assert attempts == []
    _assert_no_secret(out, err)


_ILLEGAL_TOKEN_ENV_NAMES = ['TOKEN-NAME', '1TOKEN', '', 'TOKEN NAME', 'TOKEN\nNAME', 'TOKEN+NAME']


@pytest.mark.parametrize('name', _ILLEGAL_TOKEN_ENV_NAMES,
                         ids=['hyphen', 'leading-digit', 'empty', 'space', 'newline', 'plus'])
def test_illegal_token_environment_name_is_refused(tmp_path, monkeypatch, name):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    # The name is invalid even on a service that is not selected.
    body = {'services': {
        'local': {'endpoint': LOOPBACK, 'tokenEnv': TOKEN_ENV},
        'other': {'endpoint': LOOPBACK, 'tokenEnv': name},
    }}
    path = _write_config(tmp_path, body)

    with pytest.raises(ClientError) as caught:
        load_service(str(path), 'local')
    assert (caught.value.code, caught.value.exit_code) == ('CONFIG_INVALID', 2)

    attempts = _install_client(monkeypatch)
    code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    assert code == 2
    assert json.loads(out)['error']['code'] == 'INVALID_INPUT'
    assert attempts == []
    _assert_no_secret(out, err)


def test_unconfigured_service_alias_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    path = _write_config(tmp_path, {'services': {
        'other': {'endpoint': LOOPBACK, 'tokenEnv': TOKEN_ENV}}})

    with pytest.raises(ClientError) as caught:
        load_service(str(path), 'local')
    assert (caught.value.code, caught.value.exit_code) == ('SERVICE_NOT_CONFIGURED', 2)

    attempts = _install_client(monkeypatch)
    code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    assert code == 2
    assert json.loads(out)['error']['code'] == 'INVALID_INPUT'
    assert attempts == []
    _assert_no_secret(out, err)


# ---------------------------------------------------------------------------
# 6. unreachable endpoint: typed envelope, exit 4, zero retries
# ---------------------------------------------------------------------------

def test_unreachable_endpoint_yields_typed_envelope_without_retry(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    attempts = _install_client(monkeypatch)
    probe, port = _bound_unreachable_socket()
    try:
        path = _config(tmp_path, endpoint='http://127.0.0.1:%d' % port)
        code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    finally:
        probe.close()

    assert code == 4
    envelope = json.loads(out)
    assert envelope['apiVersion'] == 'agent-tools/1'
    assert envelope['status'] == 'refused'
    assert envelope['data'] is None
    assert envelope['error']['retryable'] is False
    # Current mapping collapses the client's SERVICE_UNAVAILABLE to the exit-4
    # contract code; reported as a deviation, not asserted away.
    assert envelope['error']['code'] == 'CAPABILITY_UNSUPPORTED'
    # Exactly one transport attempt: a retry would append a second entry.
    assert attempts == ['http://127.0.0.1:%d/wire/v1/capabilities.list' % port]
    assert 'Traceback' not in err
    _assert_no_secret(out, err)


def test_global_timeout_option_does_not_bound_the_remote_transport(tmp_path, monkeypatch):
    """Recorded current behaviour: the remote client is built with a fixed timeout.

    The retired standalone remote runtime passed ``--timeout`` into
    ``CapabilityClient(timeout=...)``. The unified CLI's ``--timeout`` is a
    channel operation bound that never reaches the transport, so a hanging
    remote endpoint is only bounded by the hard-coded 30 s. Pinned here so a
    deliberate fix shows up as a test change.
    """
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    path = _config(tmp_path)
    seen = []

    class RecordingClient(CapabilityClient):
        def __init__(self, service, *, timeout=10):
            seen.append(timeout)
            super().__init__(service, timeout=0.2)
            self.opener.open = lambda request, *args, **kwargs: _Response(
                json.dumps({'jsonrpc': '2.0', 'id': json.loads(request.data)['id'],
                            'error': {'code': 'CONFLICT_VERSION',
                                      'message': 'refused'}}).encode())

    monkeypatch.setattr(cli, 'CapabilityClient', RecordingClient)
    code, out, err = _run(COMMAND + _mode(path) + ['--timeout', '0.05', '--json'])

    assert code == 5
    assert seen == [30]  # fixed client timeout, not the requested 0.05 s
    _assert_no_secret(out, err)


# ---------------------------------------------------------------------------
# 7. _client_failure exit-code -> contract-code mapping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('client_exit, contract_code, process_exit', [
    (2, 'INVALID_INPUT', 2),
    (3, 'PERMISSION_DENIED', 2),
    (4, 'CAPABILITY_UNSUPPORTED', 4),
    (5, 'CONFLICT', 5),
    (6, 'EFFECT_UNKNOWN', 6),
    (7, 'OBSERVATION_TIMEOUT', 7),
    (9, 'INVALID_INPUT', 2),  # unknown client exit falls back to the input refusal
])
def test_client_failure_maps_to_contract_code_and_exit(
        tmp_path, monkeypatch, client_exit, contract_code, process_exit):
    path = _config(tmp_path)

    def refuse(*_args, **_kwargs):
        # The CLI contract derives the envelope code from exit_code only; the
        # client's own code name is intentionally not surfaced.
        raise ClientError('CLIENT_SIDE_CODE', 'Service refused the wire request', client_exit)

    monkeypatch.setattr(cli, 'load_service', refuse)
    code, out, err = _run(COMMAND + _mode(path) + ['--json'])

    assert code == process_exit
    envelope = json.loads(out)
    assert envelope['status'] == 'refused'
    assert envelope['error']['code'] == contract_code
    assert envelope['error']['message'] == 'Service refused the wire request'
    assert envelope['error']['retryable'] is False
    assert 'CLIENT_SIDE_CODE' not in out + err
    assert 'ordessa: Service refused the wire request' in err


# ---------------------------------------------------------------------------
# 8. no token / raw server message on any failure surface
# ---------------------------------------------------------------------------

_FAILURE_SETUPS = ['symlink', 'group-write', 'plaintext-token', 'secret-in-endpoint',
                   'missing-token', 'unreachable-endpoint']


def _failure_config(tmp_path, monkeypatch, kind):
    """Return ``(config_path, probe_or_none)`` for one local failure surface."""
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    if kind == 'symlink':
        target = _config(tmp_path)
        link = tmp_path / 'link.json'
        link.symlink_to(target)
        return link, None
    if kind == 'group-write':
        return _config(tmp_path, mode=0o620), None
    if kind == 'plaintext-token':
        return _write_config(tmp_path, {'services': {'local': {
            'endpoint': LOOPBACK, 'tokenEnv': TOKEN_ENV, 'token': SECRET}}}), None
    if kind == 'secret-in-endpoint':
        return _config(tmp_path, endpoint='https://example.com/?token=' + SECRET), None
    if kind == 'missing-token':
        monkeypatch.delenv(TOKEN_ENV, raising=False)
        return _config(tmp_path), None
    if kind == 'unreachable-endpoint':
        probe, port = _bound_unreachable_socket()
        return _config(tmp_path, endpoint='http://127.0.0.1:%d' % port), probe
    raise AssertionError(kind)


@pytest.mark.parametrize('kind', _FAILURE_SETUPS)
def test_local_failure_surfaces_never_leak_the_token_value(tmp_path, monkeypatch, kind):
    path, probe = _failure_config(tmp_path, monkeypatch, kind)
    try:
        attempts = _install_client(monkeypatch)
        code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    finally:
        if probe is not None:
            probe.close()

    assert code in (2, 4)
    _assert_no_secret(out, err)
    assert '"retryable": false' in out  # a typed refusal, not a traceback
    if kind != 'unreachable-endpoint':
        assert attempts == []


def _wire_responder(payload):
    return lambda body: json.dumps(payload(body)).encode()


def test_wire_failure_never_leaks_token_or_raw_server_message(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    path = _config(tmp_path)

    # A server error message containing the bearer must be replaced by the
    # client's frozen refusal text before it reaches stdout/stderr.
    def conflict(body):
        return {'jsonrpc': '2.0', 'id': body['id'],
                'error': {'code': 'CONFLICT_VERSION', 'message': SECRET}}

    attempts = _install_client(monkeypatch, _wire_responder(conflict))
    code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    assert code == 5
    envelope = json.loads(out)
    assert envelope['error']['code'] == 'CONFLICT'
    assert envelope['error']['message'] == (
        'Service refused conflicting revision, request, or target preconditions')
    _assert_no_secret(out, err)
    assert 'CONFLICT_VERSION' not in out + err  # raw server code is not exposed
    assert len(attempts) == 1  # one refusal answer is not retried


def test_wire_envelope_containing_the_token_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    path = _config(tmp_path)

    def leaky(body):
        return {'jsonrpc': '2.0', 'id': body['id'], 'result': {
            'apiVersion': 'agent-tools/1', 'requestId': body['id'],
            'command': 'capabilities.list', 'status': 'completed',
            'data': {'leak': SECRET}, 'error': None, 'operationRef': None,
            'evidenceRefs': []}}

    attempts = _install_client(monkeypatch, _wire_responder(leaky))
    code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    assert code == 4
    assert json.loads(out)['error']['message'] == 'Invalid capability envelope'
    _assert_no_secret(out, err)
    assert len(attempts) == 1


# ---------------------------------------------------------------------------
# Mode-selector negatives (configuration entry, no connection)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('argv, message', [
    (COMMAND + ['--config'], 'needs a value'),
    (COMMAND + ['--config', 'CONFIG'], 'must be supplied together'),
    (COMMAND + ['--config', 'CONFIG', '--service', 'local', '--state', 'STATE'],
     'mutually exclusive'),
])
def test_remote_mode_selector_negatives_are_refused_locally(tmp_path, monkeypatch, argv, message):
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    config = _config(tmp_path)
    placeholders = {'CONFIG': str(config), 'STATE': str(tmp_path / 'state')}
    argv = [placeholders.get(token, token) for token in argv]
    attempts = _install_client(monkeypatch)

    code, out, err = _run(argv)
    assert code == 2
    assert message in err
    assert attempts == []
    _assert_no_secret(out, err)


# ---------------------------------------------------------------------------
# Recorded current behaviour (deviation candidate)
# ---------------------------------------------------------------------------

def test_remote_discovery_refusal_is_reported_as_invalid_input(tmp_path, monkeypatch):
    """Recorded current behaviour: discovery refusal exits 2 with INVALID_INPUT.

    ``composition.remote.RemoteRefused`` declares ``code = 'CAPABILITY_UNSUPPORTED'``
    and its docstring says composition "refuses" instead of falling back, but
    ``cli.main`` routes it through the generic local-composition branch and
    publishes INVALID_INPUT/2. Reported as a deviation; this test pins the
    real behaviour so a fix is visible as a deliberate change.
    """
    monkeypatch.setenv(TOKEN_ENV, SECRET)
    path = _config(tmp_path)

    def refused_listing(body):
        return {'jsonrpc': '2.0', 'id': body['id'], 'result': {
            'apiVersion': 'agent-tools/1', 'requestId': body['id'],
            'command': 'capabilities.list', 'status': 'refused', 'data': None,
            'error': {'code': 'CAPABILITY_UNSUPPORTED', 'message': 'refused',
                      'retryable': False},
            'operationRef': None, 'evidenceRefs': []}}

    attempts = _install_client(monkeypatch, _wire_responder(refused_listing))
    code, out, err = _run(COMMAND + _mode(path) + ['--json'])
    assert code == 2
    envelope = json.loads(out)
    assert envelope['error']['code'] == 'INVALID_INPUT'
    assert envelope['error']['message'] == 'remote capability discovery is unavailable'
    assert len(attempts) == 1  # discovery refusal is not retried either
    _assert_no_secret(out, err)
