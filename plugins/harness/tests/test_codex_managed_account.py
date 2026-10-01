"""No OAuth/token handling: exercise the native managed-account protocol."""
import json
import os
from pathlib import Path
import sys

import pytest

from ordessa_harness.codex.managed_account import CodexManagedAccount, ManagedAccountUnavailable


@pytest.fixture
def native(tmp_path):
    script = tmp_path / 'peer.py'
    script.write_text('''import json, os, sys, time
mode, audit = sys.argv[1:3]
with open(audit, 'w') as stream:
    json.dump({'argv': sys.argv[3:], 'home': os.environ.get('CODEX_HOME'), 'pid': os.getpid(),
        'api': os.environ.get('OPENAI_API_KEY'), 'token': os.environ.get('CODEX_ACCESS_TOKEN')}, stream)
for line in sys.stdin:
    msg = json.loads(line)
    if 'id' not in msg: continue
    if mode == 'hang': time.sleep(10)
    if mode == 'malformed': print('not-json', flush=True); continue
    if mode == 'oversized': print('x' * 70000, flush=True); continue
    if mode == 'error':
        print(json.dumps({'id': msg['id'], 'error': {'message': 'SECRET-FIXTURE'}}), flush=True); continue
    if msg['method'] == 'initialize': result = {}
    elif msg['method'] == 'account/read':
        with open(audit + '.read', 'w') as stream: json.dump(msg, stream)
        result = {'account': None if mode == 'absent' else {'type': 'apiKey' if mode == 'api' else 'chatgpt',
            'email': 'PRIVATE-FIXTURE'}, 'requiresOpenaiAuth': True}
        if mode == 'invalid': result = {'account': 'broken'}
    else: sys.exit(9)
    print(json.dumps({'id': msg['id'], 'result': result}), flush=True)
''')
    account = tmp_path / 'account'
    account.mkdir(mode=0o700)
    audit = tmp_path / 'audit.json'
    return script, account, audit


def build(native, mode='normal', timeout=2):
    script, account, audit = native
    return CodexManagedAccount(command=(sys.executable, str(script), mode, str(audit)),
        account_directory=account, timeout=timeout)


def test_native_managed_status_is_nonsecret_and_uses_only_owned_account(native, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'SECRET-FIXTURE')
    monkeypatch.setenv('CODEX_ACCESS_TOKEN', 'SECRET-FIXTURE')
    result = build(native).read()
    assert result == {'authenticated': True, 'method': 'chatgpt-managed'}
    assert 'PRIVATE' not in repr(result) and 'SECRET' not in repr(result)
    audit = json.loads(native[2].read_text())
    assert audit['home'] == str(native[1])
    assert audit['api'] is None and audit['token'] is None
    assert audit['argv'] == ['-c', 'cli_auth_credentials_store="keyring"', 'app-server']
    request = json.loads(Path(str(native[2]) + '.read').read_text())
    assert request['params'] == {'refreshToken': False}
    assert list(native[1].iterdir()) == []


def test_refresh_is_a_native_account_read_not_a_host_oauth_request(native):
    assert build(native).read(refresh=True)['authenticated'] is True
    request = json.loads(Path(str(native[2]) + '.read').read_text())
    assert request['method'] == 'account/read'
    assert request['params'] == {'refreshToken': True}


@pytest.mark.parametrize('mode', ['absent', 'api'])
def test_missing_or_api_account_is_not_official_subscription_auth(native, mode):
    assert build(native, mode).read() == {'authenticated': False, 'method': 'chatgpt-managed'}


@pytest.mark.parametrize('mode', ['malformed', 'oversized', 'error', 'invalid', 'hang'])
def test_native_failures_are_bounded_and_never_disclose_provider_output(native, mode):
    with pytest.raises(ManagedAccountUnavailable) as caught:
        build(native, mode, timeout=.25).read()
    assert str(caught.value) == 'CODEX_MANAGED_ACCOUNT_UNAVAILABLE'
    assert caught.value.__cause__ is None
    pid = json.loads(native[2].read_text())['pid']
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize('kind', ['link', 'public', 'missing'])
def test_unsafe_account_scope_is_refused_before_spawn(native, kind):
    if kind == 'link':
        link = native[1].parent / 'link'
        link.symlink_to(native[1])
        account = link
    elif kind == 'public':
        native[1].chmod(0o755)
        account = native[1]
    else:
        account = native[1].parent / 'missing'
    script, _, audit = native
    with pytest.raises(ManagedAccountUnavailable):
        CodexManagedAccount(command=(sys.executable, str(script), 'normal', str(audit)),
            account_directory=account).read()
    assert not audit.exists()


def test_refresh_flag_refuses_integer_alias(native):
    with pytest.raises(ManagedAccountUnavailable):
        build(native).read(refresh=1)
    assert not native[2].exists()
