"""Small resource/use registry, not a general operation journal.

One explicit database is the admission authority for this manager scope. A store
does not assert that other gateway users have no processes or resource uses.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..definitions.contracts import Capabilities
from ..definitions.errors import EnvironmentRefused
from ..definitions.models import BackendObservation, EnvironmentSnapshot


def encode_observation(observation):
    if not isinstance(observation, BackendObservation):
        raise EnvironmentRefused('provider did not return a BackendObservation')
    if not observation.backend_id or not observation.observed_at:
        raise EnvironmentRefused('provider observation lacks identity or capture time')
    return json.dumps({'backend_id': observation.backend_id, 'state': observation.state,
        'observed_at': observation.observed_at, 'isolation': observation.capabilities.isolation,
        'provides': sorted(observation.capabilities.provides),
        'runtime_identity':observation.runtime_identity,
        'detail': dict(observation.capabilities.detail)}, allow_nan=False, sort_keys=True)


def decode_observation(raw):
    if raw is None:
        return None
    value = json.loads(raw)
    return BackendObservation(value['backend_id'], value['state'],
        Capabilities(value['isolation'], frozenset(value['provides']), value['detail']),
        value['observed_at'], value.get('runtime_identity'))


class SQLiteEnvironmentStore:
    """Explicit creation of schema1; refuses a foreign or newer database."""

    def __init__(self, path):
        self.path = str(Path(path).absolute())
        with self.transaction() as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and 'environment_metadata' not in tables:
                raise EnvironmentRefused('environment registry requires its own database')
            connection.execute('CREATE TABLE IF NOT EXISTS environment_metadata (version INTEGER NOT NULL)')
            version = connection.execute('SELECT version FROM environment_metadata').fetchall()
            if version and [row[0] for row in version] != [1]:
                raise EnvironmentRefused('unsupported environment registry schema')
            if not version:
                connection.execute('INSERT INTO environment_metadata VALUES (1)')
            connection.execute('''CREATE TABLE IF NOT EXISTS environment_resources (
                identity TEXT PRIMARY KEY, provider_id TEXT NOT NULL, backend_id TEXT,
                phase TEXT NOT NULL, generation INTEGER NOT NULL, observation TEXT,
                operation TEXT, operation_id TEXT, UNIQUE(provider_id, backend_id))''')
            connection.execute('''CREATE TABLE IF NOT EXISTS environment_uses (
                identity TEXT PRIMARY KEY, environment_id TEXT NOT NULL REFERENCES environment_resources(identity),
                generation INTEGER NOT NULL, owner_id TEXT NOT NULL,
                sharing INTEGER NOT NULL, phase TEXT NOT NULL, pending INTEGER NOT NULL DEFAULT 0)''')
            connection.execute('''CREATE TABLE IF NOT EXISTS environment_provider_bindings (
                identity TEXT PRIMARY KEY, binding_id TEXT NOT NULL)''')

    def bind_provider(self, identity, binding_id):
        if not isinstance(binding_id,str) or not binding_id:
            raise EnvironmentRefused('provider requires an opaque stable binding identity')
        with self.transaction() as connection:
            row = connection.execute('SELECT binding_id FROM environment_provider_bindings WHERE identity=?', (identity,)).fetchone()
            if row is not None and row[0] != binding_id:
                raise EnvironmentRefused('provider binding changed for an existing registry scope')
            connection.execute('INSERT OR IGNORE INTO environment_provider_bindings VALUES (?,?)', (identity,binding_id))

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.execute('COMMIT')
        except BaseException:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise
        finally:
            connection.close()

    @staticmethod
    def resource(connection, identity):
        row = connection.execute('SELECT * FROM environment_resources WHERE identity=?', (identity,)).fetchone()
        if row is None:
            raise EnvironmentRefused('unknown environment identity')
        return row

    def snapshot(self, identity):
        with self.transaction() as connection:
            row = self.resource(connection, identity)
            count = connection.execute("SELECT COUNT(*) FROM environment_uses WHERE environment_id=? AND phase IN ('active','unknown','releasing')",
                (identity,)).fetchone()[0]
            return EnvironmentSnapshot(row['identity'], row['provider_id'], row['backend_id'],
                row['phase'], row['generation'], decode_observation(row['observation']), row['operation'], count)

    def identities(self):
        with self.transaction() as connection:
            return tuple(row[0] for row in connection.execute('SELECT identity FROM environment_resources ORDER BY identity'))

    def insert(self, identity, provider_id, *, observation=None, operation_id=None):
        encoded = encode_observation(observation) if observation else None
        with self.transaction() as connection:
            connection.execute('INSERT INTO environment_resources VALUES (?,?,?,?,?,?,?,?)',
                (identity, provider_id, observation.backend_id if observation else None,
                 'ready' if observation else 'creating', 0, encoded,
                 None if observation else 'create', operation_id))

    def confirm(self, identity, observation, *, expected_operation_id):
        encoded = encode_observation(observation)
        with self.transaction() as connection:
            row = self.resource(connection, identity)
            if row['operation_id'] != expected_operation_id:
                raise EnvironmentRefused('resource operation was superseded')
            if row['backend_id'] is not None and row['backend_id'] != observation.backend_id:
                raise EnvironmentRefused('immutable backend identity changed')
            if row['operation'] == 'stop' and observation.state == 'stopped':
                connection.execute("UPDATE environment_uses SET phase='invalid' WHERE environment_id=? AND generation<? AND phase='unknown'",
                    (identity, row['generation']))
            connection.execute('UPDATE environment_resources SET backend_id=?, observation=?, phase=?, operation=NULL, operation_id=NULL WHERE identity=?',
                (observation.backend_id, encoded, 'ready', identity))

    def unknown(self, identity, *, operation_id, backend_id=None):
        with self.transaction() as connection:
            row = self.resource(connection, identity)
            if row['operation_id'] != operation_id:
                raise EnvironmentRefused('resource operation was superseded')
            if row['backend_id'] is not None and backend_id not in (None, row['backend_id']):
                raise EnvironmentRefused('immutable backend identity changed')
            connection.execute("UPDATE environment_resources SET phase='unknown', backend_id=COALESCE(backend_id,?) WHERE identity=?",
                (backend_id, identity))

    def refuse_creation(self, identity, operation_id):
        with self.transaction() as connection:
            row = self.resource(connection,identity)
            if row['phase'] != 'creating' or row['operation_id'] != operation_id:
                raise EnvironmentRefused('creation refusal was superseded')
            connection.execute("UPDATE environment_resources SET phase='refused', operation=NULL, operation_id=NULL WHERE identity=?", (identity,))

    @staticmethod
    def use_row(connection, use_id, *, allow_unknown=False):
        row = connection.execute('SELECT * FROM environment_uses WHERE identity=?', (use_id,)).fetchone()
        if row is None:
            raise EnvironmentRefused('unknown environment use')
        resource = SQLiteEnvironmentStore.resource(connection, row['environment_id'])
        observation = decode_observation(resource['observation'])
        if (row['phase'] not in (('active','unknown') if allow_unknown else ('active',)) or resource['phase'] != 'ready'
                or row['generation'] != resource['generation'] or observation is None
                or observation.state != 'running'):
            raise EnvironmentRefused('environment use is released, fenced or from an old generation')
        return row

    def check_use(self, use_id, *, allow_unknown=False):
        with self.transaction() as connection:
            self.use_row(connection, use_id,allow_unknown=allow_unknown)

    def fence_use(self, use_id):
        with self.transaction() as connection:
            connection.execute("UPDATE environment_uses SET phase='unknown' WHERE identity=? AND phase='active'", (use_id,))

    def reserve_use(self, identity, use_id, owner_id, *, sharing):
        if type(sharing) is not bool or not isinstance(owner_id, str) or not owner_id:
            raise EnvironmentRefused('use requires owner identity and explicit sharing policy')
        with self.transaction() as connection:
            row = self.resource(connection, identity)
            observation = decode_observation(row['observation'])
            if row['phase'] != 'ready' or observation is None or observation.state != 'running':
                raise EnvironmentRefused('environment is not observed running or is fenced')
            uses = connection.execute("SELECT sharing FROM environment_uses WHERE environment_id=? AND phase IN ('active','unknown','releasing')", (identity,)).fetchall()
            if uses and (not sharing or any(not use[0] for use in uses)):
                raise EnvironmentRefused('sharing was not explicitly admitted by every use')
            connection.execute("INSERT INTO environment_uses VALUES (?,?,?,?,?,'active',0)",
                (use_id, identity, row['generation'], owner_id, int(sharing)))
            return row['backend_id'], row['generation']

    def begin_use_effect(self, use_id, *, allow_unknown=False):
        with self.transaction() as connection:
            self.use_row(connection, use_id,allow_unknown=allow_unknown)
            connection.execute('UPDATE environment_uses SET pending=pending+1 WHERE identity=?', (use_id,))

    def end_use_effect(self, use_id, *, unknown=False):
        with self.transaction() as connection:
            connection.execute('UPDATE environment_uses SET pending=pending-1, phase=CASE WHEN ? THEN \'unknown\' ELSE phase END WHERE identity=? AND pending>0',
                (int(unknown), use_id))

    def release_use(self, use_id):
        with self.transaction() as connection:
            row = self.use_row(connection, use_id)
            if row['pending']:
                raise EnvironmentRefused('use still has an in-flight effect')
            connection.execute("UPDATE environment_uses SET phase='released' WHERE identity=?", (use_id,))

    def begin_use_release(self, use_id, *, allow_unknown=False):
        with self.transaction() as connection:
            row=self.use_row(connection,use_id,allow_unknown=allow_unknown)
            if row['pending']:raise EnvironmentRefused('use still has in-flight effects')
            connection.execute("UPDATE environment_uses SET phase='releasing' WHERE identity=?",(use_id,))

    def finish_use_release(self,use_id,*,success,unknown=False):
        with self.transaction() as connection:
            row=connection.execute('SELECT phase FROM environment_uses WHERE identity=?',(use_id,)).fetchone()
            if row is None or row[0]!='releasing':raise EnvironmentRefused('use release was superseded')
            phase='released' if success else 'unknown' if unknown else 'active'
            connection.execute('UPDATE environment_uses SET phase=? WHERE identity=?',(phase,use_id))

    def begin_operation(self, identity, operation, operation_id, *, allow_in_use=False):
        if type(allow_in_use) is not bool:
            raise EnvironmentRefused('allow_in_use must be explicit boolean policy')
        with self.transaction() as connection:
            row = self.resource(connection, identity)
            if row['phase'] != 'ready':
                raise EnvironmentRefused('environment operation already fenced or unresolved')
            count = connection.execute("SELECT COUNT(*) FROM environment_uses WHERE environment_id=? AND phase IN ('active','unknown','releasing')", (identity,)).fetchone()[0]
            pending = connection.execute('SELECT COALESCE(SUM(pending),0) FROM environment_uses WHERE environment_id=?', (identity,)).fetchone()[0]
            releasing=connection.execute("SELECT COUNT(*) FROM environment_uses WHERE environment_id=? AND phase='releasing'",(identity,)).fetchone()[0]
            if pending or releasing or count and (operation == 'delete' or not allow_in_use):
                raise EnvironmentRefused('resource has recorded uses or an in-flight effect')
            generation = row['generation'] + 1
            connection.execute('UPDATE environment_resources SET phase=?, generation=?, operation=?, operation_id=? WHERE identity=?',
                ({'start':'starting', 'stop':'stopping', 'delete':'deleting'}[operation], generation, operation, operation_id, identity))
            connection.execute("UPDATE environment_uses SET phase='invalid' WHERE environment_id=? AND phase='active'", (identity,))
            return row['backend_id'], generation

    def confirm_deleted(self, identity, operation_id):
        with self.transaction() as connection:
            row = self.resource(connection, identity)
            if row['operation'] != 'delete' or row['operation_id'] != operation_id:
                raise EnvironmentRefused('delete operation was superseded')
            connection.execute("UPDATE environment_resources SET phase='deleted', operation=NULL, operation_id=NULL WHERE identity=?", (identity,))
