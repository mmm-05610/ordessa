"""Profile-owned atomic CAS records and request results; zero Unit/runtime imports.

Existing namespace/ref/payload identifiers stay exact. This explicit new store
never opens or auto-adopts a Unit database; historical data needs an explicit
read-only source/migration, not a normal write fallback.
"""
import json
from pathlib import Path
from threading import RLock

from ordessa_infrastructure.database import SQLiteOptions,create_connection
from ordessa_infrastructure.database.records import DomainRevisionConflict
from .record_store import RecordProfileStore
from ..definitions.errors import ProfileStoreUnavailable,ProfileRevisionConflict,ProfileChangeUnknown
from ..definitions.validation import canonical


class SqliteProfileStore(RecordProfileStore):
    def __init__(self,path):
        self.path=str(Path(path).absolute());self._lock=RLock();self._closed=False
        self._conn=create_connection(SQLiteOptions(self.path,timeout=10,isolation_level=None,
            check_same_thread=False))
        try:
            self._conn.execute('BEGIN IMMEDIATE')
            tables={r[0] for r in self._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and 'profile_store_meta' not in tables:
                raise ProfileStoreUnavailable('explicit Profile-owned database required')
            self._conn.execute('CREATE TABLE IF NOT EXISTS profile_store_meta(version INTEGER PRIMARY KEY CHECK(version=1))')
            versions=self._conn.execute('SELECT version FROM profile_store_meta').fetchall()
            if not versions:self._conn.execute('INSERT INTO profile_store_meta VALUES (1)')
            elif [r[0] for r in versions]!=[1]:raise ProfileStoreUnavailable('unknown Profile store schema')
            self._conn.execute('CREATE TABLE IF NOT EXISTS env_domain_records(environment TEXT NOT NULL,namespace TEXT NOT NULL,record_id TEXT NOT NULL,revision INTEGER NOT NULL CHECK(revision>0),payload TEXT NOT NULL,PRIMARY KEY(environment,namespace,record_id))')
            self._conn.execute('CREATE TABLE IF NOT EXISTS profile_requests(environment TEXT NOT NULL,principal TEXT NOT NULL,request_id TEXT NOT NULL,digest TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(environment,principal,request_id))')
            self._conn.commit()
        except BaseException:
            if self._conn.in_transaction:self._conn.rollback()
            self._conn.close()
            raise
        super().__init__(self)

    def available(self):return not self._closed

    def close(self):
        with self._lock:self._closed=True;self._conn.close()

    def _check(self):
        if self._closed:raise ProfileStoreUnavailable('Profile store closed')

    @staticmethod
    def _record(row):
        if row is None:return None
        try:
            value=json.loads(row[2])
            if type(value) is not dict:raise ValueError()
            return {'record_id':row[0],'revision':row[1],'value':value}
        except (ValueError,TypeError):raise ProfileStoreUnavailable('Profile record corrupt') from None

    def read_domain(self,environment,namespace,record_id):
        with self._lock:
            self._check()
            return self._record(self._conn.execute('SELECT record_id,revision,payload FROM env_domain_records WHERE environment=? AND namespace=? AND record_id=?',(environment,namespace,record_id)).fetchone())

    def list_domain(self,environment,namespace):
        with self._lock:
            self._check()
            return tuple(self._record(r) for r in self._conn.execute('SELECT record_id,revision,payload FROM env_domain_records WHERE environment=? AND namespace=? ORDER BY record_id',(environment,namespace)))

    def read_domain_result(self,request,digest):
        with self._lock:
            self._check()
            row=self._conn.execute('SELECT digest,result FROM profile_requests WHERE environment=? AND principal=? AND request_id=?',(request.environment_namespace,request.principal_scope,request.request_id)).fetchone()
            if row is None:return None
            if row[0]!=digest:raise ProfileRevisionConflict('request key has a different input')
            try:
                value=json.loads(row[1])
                if type(value) is not dict:raise ValueError()
                return value
            except (TypeError,ValueError):raise ProfileChangeUnknown('original Profile result corrupt; do not resend') from None

    def commit_domain_change(self,request,digest,writes,result):
        identities=[(w.namespace,w.record_id) for w in writes]
        if len(set(identities))!=len(identities):raise ValueError('duplicate Profile record write')
        payloads=[canonical(dict(w.value)) for w in writes];result_json=canonical(dict(result))
        with self._lock:
            self._check()
            if self._conn.in_transaction:raise ProfileStoreUnavailable('Profile transaction cannot nest')
            self._conn.execute('BEGIN IMMEDIATE')
            try:
                replay=self.read_domain_result(request,digest)
                if replay is not None:self._conn.rollback();return replay
                for write,payload in zip(writes,payloads):
                    key=(request.environment_namespace,write.namespace,write.record_id)
                    row=self._conn.execute('SELECT revision FROM env_domain_records WHERE environment=? AND namespace=? AND record_id=?',key).fetchone()
                    actual=0 if row is None else row[0]
                    if actual!=write.expected_revision:raise DomainRevisionConflict('Profile record CAS conflict')
                    if row is None:self._conn.execute('INSERT INTO env_domain_records VALUES (?,?,?,?,?)',(*key,1,payload))
                    else:self._conn.execute('UPDATE env_domain_records SET revision=?,payload=? WHERE environment=? AND namespace=? AND record_id=?',(actual+1,payload,*key))
                self._conn.execute('INSERT INTO profile_requests VALUES (?,?,?,?,?)',(request.environment_namespace,request.principal_scope,request.request_id,digest,result_json))
                self._conn.commit()
                return json.loads(result_json)
            except BaseException:
                if self._conn.in_transaction:self._conn.rollback()
                raise
