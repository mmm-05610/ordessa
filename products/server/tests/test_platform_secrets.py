"""No real bus/keyring access; persistent fake collection + socket-only fences."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from pacthold.storage.secrets import MAX_SECRET_BYTES, SecretLocatorUnavailable
from ordessa_server_product import platform_secrets as module
from ordessa_server_product.platform_secrets import LinuxSecretServiceStore, SecretServiceUnavailable


class Collection:
    def __init__(self):
        self.items, self.searches = [], []
        self.locked = False
        self.session = SimpleNamespace(encrypted=True)
        self.creates = 0
    def is_locked(self):
        return self.locked
    def search_items(self, attrs):
        assert set(attrs) == {'application', 'ordessa.data-root', 'ordessa.locator', 'ordessa.schema'}
        assert attrs['application'] == 'org.ordessa.server'
        self.searches.append(dict(attrs))
        return iter(item for item in self.items if all(item.attrs.get(k) == v for k, v in attrs.items()))
    def create_item(self, label, attrs, secret, *, replace, content_type):
        assert label == 'Ordessa credential' and replace is False
        assert content_type == 'application/octet-stream'
        self.creates += 1
        item = Item(self, attrs, secret)
        self.items.append(item)
        return item


class Item:
    def __init__(self, collection, attrs, secret):
        self.collection, self.attrs, self.secret = collection, dict(attrs), secret
        self.locked, self.reads, self.deletes = False, 0, 0
    def get_attributes(self):
        return dict(self.attrs)
    def is_locked(self):
        return self.locked
    def get_secret(self):
        self.reads += 1
        return self.secret
    def delete(self):
        self.deletes += 1
        self.collection.items.remove(self)


@pytest.fixture
def backend(tmp_path):
    collection = Collection()
    calls = []
    @contextmanager
    def factory():
        calls.append('opened')
        yield collection
    root = tmp_path / 'data'
    root.mkdir()
    source = tmp_path / 'credential-input'
    source.write_bytes(b'synthetic-private-content')
    store = LinuxSecretServiceStore(root, _backend_factory=factory)
    return SimpleNamespace(collection=collection, factory=factory, calls=calls, root=root, source=source, store=store)


def test_roundtrip_reopen_delete_and_only_exact_own_attributes(backend):
    b = backend
    cid, locator = b.store.import_file(b.source, 'api_key')
    assert cid.startswith('credential_') and b.source.read_bytes() == b'synthetic-private-content'
    assert b.store.read(locator) == b'synthetic-private-content'
    reopened = LinuxSecretServiceStore(b.root, _backend_factory=b.factory)
    assert reopened.read(locator) == b'synthetic-private-content'
    foreign = Item(b.collection, {'application': 'other-app'}, b'foreign')
    b.collection.items.append(foreign)
    reopened.delete(locator)
    reopened.delete(locator)
    assert b.collection.items == [foreign] and foreign.reads == foreign.deletes == 0
    with pytest.raises(SecretLocatorUnavailable) as error: reopened.read(locator)
    assert error.value.code == 'CREDENTIAL_NOT_AVAILABLE'


def test_transient_bytes_import_requires_no_plaintext_source_file(backend):
    backend.source.unlink()
    credential_id, locator = backend.store.import_bytes(b'synthetic-byte-only-key', 'api-key')
    assert credential_id.startswith('credential_')
    assert backend.store.read(locator) == b'synthetic-byte-only-key'
    assert not backend.source.exists()
    backend.store.delete(locator)


@pytest.mark.parametrize('content', [b'', '', bytearray(b'key'), b'x' * (MAX_SECRET_BYTES + 1)])
def test_transient_bytes_invalid_input_never_opens_keyring(backend, content):
    with pytest.raises(ValueError):
        backend.store.import_bytes(content, 'api-key')
    assert backend.collection.items == []


def test_explicit_gnome_generic_schema_is_allowed_but_other_schema_refused(backend):
    b = backend
    _, locator = b.store.import_file(b.source, 'api_key')
    item = b.collection.items[0]
    item.attrs['xdg:schema'] = 'org.freedesktop.Secret.Generic'
    assert b.store.read(locator) == b'synthetic-private-content'
    item.attrs['xdg:schema'] = 'other-app-schema'
    with pytest.raises(SecretServiceUnavailable) as error: b.store.read(locator)
    assert error.value.code == 'SECRET_STORE_INTEGRITY'
    assert item.reads == 1


@pytest.mark.parametrize('cleanup_fails', [False, True])
def test_failed_postcreate_verification_cleans_only_exact_created_item(backend, monkeypatch, cleanup_fails):
    b = backend
    original = b.collection.create_item
    created = []
    def create(*args, **kwargs):
        item = original(*args, **kwargs)
        created.append(item)
        b.collection.items.append(Item(b.collection, item.attrs, b'foreign-duplicate'))
        if cleanup_fails:
            def failed_delete(): raise RuntimeError('synthetic-provider-secret-error')
            item.delete = failed_delete
        return item
    monkeypatch.setattr(b.collection, 'create_item', create)
    with pytest.raises(SecretServiceUnavailable) as error: b.store.import_file(b.source, 'api_key')
    assert error.value.code == 'SECRET_STORE_INTEGRITY'
    assert 'synthetic' not in str(error.value) + repr(vars(error.value))
    if cleanup_fails:
        assert error.value.cleanup_code == 'SECRET_STORE_UNAVAILABLE'
        assert len(b.collection.items) == 2
    else:
        assert created[0].deletes == 1 and len(b.collection.items) == 1
        assert b.collection.items[0] is not created[0] and b.collection.items[0].deletes == 0


def test_canonical_data_root_alias_and_wrong_root_never_open_backend(backend, tmp_path):
    b = backend
    _, locator = b.store.import_file(b.source, 'api-key')
    alias = tmp_path / 'root-alias'
    alias.symlink_to(b.root, target_is_directory=True)
    assert LinuxSecretServiceStore(alias, _backend_factory=b.factory).read(locator) == b'synthetic-private-content'
    count = len(b.calls)
    other = LinuxSecretServiceStore(tmp_path / 'different-root', _backend_factory=b.factory)
    with pytest.raises(ValueError, match='CREDENTIAL_LOCATOR_INVALID'): other.read(locator)
    with pytest.raises(ValueError): other.delete(locator)
    assert len(b.calls) == count


@pytest.mark.parametrize('locator', ['raw-secret', '../item', 'secret-service:v1:bad:bad', None, '', 5])
def test_malformed_locator_has_no_bus_or_secret_access(backend, locator):
    with pytest.raises(ValueError, match='CREDENTIAL_LOCATOR_INVALID'): backend.store.read(locator)
    assert not backend.calls


@pytest.mark.parametrize('change', ['duplicate', 'wrong-kind', 'foreign-extra', 'locked-item', 'locked-collection', 'oversize', 'malformed'])
def test_item_fences_fail_closed_before_wrong_secret_or_delete(backend, change):
    b = backend
    _, locator = b.store.import_file(b.source, 'api_key')
    item = b.collection.items[0]
    if change == 'duplicate': b.collection.items.append(Item(b.collection, item.attrs, b'duplicate'))
    if change == 'wrong-kind': item.attrs['ordessa.kind'] = '../secret'
    if change == 'foreign-extra': item.attrs['extra'] = 'foreign'
    if change == 'locked-item': item.locked = True
    if change == 'locked-collection': b.collection.locked = True
    if change == 'oversize': item.secret = b'x' * (MAX_SECRET_BYTES + 1)
    if change == 'malformed': item.secret = 'not-bytes'
    with pytest.raises(SecretServiceUnavailable) as error: b.store.read(locator)
    assert error.value.code == ('SECRET_STORE_LOCKED' if change.startswith('locked') else 'SECRET_STORE_INTEGRITY')
    assert 'synthetic' not in str(error.value)
    if change not in ('oversize', 'malformed'):
        assert item.reads == 0
        with pytest.raises(SecretServiceUnavailable): b.store.delete(locator)
        assert item.deletes == 0


@pytest.mark.parametrize('problem', ['locked', 'unencrypted', 'unavailable', 'timeout', 'raw-value-error'])
def test_unavailable_backend_never_imports_or_logs_secret(backend, problem):
    b = backend
    if problem == 'locked': b.collection.locked = True
    if problem == 'unencrypted': b.collection.session.encrypted = False
    if problem in ('unavailable', 'timeout', 'raw-value-error'):
        @contextmanager
        def factory():
            if problem == 'timeout': raise TimeoutError('synthetic-private-provider-message')
            if problem == 'raw-value-error': raise ValueError('synthetic-private-provider-message')
            raise RuntimeError('synthetic-private-provider-message')
            yield
        b.store._backend_factory = factory
    with pytest.raises(SecretServiceUnavailable) as error: b.store.import_file(b.source, 'api_key')
    assert error.value.code in ('SECRET_STORE_UNAVAILABLE', 'SECRET_STORE_LOCKED', 'SECRET_STORE_TIMEOUT')
    assert 'synthetic' not in str(error.value)
    assert b.collection.creates == 0


def test_availability_is_lazy_and_never_searches_or_reads_items(backend, monkeypatch, tmp_path):
    b = backend
    b.store.check_available()
    assert b.calls == ['opened'] and not b.collection.searches and b.collection.creates == 0
    monkeypatch.setattr(Path, 'resolve', lambda *args, **kwargs: pytest.fail('Constructor touched filesystem'))
    monkeypatch.setattr(module, '_default_collection', lambda: pytest.fail('Constructor opened bus'))
    store = LinuxSecretServiceStore(tmp_path / 'not-created')
    assert store._root_namespace is None
    monkeypatch.setattr(module.sys, 'platform', 'linux')
    assert isinstance(module.product_secret_store(tmp_path), LinuxSecretServiceStore)
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    assert module.product_secret_store(tmp_path) is None


@pytest.mark.parametrize('problem', ['empty', 'oversize', 'directory', 'symlink', 'parent-symlink', 'missing'])
def test_source_path_and_size_guards_before_backend(backend, tmp_path, problem):
    b = backend
    source = b.source
    if problem == 'empty': source.write_bytes(b'')
    if problem == 'oversize': source.write_bytes(b'x' * (MAX_SECRET_BYTES + 1))
    if problem == 'directory': source = tmp_path
    if problem == 'symlink':
        source = tmp_path / 'link'
        source.symlink_to(b.source)
    if problem == 'parent-symlink':
        alias = tmp_path / 'alias'
        alias.symlink_to(tmp_path, target_is_directory=True)
        source = alias / b.source.name
    if problem == 'missing': source = tmp_path / 'missing'
    with pytest.raises(ValueError): b.store.import_file(source, 'api_key')
    assert not b.calls and b.collection.creates == 0


def test_source_swap_during_read_refuses_before_backend(backend, monkeypatch):
    b = backend
    real_read = module.os.read
    changed = False
    def swap(fd, size):
        nonlocal changed
        data = real_read(fd, size)
        if not changed:
            changed = True
            b.source.unlink()
            b.source.write_bytes(b'replaced-private-source')
        return data
    monkeypatch.setattr(module.os, 'read', swap)
    with pytest.raises(ValueError, match='CREDENTIAL_SOURCE_CHANGED'): b.store.import_file(b.source, 'api_key')
    assert not b.calls


def test_source_exact_limit_and_invalid_kind(backend):
    b = backend
    b.source.write_bytes(b'x' * MAX_SECRET_BYTES)
    _, locator = b.store.import_file(b.source, 'api_key')
    assert len(b.store.read(locator)) == MAX_SECRET_BYTES
    count = b.collection.creates
    with pytest.raises(ValueError, match='CREDENTIAL_KIND_INVALID'): b.store.import_file(b.source, 'secret\nkind')
    assert b.collection.creates == count


@pytest.mark.parametrize('member,body', [('OpenSession', ('plain', ('s', ''))), ('Prompt', ('',)),
    ('Unlock', ([],)), ('CreateCollection', ({}, 'default'))])
def test_forbidden_protocol_calls_are_blocked_before_send(member, body):
    with pytest.raises(SecretServiceUnavailable) as error: module._guard_call(member, body)
    assert error.value.code == 'SECRET_STORE_UNAVAILABLE'


@pytest.mark.parametrize('member,body', [('CreateItem', ('/item', '/prompt')), ('Delete', ('/prompt',))])
def test_prompt_producing_replies_cannot_report_success(member, body):
    with pytest.raises(SecretServiceUnavailable): module._guard_reply(member, body)


def test_real_jeepney_constructor_hello_and_reply_calls_have_timeouts(monkeypatch):
    # In-memory socketpair only: no session bus/keyring access.
    import socket
    import jeepney.io.blocking as blocking
    from jeepney import new_method_call, new_method_return, DBusAddress
    from jeepney.low_level import HeaderFields
    left, right = socket.socketpair()
    calls, auth = [], []
    monkeypatch.setattr(blocking, 'get_bus', lambda bus: 'controlled-address')
    def prepare(address, *, timeout):
        auth.append((address, timeout))
        return left
    monkeypatch.setattr(blocking, 'prep_socket', prepare)
    def reply(self, message, *, timeout=None):
        calls.append((message.header.fields[HeaderFields.member], timeout, self.sock.gettimeout()))
        return new_method_return(message, 's', (':1.controlled',))
    monkeypatch.setattr(blocking.DBusConnection, 'send_and_get_reply', reply)
    conn = module._bounded_connection()
    try:
        assert auth == [('controlled-address', module.CALL_TIMEOUT)]
        assert calls[0][0] == 'Hello' and 0 < calls[0][1] <= module.CALL_TIMEOUT
        assert calls[0][2] == calls[0][1]
        msg = new_method_call(DBusAddress('/controlled', 'controlled.service', 'controlled.interface'), 'Prompt', 's', ('',))
        with pytest.raises(SecretServiceUnavailable): conn.send_and_get_reply(msg)
        assert len(calls) == 1
        conn.deadline = 0
        msg = new_method_call(DBusAddress('/controlled', 'controlled.service', 'controlled.interface'), 'ReadAlias', 's', ('default',))
        with pytest.raises(TimeoutError): conn.send_and_get_reply(msg)
        assert len(calls) == 1
    finally:
        conn.close()
        right.close()


def test_real_backend_generator_does_not_relabel_a_missing_credential(monkeypatch, tmp_path):
    """The real ladder, not an injected fake: `contextlib` throws the caller's
    exception back into the generator at its `yield`, so an absent item must
    still surface as SecretLocatorUnavailable rather than an unusable keyring."""
    import sys, types
    collection = Collection()
    # A durable default collection; the session alias is rejected upstream.
    collection.collection_path = '/org/freedesktop/secrets/collection/login'
    for name in ('secretstorage', 'secretstorage.collection', 'secretstorage.util'):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    secretstorage = sys.modules['secretstorage']
    secretstorage.get_collection_by_alias = lambda connection, alias: collection
    sys.modules['secretstorage.collection'].SESSION_COLLECTION = '/org/freedesktop/secrets/aliases/default'
    sys.modules['secretstorage.util'].open_session = lambda connection: SimpleNamespace(
        encrypted=True, aes_key=b'0123456789abcdef',
        object_path='/org/freedesktop/secrets/session/s1')
    monkeypatch.setattr(module, '_bounded_connection', lambda: SimpleNamespace(close=lambda: None))

    store = LinuxSecretServiceStore(tmp_path / 'data')
    missing = f"secret-service:v1:{store._namespace()}:00000000000000000000000000000000"
    with pytest.raises(SecretLocatorUnavailable) as absent:
        store.read(missing)
    assert absent.value.code == 'CREDENTIAL_NOT_AVAILABLE'

    # The complementary case must keep its own distinct reason, not collapse
    # into the absent one.
    collection.locked = True
    with pytest.raises(SecretServiceUnavailable) as locked:
        store.read(missing)
    assert locked.value.code == 'SECRET_STORE_LOCKED'
