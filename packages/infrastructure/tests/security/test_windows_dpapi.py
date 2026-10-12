import ctypes
from pathlib import Path
from types import SimpleNamespace
import os
import subprocess

import pytest

from ordessa_infrastructure.security import windows_dpapi as module
from ordessa_infrastructure.security.secrets import MAX_SECRET_BYTES
from ordessa_infrastructure.security.windows_dpapi import WindowsDpapiSecretStore


@pytest.fixture
def simulated(tmp_path, monkeypatch):
    # Only this module sees Windows platform admission. Real OS remains POSIX;
    # there is never a real DPAPI call or whoami/icacls/security-setting change.
    real_os = module.os
    monkeypatch.setattr(module, 'os', SimpleNamespace(name='nt', open=real_os.open,
        fdopen=real_os.fdopen, fsync=real_os.fsync, O_WRONLY=real_os.O_WRONLY,
        O_CREAT=real_os.O_CREAT, O_EXCL=real_os.O_EXCL))
    store = WindowsDpapiSecretStore(tmp_path / 'explicit-root', protect_description='synthetic description')
    protected, acl = [], []
    monkeypatch.setattr(store, '_protect', lambda data: protected.append(data) or b'fake-dpapi:' + data)
    monkeypatch.setattr(store, '_unprotect', lambda data: data.removeprefix(b'fake-dpapi:'))
    monkeypatch.setattr(store, '_protect_acl', lambda path: acl.append(path))
    return store, protected, acl


def test_real_nonwindows_platform_refuses_constructor_without_fallback(tmp_path):
    if os.name == 'nt':
        # This test targets the non-Windows admission branch without changing
        # the actual global OS; real Windows functionality is a separate gate.
        original = module.os
        module.os = SimpleNamespace(name='posix')
        try:
            with pytest.raises(RuntimeError, match='SECRET_STORE_WINDOWS_REQUIRED'):
                WindowsDpapiSecretStore(tmp_path, protect_description='synthetic')
        finally:
            module.os = original
    else:
        with pytest.raises(RuntimeError, match='SECRET_STORE_WINDOWS_REQUIRED'):
            WindowsDpapiSecretStore(tmp_path, protect_description='synthetic')
    assert list(tmp_path.iterdir()) == []


def test_synthetic_roundtrip_explicit_root_original_locator_acl_and_delete(simulated, tmp_path):
    store, protected, acl = simulated
    source = tmp_path / 'synthetic-input'; source.write_bytes(b'synthetic-content')
    assert not store.root.exists()
    credential, locator = store.import_file(source, 'opaque-kind')
    assert credential.startswith('credential_') and len(credential) == len('credential_') + 32
    assert locator == credential + '.dpapi'
    assert store.root == tmp_path / 'explicit-root'
    assert (store.root / locator).read_bytes() == b'fake-dpapi:synthetic-content'
    assert source.read_bytes() == b'synthetic-content'
    assert protected == [b'synthetic-content']
    assert acl == [store.root, store.root / locator]
    assert store.read(locator) == b'synthetic-content'
    store.delete(locator); store.delete(locator)
    assert not (store.root / locator).exists()
    with pytest.raises(ValueError, match='CREDENTIAL_UNAVAILABLE'):
        store.read(locator)


@pytest.mark.parametrize('size', [0, MAX_SECRET_BYTES + 1])
def test_source_bound_is_refused_before_encryption_or_acl(simulated, tmp_path, size):
    store, protected, acl = simulated
    source = tmp_path / 'synthetic-input'; source.write_bytes(b'x' * size)
    with pytest.raises(ValueError, match='CREDENTIAL_SOURCE_OUTSIDE_BOUND'):
        store.import_file(source, 'opaque')
    assert protected == acl == [] and not store.root.exists()


def test_source_symlink_and_directory_are_refused(simulated, tmp_path):
    store, protected, acl = simulated
    actual = tmp_path / 'actual'; actual.write_bytes(b'synthetic')
    link = tmp_path / 'link'; link.symlink_to(actual)
    for source in [link, tmp_path]:
        with pytest.raises(ValueError, match='CREDENTIAL_SOURCE_INVALID'):
            store.import_file(source, 'opaque')
    assert protected == acl == []


@pytest.mark.parametrize('locator', ['../outside.dpapi', 'not-dpapi', '/absolute.dpapi'])
def test_invalid_locator_is_refused_by_read_and_delete(simulated, locator):
    store, _, _ = simulated
    with pytest.raises(ValueError, match='CREDENTIAL_LOCATOR_INVALID'): store.read(locator)
    with pytest.raises(ValueError, match='CREDENTIAL_LOCATOR_INVALID'): store.delete(locator)


def test_encrypted_read_size_bound_is_preserved(simulated):
    store, _, _ = simulated
    store.root.mkdir()
    (store.root / 'credential_synthetic.dpapi').write_bytes(b'x' * (MAX_SECRET_BYTES * 2 + 1))
    with pytest.raises(ValueError, match='CREDENTIAL_UNAVAILABLE'):
        store.read('credential_synthetic.dpapi')


def test_dpapi_calls_preserve_user_scope_ui_flag_description_and_localfree(tmp_path, monkeypatch):
    store = object.__new__(WindowsDpapiSecretStore)
    store.root = tmp_path; store._protect_description = 'caller-selected description'
    buffers, calls, freed = [], [], []

    def output(pointer, data):
        buffer = ctypes.create_string_buffer(data); buffers.append(buffer)
        pointer._obj.cbData = len(data)
        pointer._obj.pbData = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))

    def protect(*args):
        calls.append(('protect', args[1], args[5]))
        assert args[2:5] == (None, None, None)
        output(args[6], b'synthetic-encrypted')
        return True

    def unprotect(*args):
        calls.append(('unprotect', args[1], args[5]))
        assert args[2:5] == (None, None, None)
        output(args[6], b'synthetic-clear')
        return True

    monkeypatch.setattr(module, '_dpapi_functions', lambda: (
        SimpleNamespace(CryptProtectData=protect, CryptUnprotectData=unprotect),
        SimpleNamespace(LocalFree=lambda address: freed.append(address.value))))
    assert store._protect(b'synthetic-clear') == b'synthetic-encrypted'
    assert store._unprotect(b'synthetic-encrypted') == b'synthetic-clear'
    assert calls == [('protect', 'caller-selected description', 0x01), ('unprotect', None, 0x01)]
    assert len(freed) == 2 and all(freed)


def test_dpapi_native_failure_propagates_without_plaintext_fallback(monkeypatch):
    store = object.__new__(WindowsDpapiSecretStore); store._protect_description = 'synthetic'
    failure = OSError('controlled DPAPI failure')
    monkeypatch.setattr(module.ctypes, 'WinError', lambda: failure, raising=False)
    monkeypatch.setattr(module, '_dpapi_functions', lambda: (
        SimpleNamespace(CryptProtectData=lambda *args: False), SimpleNamespace(LocalFree=lambda *args: pytest.fail('no native allocation'))))
    with pytest.raises(OSError) as caught: store._protect(b'synthetic')
    assert caught.value is failure


def test_acl_command_contract_is_observed_only_through_fake_runner(tmp_path, monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout='"synthetic-user","S-1-5-21-100"\n')
    monkeypatch.setattr(module.subprocess, 'run', run)
    WindowsDpapiSecretStore._protect_acl(tmp_path)
    assert calls[0][0] == ['whoami.exe', '/user', '/fo', 'csv', '/nh']
    assert calls[1][0] == ['icacls.exe', str(tmp_path), '/inheritance:r', '/grant:r', '*S-1-5-21-100:(F)']
    assert all(options == dict(check=True, capture_output=True, text=True, timeout=5) for _, options in calls)
