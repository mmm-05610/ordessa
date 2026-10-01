"""Product-only Linux Secret Service store; no file/plaintext fallback.

SecretStorage 3.5.0 handles collection/item semantics and encryption. The
connection fence supplies deadlines and refuses its optional plaintext and
prompt paths before transmission. Constructors do not open the bus or files.
"""
from contextlib import contextmanager
import hashlib
from itertools import islice
import os
from pathlib import Path
import re
import stat
import sys
import time
from uuid import uuid4

from pacthold.storage.secrets import MAX_SECRET_BYTES, SecretLocatorUnavailable

APPLICATION = 'org.ordessa.server'
_KIND = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
_LOCATOR = re.compile(r'secret-service:v1:([0-9a-f]{64}):([0-9a-f]{32})\Z')
CALL_TIMEOUT = 3.0
OPERATION_TIMEOUT = 15.0


class SecretServiceUnavailable(RuntimeError):
    """Static code only: provider messages, paths and bytes never escape."""
    def __init__(self, code='SECRET_SERVICE_UNAVAILABLE'):
        self.code = {'SECRET_SERVICE_LOCKED': 'SECRET_STORE_LOCKED',
                     'SECRET_SERVICE_TIMEOUT': 'SECRET_STORE_TIMEOUT',
                     'SECRET_SERVICE_ITEM_AMBIGUOUS': 'SECRET_STORE_INTEGRITY',
                     'SECRET_SERVICE_ITEM_INVALID': 'SECRET_STORE_INTEGRITY'}.get(code, 'SECRET_STORE_UNAVAILABLE')
        super().__init__(self.code)


def _guard_call(member, body):
    if member in ('Prompt', 'Unlock', 'CreateCollection'):
        raise SecretServiceUnavailable('SECRET_SERVICE_PROMPT_REQUIRED')
    if member == 'OpenSession' and (not body or body[0] != 'dh-ietf1024-sha256-aes128-cbc-pkcs7'):
        raise SecretServiceUnavailable('SECRET_SERVICE_ENCRYPTION_REQUIRED')


def _guard_reply(member, body):
    if member == 'CreateItem' and (len(body) != 2 or body[1] != '/'):
        raise SecretServiceUnavailable('SECRET_SERVICE_PROMPT_REQUIRED')
    if member == 'Delete' and (len(body) != 1 or body[0] != '/'):
        raise SecretServiceUnavailable('SECRET_SERVICE_PROMPT_REQUIRED')


def _bounded_connection():
    """Bound authentication AND Hello; stock dbus_init leaves Hello unbounded.

    Jeepney's prep_socket has an authentication deadline; its connection's
    overridable send_and_get_reply is used even by the constructor's Hello.
    Every socket send and reply receive is capped, with a shared total deadline.
    """
    from jeepney.io.blocking import DBusConnection, get_bus, prep_socket
    from jeepney.low_level import HeaderFields, MessageType
    class Connection(DBusConnection):
        def __init__(self, sock):
            self.deadline = time.monotonic() + OPERATION_TIMEOUT
            super().__init__(sock)
        def send_and_get_reply(self, message, *, timeout=None):
            member = message.header.fields.get(HeaderFields.member)
            _guard_call(member, message.body)
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            limit = min(CALL_TIMEOUT, remaining, timeout if timeout is not None else CALL_TIMEOUT)
            self.sock.settimeout(limit)
            reply = super().send_and_get_reply(message, timeout=limit)
            if reply.header.message_type == MessageType.method_return:
                _guard_reply(member, reply.body)
            return reply
    sock = prep_socket(get_bus('SESSION'), timeout=CALL_TIMEOUT)
    try:
        sock.settimeout(CALL_TIMEOUT)
        return Connection(sock)
    except BaseException:
        sock.close()
        raise


@contextmanager
def _default_collection():
    # Imports and bus connection happen only during an explicitly requested
    # credential operation. No process/global keyring setup is performed.
    connection = None
    try:
        from importlib.metadata import version
        if version('SecretStorage') != '3.5.0':
            raise SecretServiceUnavailable()
        import secretstorage
        from secretstorage.collection import SESSION_COLLECTION
        from secretstorage.util import open_session
        connection = _bounded_connection()
        collection = secretstorage.get_collection_by_alias(connection, 'default')
        if collection.collection_path == SESSION_COLLECTION:
            raise SecretServiceUnavailable('SECRET_SERVICE_DEFAULT_UNAVAILABLE')
        if collection.is_locked():
            raise SecretServiceUnavailable('SECRET_SERVICE_LOCKED')
        # The connection denies a plaintext fallback request before it reaches
        # the bus, including fallback inside SecretStorage.open_session.
        session = open_session(connection)
        if (session.encrypted is not True or not isinstance(session.aes_key, bytes)
                or len(session.aes_key) != 16 or not isinstance(session.object_path, str)
                or not session.object_path.startswith('/org/freedesktop/secrets/session/')):
            raise SecretServiceUnavailable('SECRET_SERVICE_ENCRYPTION_REQUIRED')
        collection.session = session
        yield collection
    except SecretServiceUnavailable:
        raise
    except TimeoutError:
        raise SecretServiceUnavailable('SECRET_SERVICE_TIMEOUT') from None
    except Exception:
        raise SecretServiceUnavailable() from None
    finally:
        if connection is not None:
            connection.close()


def _open_parent(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    try:
        for part in path.parts[1:-1]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read_source(source):
    """Anchored nofollow directory walk and stable descriptor/path checks."""
    path = Path(source)
    if '..' in path.parts or not path.name:
        raise ValueError('CREDENTIAL_SOURCE_INVALID')
    path = Path(os.path.abspath(path))
    parent = fd = final_parent = None
    try:
        parent = _open_parent(path)
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('CREDENTIAL_SOURCE_INVALID')
        if not 0 < before.st_size <= MAX_SECRET_BYTES:
            raise ValueError('CREDENTIAL_SOURCE_OUTSIDE_BOUND')
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
            raise ValueError('CREDENTIAL_SOURCE_CHANGED')
        chunks, size = [], 0
        while size <= MAX_SECRET_BYTES:
            chunk = os.read(fd, min(65536, MAX_SECRET_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if not 0 < size <= MAX_SECRET_BYTES:
            raise ValueError('CREDENTIAL_SOURCE_OUTSIDE_BOUND')
        final_parent = _open_parent(path)
        if ((os.fstat(parent).st_dev, os.fstat(parent).st_ino) !=
                (os.fstat(final_parent).st_dev, os.fstat(final_parent).st_ino)
                or _identity(os.fstat(fd)) != _identity(before)
                or _identity(os.stat(path.name, dir_fd=final_parent, follow_symlinks=False)) != _identity(before)
                or size != before.st_size):
            raise ValueError('CREDENTIAL_SOURCE_CHANGED')
        return b''.join(chunks)
    except OSError:
        raise ValueError('CREDENTIAL_SOURCE_INVALID') from None
    finally:
        for handle in (fd, final_parent, parent):
            if handle is not None:
                os.close(handle)


class LinuxSecretServiceStore:
    def __init__(self, data_root, *, _backend_factory=None):
        # Pure path normalization only. Canonical filesystem resolution is
        # deferred until operation, and the first resolved root stays fenced.
        self._data_root = os.path.abspath(os.fspath(data_root))
        self._root_namespace = None
        self._backend_factory = _backend_factory or _default_collection

    def _namespace(self):
        try:
            namespace = hashlib.sha256(os.fsencode(str(Path(self._data_root).resolve()))).hexdigest()
        except Exception:
            raise SecretServiceUnavailable('SECRET_SERVICE_ITEM_INVALID') from None
        if self._root_namespace is not None and namespace != self._root_namespace:
            raise SecretServiceUnavailable('SECRET_SERVICE_ITEM_INVALID')
        self._root_namespace = namespace
        return namespace

    def _attributes(self, locator):
        match = _LOCATOR.fullmatch(locator) if type(locator) is str else None
        if match is None or match[1] != self._namespace():
            raise ValueError('CREDENTIAL_LOCATOR_INVALID')
        return {'application': APPLICATION, 'ordessa.data-root': match[1],
                'ordessa.locator': match[2], 'ordessa.schema': '1'}

    @staticmethod
    def _item(collection, attributes, *, missing_ok=False):
        if collection.is_locked():
            raise SecretServiceUnavailable('SECRET_SERVICE_LOCKED')
        matches = list(islice(collection.search_items(attributes), 2))
        if len(matches) > 1:
            raise SecretServiceUnavailable('SECRET_SERVICE_ITEM_AMBIGUOUS')
        if not matches:
            if missing_ok:
                return None
            raise SecretServiceUnavailable('SECRET_SERVICE_ITEM_UNAVAILABLE')
        item = matches[0]
        actual = item.get_attributes()
        if (not isinstance(actual, dict) or set(actual) - {'xdg:schema'} != set(attributes) | {'ordessa.kind'}
                or ('xdg:schema' in actual and actual['xdg:schema'] != 'org.freedesktop.Secret.Generic')
                or any(actual.get(key) != value for key, value in attributes.items())
                or type(actual.get('ordessa.kind')) is not str or not _KIND.fullmatch(actual['ordessa.kind'])):
            raise SecretServiceUnavailable('SECRET_SERVICE_ITEM_INVALID')
        if item.is_locked():
            raise SecretServiceUnavailable('SECRET_SERVICE_LOCKED')
        item.session = collection.session
        return item

    @contextmanager
    def _collection(self):
        try:
            with self._backend_factory() as collection:
                if collection.is_locked():
                    raise SecretServiceUnavailable('SECRET_SERVICE_LOCKED')
                if getattr(collection.session, 'encrypted', None) is not True:
                    raise SecretServiceUnavailable('SECRET_SERVICE_ENCRYPTION_REQUIRED')
                yield collection
        except (SecretServiceUnavailable, SecretLocatorUnavailable):
            raise
        except TimeoutError:
            raise SecretServiceUnavailable('SECRET_SERVICE_TIMEOUT') from None
        except Exception:
            raise SecretServiceUnavailable() from None

    def import_file(self, source, kind):
        if type(kind) is not str or not _KIND.fullmatch(kind):
            raise ValueError('CREDENTIAL_KIND_INVALID')
        return self.import_bytes(_read_source(source), kind)

    def import_bytes(self, content, kind):
        """Optional product capability for transient UI input; no scratch file."""
        if type(kind) is not str or not _KIND.fullmatch(kind):
            raise ValueError('CREDENTIAL_KIND_INVALID')
        if type(content) is not bytes or not 0 < len(content) <= MAX_SECRET_BYTES:
            raise ValueError('CREDENTIAL_SOURCE_OUTSIDE_BOUND')
        locator = f'secret-service:v1:{self._namespace()}:{uuid4().hex}'
        attributes = self._attributes(locator)
        with self._collection() as collection:
            if self._item(collection, attributes, missing_ok=True) is not None:
                raise SecretServiceUnavailable('SECRET_SERVICE_ITEM_AMBIGUOUS')
            created = collection.create_item('Ordessa credential', {**attributes, 'ordessa.kind': kind}, content,
                replace=False, content_type='application/octet-stream')
            try:
                self._item(collection, attributes)
            except Exception as primary:
                error = primary if isinstance(primary, SecretServiceUnavailable) else SecretServiceUnavailable()
                try:
                    # Cleanup only the exact create result, never a search
                    # result or duplicate. Its random own attributes must
                    # still match before any deletion can be attempted.
                    actual = created.get_attributes()
                    expected = {**attributes, 'ordessa.kind': kind}
                    if not isinstance(actual, dict) or any(actual.get(k) != v for k, v in expected.items()):
                        raise SecretServiceUnavailable('SECRET_SERVICE_ITEM_INVALID')
                    created.delete()
                except Exception as cleanup:
                    error.cleanup_code = (cleanup.code if isinstance(cleanup, SecretServiceUnavailable)
                                          else 'SECRET_STORE_UNAVAILABLE')
                raise error from None
        return 'credential_' + locator.rsplit(':', 1)[1], locator

    def read(self, locator):
        attributes = self._attributes(locator)
        with self._collection() as collection:
            item = self._item(collection, attributes, missing_ok=True)
            if item is None:
                raise SecretLocatorUnavailable(locator)
            secret = item.get_secret()
            if type(secret) is not bytes or not 0 < len(secret) <= MAX_SECRET_BYTES:
                raise SecretServiceUnavailable('SECRET_SERVICE_ITEM_INVALID')
            self._item(collection, attributes)  # ownership/locked fence after read
            return secret

    def delete(self, locator):
        attributes = self._attributes(locator)
        with self._collection() as collection:
            item = self._item(collection, attributes, missing_ok=True)
            if item is not None:
                item.delete()

    def check_available(self):
        """No item enumeration or credential access; no unlock/prompt/create."""
        with self._collection():
            pass


def product_secret_store(data_root):
    return LinuxSecretServiceStore(data_root) if sys.platform == 'linux' else None
