"""Durable API-key import reservations; secret bytes never enter this journal."""
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import unicodedata

from server_plugin_api import WireError

_IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_CREDENTIAL = re.compile(r'credential_[0-9a-f]{32}\Z')


def _error(family, code, message):
    return WireError(family, message, details={'internalCode': code})


class ApiKeyImportService:
    def __init__(self, *, data_root, harnesses, credentials, secret_store):
        self.harnesses, self.credentials, self.secret_store = harnesses, credentials, secret_store
        self.path = None if data_root is None else Path(data_root) / 'plugins/model-provider/key-import.sqlite'
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(self._connect()) as conn:
                    conn.execute('''CREATE TABLE IF NOT EXISTS imports (
                        request_id TEXT PRIMARY KEY, harness_id TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN ('unknown','refused','imported')),
                        credential_id TEXT, kind TEXT, cleanup_state TEXT,
                        CHECK((state='imported' AND credential_id IS NOT NULL AND kind='api-key')
                              OR (state!='imported' AND credential_id IS NULL AND kind IS NULL)))''')
                    conn.commit()
            except Exception:
                raise _error('UNAVAILABLE', 'API_KEY_IMPORT_STORAGE_UNAVAILABLE', 'Credential import storage unavailable') from None

    def _connect(self):
        if self.path is None:
            raise _error('UNAVAILABLE', 'API_KEY_IMPORT_STORAGE_UNAVAILABLE', 'Credential import storage unavailable')
        conn = sqlite3.connect(self.path, timeout=3)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _identities(request_id, harness_id):
        if (type(request_id) is not str or not 8 <= len(request_id) <= 128 or not _IDENTITY.fullmatch(request_id)
                or type(harness_id) is not str or not _IDENTITY.fullmatch(harness_id)):
            raise _error('INVALID_REQUEST', 'API_KEY_IMPORT_INVALID', 'Invalid credential import identity')

    @staticmethod
    def _same_harness(row, harness_id):
        if row['harness_id'] != harness_id:
            raise _error('CONFLICT_REQUEST', 'API_KEY_IMPORT_HARNESS_CONFLICT', 'Credential import belongs to another Harness')

    def _lookup(self, request_id):
        try:
            with closing(self._connect()) as conn:
                return conn.execute('SELECT * FROM imports WHERE request_id=?', (request_id,)).fetchone()
        except WireError:
            raise
        except Exception:
            raise _error('UNAVAILABLE', 'API_KEY_IMPORT_STORAGE_UNAVAILABLE', 'Credential import storage unavailable') from None

    def _reserve(self, request_id, harness_id):
        try:
            with closing(self._connect()) as conn:
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute('SELECT * FROM imports WHERE request_id=?', (request_id,)).fetchone()
                if row is not None:
                    self._same_harness(row, harness_id)
                    raise _error('CONFLICT_REQUEST', 'API_KEY_IMPORT_ALREADY_STARTED', 'Credential import already started; query this request')
                if conn.execute('SELECT COUNT(*) FROM imports').fetchone()[0] >= 4096:
                    raise _error('UNAVAILABLE', 'API_KEY_IMPORT_CAPACITY', 'Credential import capacity exhausted')
                conn.execute("INSERT INTO imports(request_id,harness_id,state) VALUES(?,?,'unknown')", (request_id, harness_id))
                conn.commit()  # reservation is durable BEFORE any store effect
        except WireError:
            raise
        except Exception:
            raise _error('UNAVAILABLE', 'API_KEY_IMPORT_STORAGE_UNAVAILABLE', 'Credential import storage unavailable') from None

    def _complete(self, request_id, state, *, credential_id=None, cleanup_state=None):
        try:
            with closing(self._connect()) as conn:
                conn.execute("UPDATE imports SET state=?,credential_id=?,kind=?,cleanup_state=? WHERE request_id=? AND state='unknown'",
                    (state, credential_id, 'api-key' if state == 'imported' else None, cleanup_state, request_id))
                conn.commit()
            return True
        except Exception:
            return False  # reservation remains unknown across restart

    @staticmethod
    def _project(request_id, state, credential_id=None):
        result = {'operationId': 'key-import:' + request_id, 'state': state}
        if state == 'imported':
            result.update(credentialId=credential_id, kind='api-key')
        return result

    def query(self, *, request_id, harness_id):
        self._identities(request_id, harness_id)
        row = self._lookup(request_id)
        if row is None:
            return self._project(request_id, 'not-found')
        self._same_harness(row, harness_id)
        return self._project(request_id, row['state'], row['credential_id'])

    def _cleanup(self, request_id, locator):
        cleanup = 'unknown'
        try:
            self.secret_store.delete(locator)  # exact newly returned locator only
            cleanup = 'removed'
        except Exception:
            pass
        self._complete(request_id, 'unknown', cleanup_state=cleanup)

    def import_key(self, *, request_id, harness_id, api_key):
        self._identities(request_id, harness_id)
        prior = self._lookup(request_id)
        if prior is not None:
            self._same_harness(prior, harness_id)
            raise _error('CONFLICT_REQUEST', 'API_KEY_IMPORT_ALREADY_STARTED', 'Credential import already started; query this request')
        try:
            descriptor = self.harnesses.get(harness_id) if self.harnesses is not None and harness_id in self.harnesses else None
        except Exception:
            descriptor = None
        if descriptor is None or getattr(descriptor, 'credential_kind', None) != 'api-key':
            raise _error('CAPABILITY_UNSUPPORTED', 'API_KEY_IMPORT_HARNESS_UNSUPPORTED', 'Harness does not accept API keys')
        try:
            if (type(api_key) is not str or not api_key or not api_key.strip()
                    or any(unicodedata.category(c).startswith('C') for c in api_key)):
                raise ValueError()
            content = api_key.encode('utf-8')
            if len(content) > 8000 or api_key == request_id:
                raise ValueError()
        except Exception:
            raise _error('INVALID_REQUEST', 'API_KEY_IMPORT_INVALID', 'Invalid API key') from None
        self._reserve(request_id, harness_id)
        importer = getattr(self.secret_store, 'import_bytes', None)
        if not callable(importer):
            state = 'refused' if self._complete(request_id, 'refused') else 'unknown'
            return self._project(request_id, state)
        check = getattr(self.secret_store, 'check_available', None)
        if callable(check):
            try:
                check()  # no credential read or import; before-effects refusal
            except Exception:
                state = 'refused' if self._complete(request_id, 'refused') else 'unknown'
                return self._project(request_id, state)
        try:
            created = importer(content, 'api-key')
            # Only the declared two-field store return establishes a new
            # locator's provenance. Never infer one from an exception or scan.
            if type(created) is not tuple or len(created) != 2:
                raise ValueError()
            credential_id, locator = created
            if (type(locator) is not str or not locator or len(locator) > 4096
                    or any(unicodedata.category(c).startswith('C') for c in locator)):
                raise ValueError()
        except Exception:
            # A timeout or exception after entering import may follow a real
            # store effect. Never retry or classify it as a clean refusal.
            return self._project(request_id, 'unknown')
        if type(credential_id) is not str or not _CREDENTIAL.fullmatch(credential_id):
            self._cleanup(request_id, locator)
            return self._project(request_id, 'unknown')
        try:
            self.credentials.register(credential_id, 'api-key', locator)
        except Exception:
            self._cleanup(request_id, locator)
            return self._project(request_id, 'unknown')
        state = 'imported' if self._complete(request_id, 'imported', credential_id=credential_id) else 'unknown'
        return self._project(request_id, state, credential_id if state == 'imported' else None)
