"""Runnable agent manager over one durable, uniquely claimed operation ledger.

Every action follows the same three steps: an atomic durable reservation (before
any side effect), the effect itself through the endpoint member that is actually
granted, and a completion receipt on the same row. A reservation that never
completed is reported as `unknown` and never re-sent; a replay is served from the
ledger after a *read* check only, so losing send rights later cannot rewrite
history and cannot authorize a new effect either.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import threading

_OPEN_LOCKS = {}
_OPEN_LOCKS_GUARD = threading.Lock()

from .endpoint import BoundEndpoint, EndpointValueError, lifecycle_guarded
from .instances import AgentInstanceRef, EndpointRef
from .prepare import (EndpointError, LaunchObservation, LaunchPlan,
                      validate_lifecycle_observation, validate_launch_observation)


class ManagerRefused(RuntimeError):
    """A refusal with a stable code. Nothing was launched for this code path."""

    def __init__(self, code, message=''):
        super().__init__(message or code)
        self.code = code


_UNKNOWN = 'unknown'
_RESERVED = 'reserved'


@dataclass(frozen=True)
class Record:
    request_id: str
    operation: str
    status: str
    operation_ref: str | None
    endpoint: dict | None
    payload: dict
    principal: str = ''
    target: str = ''
    request_digest: str = ''
    turn_id: str | None = None

    def observation(self) -> LaunchObservation:
        if self.operation in ('stop','detach') and 'endpointObservation' in self.payload:
            observed=LaunchObservation.decode(self.payload['endpointObservation'])
            if observed.status!=self.status:raise ManagerRefused('RECORD_CORRUPT')
            return observed
        error = self.payload.get('error')
        return LaunchObservation(
            operation_ref=self.operation_ref or f'{self.operation}:{self.request_id}',
            status=_UNKNOWN if self.status in (_RESERVED, 'possibly-written') else self.status,
            process_endpoint_ref=None if self.endpoint is None else EndpointRef.decode(self.endpoint),
            facts={key: ('terminate' if self.operation=='stop' and key=='action' and value=='stop' else value)
                   for key, value in self.payload.items() if key != 'error'},
            error=(EndpointError(error['code'], error['diagnostic']) if error
                   else (EndpointError('OPERATION_UNCONFIRMED',
                                       'the durable reservation never completed') if
                         self.status in (_RESERVED,'possibly-written') else None)))


class Records:
    """SQLite ledger: one row per (request, operation), claimed inside a transaction."""

    def __init__(self, path, *, attempts=8, backoff=0.05):
        self.path = str(path)
        # Concurrent first opens race on WAL/schema creation. Serialise them in
        # process with one lock per ledger file, and keep a short bounded retry
        # for the cross-process case; a persistent failure still fails closed.
        import time
        with _OPEN_LOCKS_GUARD:
            lock = _OPEN_LOCKS.setdefault(self.path, threading.Lock())
        last = None
        with lock:
            for attempt in range(max(1, attempts)):
                try:
                    self._db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
                    self._db.execute('PRAGMA busy_timeout=10000')
                    self._db.execute(
                        'CREATE TABLE IF NOT EXISTS operations ('
                        'request_id TEXT NOT NULL, operation TEXT NOT NULL, principal TEXT NOT NULL,'
                        'target TEXT NOT NULL, request_digest TEXT NOT NULL, endpoint_json TEXT,'
                        'status TEXT NOT NULL, operation_ref TEXT, payload TEXT NOT NULL,'
                        'PRIMARY KEY (request_id, operation))')
                    columns={row[1] for row in self._db.execute('PRAGMA table_info(operations)')}
                    if 'turn_id' not in columns:self._db.execute('ALTER TABLE operations ADD COLUMN turn_id TEXT')
                    self._db.execute('CREATE UNIQUE INDEX IF NOT EXISTS operations_turn_id ON operations(turn_id) WHERE turn_id IS NOT NULL')
                    self._db.execute('PRAGMA journal_mode=WAL')
                    self._db.execute('PRAGMA synchronous=FULL')
                    # Additive native-interaction journal in the SAME owner/database.
                    # No existing row, column or identifier is rewritten; a cold
                    # open creates the two tables only when they are absent.
                    self._db.execute(
                        'CREATE TABLE IF NOT EXISTS protocol_events ('
                        'seq INTEGER PRIMARY KEY AUTOINCREMENT,'
                        'namespace TEXT NOT NULL, instance_id TEXT NOT NULL,'
                        'kind TEXT NOT NULL, operation_ref TEXT,'
                        'payload TEXT NOT NULL, payload_digest TEXT NOT NULL,'
                        'payload_bytes INTEGER NOT NULL,'
                        'connection_generation INTEGER NOT NULL, observed_at TEXT NOT NULL)')
                    self._db.execute(
                        'CREATE INDEX IF NOT EXISTS protocol_events_stream'
                        ' ON protocol_events(namespace, instance_id, seq)')
                    self._db.execute(
                        'CREATE TABLE IF NOT EXISTS protocol_journal ('
                        'namespace TEXT NOT NULL, instance_id TEXT NOT NULL,'
                        'first_seq INTEGER NOT NULL DEFAULT 0,'
                        'dropped_events INTEGER NOT NULL DEFAULT 0,'
                        'dropped_bytes INTEGER NOT NULL DEFAULT 0,'
                        'PRIMARY KEY(namespace, instance_id))')
                    self._db.execute(
                        'CREATE TABLE IF NOT EXISTS native_pending ('
                        'namespace TEXT NOT NULL, instance_id TEXT NOT NULL,'
                        'connection_generation INTEGER NOT NULL,'
                        'native_request_id TEXT NOT NULL,'
                        'protocol_id TEXT NOT NULL, method TEXT,'
                        'payload TEXT NOT NULL, payload_digest TEXT NOT NULL,'
                        'state TEXT NOT NULL, operation_ref TEXT,'
                        'observed_at TEXT NOT NULL, updated_at TEXT NOT NULL,'
                        'PRIMARY KEY(namespace, instance_id, native_request_id))')
                    return
                except sqlite3.Error as error:
                    last = error
                    try:
                        self._db.close()
                    except Exception:
                        pass
                    time.sleep(backoff * (attempt + 1))
        raise ManagerRefused('RECORDS_UNAVAILABLE', str(last)) from None

    def close(self):
        """Close this ledger handle; never stop/release externally owned endpoints."""
        self._db.close()

    def _row(self, row):
        if row is None:
            return None
        try:
            payload = json.loads(row[8]) if row[8] else {}
            endpoint = json.loads(row[7]) if row[7] else None
        except ValueError:
            # Unparsable storage fails closed instead of reading as "no record".
            raise ManagerRefused('RECORD_CORRUPT') from None
        return Record(row[0], row[1], row[6], row[5], endpoint, payload,
                      row[2], row[3], row[4],row[9])

    def operation(self, request_id, operation):
        try:
            cursor = self._db.execute(
                'SELECT request_id, operation, principal, target, request_digest,'
                ' operation_ref, status, endpoint_json, payload, turn_id FROM operations'
                ' WHERE request_id=? AND operation=?', (request_id, operation))
            return self._row(cursor.fetchone())
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None

    def turn(self, turn_id):
        try:
            return self._row(self._db.execute(
                'SELECT request_id,operation,principal,target,request_digest,operation_ref,status,endpoint_json,payload,turn_id '
                "FROM operations WHERE operation='turn' AND turn_id=?",(turn_id,)).fetchone())
        except sqlite3.Error:raise ManagerRefused('RECORDS_UNAVAILABLE') from None

    def session_starts(self):
        """Read-only projection of unfinished/active original start records.

        The foreground session uses this to report retained instances on exit;
        it creates no claim, changes no row and never infers an instance from a
        request outside this ledger.
        """
        from ..instances.contracts import AgentStartReceipt
        try:
            rows=self._db.execute(
                'SELECT request_id, operation, principal, target, request_digest,'
                ' operation_ref, status, endpoint_json, payload, turn_id FROM operations'
                " WHERE operation='agent-start'").fetchall()
        except sqlite3.Error:raise ManagerRefused('RECORDS_UNAVAILABLE') from None
        result=[]
        for row in rows:
            record=self._row(row)
            if record.status not in ('running','reserved','possibly-written','unknown'):
                continue
            try:
                receipt=AgentStartReceipt.decode(record.payload['agentStartReceipt'])
            except Exception:
                continue
            association=None
            if receipt.instance_ref is not None:
                from ..instances.contracts import instance_control_key
                control_row=self.operation(instance_control_key(receipt.instance_ref),'instance-control')
                if control_row is not None:
                    try:association=control_row.payload['control']['association']
                    except (KeyError,TypeError):association=None
            if association in ('stopped','detached'):
                continue
            result.append({'requestId':record.request_id,'status':record.status,
                           'association':association,'receipt':receipt.projection()})
        return tuple(result)

    def publish_instance_binding(self, provenance, session_id, *, principal_scope, protocol_id):
        """Trusted materialization storage, not a permission or public wire API.

        Original Profile/harness preparation must validate its source before
        publishing. This primitive neither derives metadata from caller labels
        nor grants any access: interaction reads still verify external authority.
        """
        from .interactions import BindingProvenance,_text,_digest_of,_canonical
        if type(provenance) is not BindingProvenance:raise ManagerRefused('PROVENANCE_REQUIRED')
        BindingProvenance.decode(provenance.projection())
        _text(principal_scope,'original principal scope')
        # Any bounded protocol id carrying an observed native session is a
        # recordable fact; the bound Harness provider decides the dialect later.
        if protocol_id is not None:_text(protocol_id,'observed protocol id');_text(session_id,'fixed session')
        elif session_id is not None:raise ManagerRefused('PROTOCOL_UNSUPPORTED')
        instance=provenance.instance_ref
        key=_digest_of({'namespace':instance.namespace,'instanceId':instance.instance_id})
        payload={'provenance':provenance.projection(),'sessionId':session_id,'protocolId':protocol_id}
        status,record=self.claim(key,'instance-binding',principal=principal_scope,
            target=_canonical(instance.projection()),request_digest=_digest_of(payload),
            payload=payload,operation_ref='instance-binding/'+key)
        if status=='created':
            return self.complete(key,'instance-binding',status='completed',
                operation_ref=record.operation_ref,payload=payload)
        if record.payload!=payload or record.status!='completed':raise ManagerRefused('INSTANCE_BINDING_CONFLICT')
        return record

    def claim(self, request_id, operation, *, principal, target, request_digest, endpoint=None, operation_ref=None, payload=None, turn_id=None):
        """Atomically reserve one operation; a foreign binding is a named conflict."""
        try:
            self._db.execute('BEGIN IMMEDIATE')
            cursor = self._db.execute(
                'SELECT request_id, operation, principal, target, request_digest,'
                ' operation_ref, status, endpoint_json, payload, turn_id FROM operations'
                ' WHERE request_id=? AND operation=?', (request_id, operation))
            existing = cursor.fetchone()
            if existing is not None:
                same = (existing[2] == principal and existing[3] == target
                        and existing[4] == request_digest)
                self._db.execute('COMMIT')
                if not same:
                    raise ManagerRefused('REQUEST_CONFLICT')
                return 'existing', self._row(existing)
            self._db.execute(
                'INSERT INTO operations (request_id, operation, principal, target,'
                ' request_digest, endpoint_json, status, operation_ref, payload, turn_id)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?)',
                (request_id, operation, principal, target, request_digest,
                 None if endpoint is None else json.dumps(endpoint, sort_keys=True),
                 _RESERVED, operation_ref, json.dumps(payload or {},sort_keys=True),turn_id))
            self._db.execute('COMMIT')
            return 'created', self.operation(request_id, operation)
        except ManagerRefused:
            raise
        except sqlite3.Error as error:
            try:
                self._db.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None

    def complete(self, request_id, operation, *, status, operation_ref=None, payload=None,
                 endpoint=None):
        try:
            # Compare-and-set from `reserved` only: a second completion, a
            # regression or a concurrent owner cannot overwrite a recorded
            # outcome, and an already completed row is reported instead.
            cursor = self._db.execute(
                'UPDATE operations SET status=?, operation_ref=?, payload=?, endpoint_json=?'
                ' WHERE request_id=? AND operation=? AND status=?',
                (status, operation_ref, json.dumps(payload or {}, sort_keys=True),
                 None if endpoint is None else json.dumps(endpoint, sort_keys=True),
                 request_id, operation, _RESERVED))
            if cursor.rowcount != 1:
                raise ManagerRefused('RECORD_CHANGED')
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None
        return self.operation(request_id, operation)

    def advance_turn(self, record, *, status, payload):
        """Original protocol owner CAS, never a physical effect or resend.

        Only an in-progress possibly-written row may acquire its first terminal
        observation. Expected full payload includes the monotonic receipt revision.
        A terminal/corrupt/concurrently changed row cannot be overwritten.
        """
        if record.operation!='turn' or record.status!='possibly-written' or status not in ('completed','failed','unknown'):
            raise ManagerRefused('TURN_TRANSITION_INVALID')
        try:
            cursor=self._db.execute('UPDATE operations SET status=?,payload=? WHERE request_id=? '
                'AND operation=? AND operation_ref=? AND turn_id=? AND status=? AND payload=?',
                (status,json.dumps(payload,sort_keys=True),record.request_id,'turn',record.operation_ref,
                 record.turn_id,record.status,json.dumps(record.payload,sort_keys=True)))
            if cursor.rowcount!=1:raise ManagerRefused('RECORD_CHANGED')
            return self.operation(record.request_id,'turn')
        except sqlite3.Error:raise ManagerRefused('RECORDS_UNAVAILABLE') from None

    def finish_bootstrap_phase(self, record, *, status, payload):
        if (record.operation!='bootstrap-frame' or record.status not in ('reserved','possibly-written')
                or status not in ('completed','failed','unknown')
                or status=='completed' and record.status!='possibly-written'):
            raise ManagerRefused('PROTOCOL_TRANSITION_INVALID')
        try:
            changed=self._db.execute('UPDATE operations SET status=?,payload=? WHERE request_id=? AND operation=? AND status=? AND operation_ref=? AND payload=?',
                (status,json.dumps(payload,sort_keys=True),record.request_id,record.operation,record.status,record.operation_ref,json.dumps(record.payload,sort_keys=True)))
            if changed.rowcount!=1:raise ManagerRefused('RECORD_CHANGED')
            return self.operation(record.request_id,record.operation)
        except sqlite3.Error:raise ManagerRefused('RECORDS_UNAVAILABLE') from None

    def finish_bootstrap_observe(self, record, *, status, payload):
        """Terminal CAS for a receive-only bootstrap phase (no physical write).

        Such a phase never becomes ``possibly-written`` because nothing was sent,
        so its own transition is reserved -> completed/failed/unknown.
        """
        if (record.operation!='bootstrap-observe' or record.status!='reserved'
                or status not in ('completed','failed','unknown')):
            raise ManagerRefused('PROTOCOL_TRANSITION_INVALID')
        try:
            changed=self._db.execute('UPDATE operations SET status=?,payload=? WHERE request_id=? AND operation=? AND status=? AND operation_ref=? AND payload=?',
                (status,json.dumps(payload,sort_keys=True),record.request_id,record.operation,record.status,record.operation_ref,json.dumps(record.payload,sort_keys=True)))
            if changed.rowcount!=1:raise ManagerRefused('RECORD_CHANGED')
            return self.operation(record.request_id,record.operation)
        except sqlite3.Error:raise ManagerRefused('RECORDS_UNAVAILABLE') from None

    def advance_native(self,record,*,status,payload):
        """CAS on the original operations table; never a competing effect claim."""
        allowed={'reserved':{'possibly-written','failed','unknown'},
            'possibly-written':{'completed','failed','unknown'}}
        if record.operation!='native-operation' or status not in allowed.get(record.status,set()):
            raise ManagerRefused('NATIVE_TRANSITION_INVALID')
        try:
            cursor=self._db.execute('UPDATE operations SET status=?,payload=? WHERE request_id=? AND operation=? '
                'AND status=? AND operation_ref=? AND payload=?',
                (status,json.dumps(payload,sort_keys=True),record.request_id,record.operation,record.status,
                 record.operation_ref,json.dumps(record.payload,sort_keys=True)))
            if cursor.rowcount!=1:raise ManagerRefused('RECORD_CHANGED')
            return self.operation(record.request_id,record.operation)
        except sqlite3.Error:raise ManagerRefused('RECORDS_UNAVAILABLE') from None

    # -- agent-native/1 journal (same owner and database, additive) -----------

    _NATIVE_V2_TRANSITIONS = {
        'reserved': frozenset({'accepted', 'failed', 'unknown'}),
        'accepted': frozenset({'accepted', 'sent', 'completed', 'failed', 'cancelled',
                               'refused', 'unknown'}),
    }
    _NATIVE_V2_OPERATIONS = frozenset({'native-request', 'native-notify', 'native-reply'})

    def advance_native_v2(self, record, *, status, payload):
        """CAS from the accepted reservation to a later observation.

        The async native surface claims first (``reserved``), marks the durable
        acceptance (``accepted``) before any write, and only then records what
        was observed. A terminal row is never rewritten.
        """
        if (record.operation not in self._NATIVE_V2_OPERATIONS
                or status not in self._NATIVE_V2_TRANSITIONS.get(record.status, frozenset())):
            raise ManagerRefused('NATIVE_TRANSITION_INVALID')
        try:
            cursor = self._db.execute(
                'UPDATE operations SET status=?, payload=? WHERE request_id=? AND operation=?'
                ' AND status=? AND operation_ref IS ? AND payload=?',
                (status, json.dumps(payload, sort_keys=True), record.request_id,
                 record.operation, record.status, record.operation_ref,
                 json.dumps(record.payload, sort_keys=True)))
            if cursor.rowcount != 1:
                raise ManagerRefused('RECORD_CHANGED')
            return self.operation(record.request_id, record.operation)
        except sqlite3.Error:
            raise ManagerRefused('RECORDS_UNAVAILABLE') from None

    def expire_native_operations_for_instance(self, instance_id, *, reason='PROCESS_STOPPED'):
        """After that instance's process is gone, its accepted work is unknown.

        Only the operations positively bound to this instance id are touched; a
        completed/failed/refused row is never rewritten, and no frame is resent.
        """
        if type(instance_id) is not str or not instance_id:
            raise ManagerRefused('VALUE_INVALID', 'instance')
        try:
            rows = self._db.execute(
                "SELECT request_id, operation, status, payload FROM operations"
                " WHERE operation IN ('native-request','native-notify')"
                " AND status IN ('reserved','accepted')").fetchall()
            expired = 0
            for request_id, operation, status, payload_text in rows:
                try:
                    payload = json.loads(payload_text) if payload_text else {}
                except ValueError:
                    continue
                ref = payload.get('instanceRef') if isinstance(payload, dict) else None
                if not isinstance(ref, dict) or ref.get('instanceId') != instance_id:
                    continue
                payload = dict(payload)
                payload['state'] = 'unknown'
                payload['error'] = {'code': reason}
                payload['updatedAt'] = __import__('datetime').datetime.now(
                    __import__('datetime').timezone.utc).isoformat()
                changed = self._db.execute(
                    'UPDATE operations SET status=?, payload=? WHERE request_id=?'
                    ' AND operation=? AND status=?',
                    ('unknown', json.dumps(payload, sort_keys=True), request_id,
                     operation, status))
                expired += changed.rowcount
            return expired
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None

    def expire_unresolved_native_operations(self, *, reason='RESTART_UNCONFIRMED'):
        """A new process cannot resurrect an accepted native operation.

        Called once when the interaction owner starts. Rows still in ``accepted``
        (or the pre-accept ``reserved`` state) have no live receiver in THIS
        process; they become an explicit ``unknown`` fact with a stable reason.
        A completed/failed row is never rewritten.
        """
        try:
            rows = self._db.execute(
                "SELECT request_id, operation, status, operation_ref, payload"
                " FROM operations WHERE operation IN ('native-request','native-notify')"
                " AND status IN ('reserved','accepted')").fetchall()
            expired = 0
            for request_id, operation, status, operation_ref, payload_text in rows:
                try:
                    payload = json.loads(payload_text) if payload_text else {}
                except ValueError:
                    payload = {}
                payload = dict(payload)
                payload['state'] = 'unknown'
                payload['error'] = {'code': reason}
                payload['updatedAt'] = __import__('datetime').datetime.now(
                    __import__('datetime').timezone.utc).isoformat()
                changed = self._db.execute(
                    'UPDATE operations SET status=?, payload=? WHERE request_id=?'
                    ' AND operation=? AND status=?',
                    ('unknown', json.dumps(payload, sort_keys=True), request_id,
                     operation, status))
                expired += changed.rowcount
            return expired
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None

    def journal_state(self, instance_ref):
        try:
            row = self._db.execute(
                'SELECT first_seq, dropped_events, dropped_bytes FROM protocol_journal'
                ' WHERE namespace=? AND instance_id=?',
                (instance_ref.namespace, instance_ref.instance_id)).fetchone()
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None
        return (0, 0, 0) if row is None else (row[0], row[1], row[2])

    def append_event(self, instance_ref, *, kind, operation_ref, payload,
                     connection_generation, observed_at, max_events=4096,
                     max_bytes=8 * 1024 * 1024):
        """Append one inbound frame to the instance journal and return its seq.

        The payload is stored canonical and digested; oversized payloads are the
        caller's explicit decision (a separate ``oversize`` event), never a
        silent truncation here. Eviction is explicit: the journal records the
        first retained seq and cumulative dropped counts.
        """
        try:
            text = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                              ensure_ascii=False, allow_nan=False)
            raw = text.encode('utf-8')
            digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
            self._db.execute('BEGIN IMMEDIATE')
            self._db.execute(
                'INSERT INTO protocol_events (namespace, instance_id, kind, operation_ref,'
                ' payload, payload_digest, payload_bytes, connection_generation, observed_at)'
                ' VALUES (?,?,?,?,?,?,?,?,?)',
                (instance_ref.namespace, instance_ref.instance_id, kind, operation_ref,
                 text, digest, len(raw), connection_generation, observed_at))
            seq = self._db.execute('SELECT last_insert_rowid()').fetchone()[0]
            self._db.execute(
                'INSERT OR IGNORE INTO protocol_journal'
                ' (namespace, instance_id, first_seq, dropped_events, dropped_bytes)'
                ' VALUES (?,?,?,?,?)', (instance_ref.namespace, instance_ref.instance_id, 0, 0, 0))
            rows = self._db.execute(
                'SELECT seq, payload_bytes FROM protocol_events'
                ' WHERE namespace=? AND instance_id=? ORDER BY seq',
                (instance_ref.namespace, instance_ref.instance_id)).fetchall()
            total = sum(row[1] for row in rows)
            excess = max(0, len(rows) - max_events)
            drop = []
            dropped_bytes = 0
            for index, row in enumerate(rows):
                if index < excess or total > max_bytes:
                    drop.append(row[0])
                    dropped_bytes += row[1]
                    total -= row[1]
                else:
                    break
            if drop:
                marks = ','.join('?' * len(drop))
                self._db.execute('DELETE FROM protocol_events WHERE seq IN (' + marks + ')', drop)
                first_retained = rows[len(drop)][0] if len(rows) > len(drop) else seq + 1
                self._db.execute(
                    'UPDATE protocol_journal SET first_seq=?, dropped_events=dropped_events+?,'
                    ' dropped_bytes=dropped_bytes+? WHERE namespace=? AND instance_id=?',
                    (first_retained, len(drop), dropped_bytes,
                     instance_ref.namespace, instance_ref.instance_id))
            self._db.execute('COMMIT')
            return seq
        except sqlite3.Error as error:
            try:
                self._db.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None

    def event_page(self, instance_ref, *, after_seq, limit):
        """Read the journal strictly after a seq; pure read, no state advance."""
        try:
            rows = self._db.execute(
                'SELECT seq, kind, operation_ref, payload, payload_digest, payload_bytes,'
                ' connection_generation, observed_at FROM protocol_events'
                ' WHERE namespace=? AND instance_id=? AND seq>? ORDER BY seq LIMIT ?',
                (instance_ref.namespace, instance_ref.instance_id, after_seq,
                 limit + 1)).fetchall()
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None
        return rows

    def journal_bounds(self, instance_ref):
        """(first_retained_seq, max_seq, dropped_events, dropped_bytes)."""
        try:
            row = self._db.execute(
                'SELECT MIN(seq), MAX(seq) FROM protocol_events'
                ' WHERE namespace=? AND instance_id=?',
                (instance_ref.namespace, instance_ref.instance_id)).fetchone()
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None
        first, last = (0, 0) if row is None else (row[0] or 0, row[1] or 0)
        _, dropped_events, dropped_bytes = self.journal_state(instance_ref)
        return first, last, dropped_events, dropped_bytes

    # -- observed reverse requests (pending replies) -------------------------

    def record_pending(self, instance_ref, *, connection_generation, native_request_id,
                       protocol_id, method, payload, operation_ref, observed_at):
        """Persist one observed reverse request; one row per native request id."""
        try:
            text = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                              ensure_ascii=False, allow_nan=False)
            digest = 'sha256:' + hashlib.sha256(text.encode('utf-8')).hexdigest()
            self._db.execute(
                'INSERT OR IGNORE INTO native_pending (namespace, instance_id,'
                ' connection_generation, native_request_id, protocol_id, method, payload,'
                ' payload_digest, state, operation_ref, observed_at, updated_at)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (instance_ref.namespace, instance_ref.instance_id, connection_generation,
                 native_request_id, protocol_id, method, text, digest, 'pending',
                 operation_ref, observed_at, observed_at))
            row = self._db.execute(
                'SELECT namespace, instance_id, connection_generation, native_request_id,'
                ' protocol_id, method, payload, payload_digest, state, operation_ref,'
                ' observed_at, updated_at FROM native_pending'
                ' WHERE namespace=? AND instance_id=? AND native_request_id=?',
                (instance_ref.namespace, instance_ref.instance_id,
                 native_request_id)).fetchone()
            return dict(zip(('namespace', 'instanceId', 'connectionGeneration',
                             'nativeRequestId', 'protocolId', 'method', 'payload',
                             'payloadDigest', 'state', 'operationRef', 'observedAt',
                             'updatedAt'), row))
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None

    def pending_request(self, instance_ref, native_request_id):
        try:
            row = self._db.execute(
                'SELECT namespace, instance_id, connection_generation, native_request_id,'
                ' protocol_id, method, payload, payload_digest, state, operation_ref,'
                ' observed_at, updated_at FROM native_pending'
                ' WHERE namespace=? AND instance_id=? AND native_request_id=?',
                (instance_ref.namespace, instance_ref.instance_id,
                 native_request_id)).fetchone()
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None
        if row is None:
            return None
        return dict(zip(('namespace', 'instanceId', 'connectionGeneration',
                         'nativeRequestId', 'protocolId', 'method', 'payload',
                         'payloadDigest', 'state', 'operationRef', 'observedAt',
                         'updatedAt'), row))

    def mark_pending(self, instance_ref, native_request_id, *, state, updated_at,
                     expected_state='pending'):
        try:
            changed = self._db.execute(
                'UPDATE native_pending SET state=?, updated_at=?'
                ' WHERE namespace=? AND instance_id=? AND native_request_id=?'
                ' AND state=?',
                (state, updated_at, instance_ref.namespace, instance_ref.instance_id,
                 native_request_id, expected_state))
            return changed.rowcount == 1
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None

    def expire_pending(self, instance_ref, *, updated_at):
        """A process restart cannot answer a live request; keep the fact, mark it."""
        try:
            self._db.execute(
                'UPDATE native_pending SET state=?, updated_at=?'
                ' WHERE namespace=? AND instance_id=? AND state=?',
                ('expired', updated_at, instance_ref.namespace, instance_ref.instance_id,
                 'pending'))
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None

    def pending_requests(self, instance_ref, *, state='pending', limit=64):
        try:
            rows = self._db.execute(
                'SELECT native_request_id FROM native_pending'
                ' WHERE namespace=? AND instance_id=? AND state=? ORDER BY observed_at LIMIT ?',
                (instance_ref.namespace, instance_ref.instance_id, state, limit)).fetchall()
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE', str(error)) from None
        return [row[0] for row in rows]


    def enter_protocol_session(self, key, *, principal, target, turn):
        """Original session's durable single-reader cut, shared by all processes.

        Not a send-effect claim/lease. Active after a crash is never reclaimed by
        time, owner death or another service; unresolved sessions stay unavailable.
        """
        try:
            self._db.execute('BEGIN IMMEDIATE')
            existing=self.operation(key,'protocol-session')
            if existing is not None:
                if (existing.principal,existing.target)!=(principal,target):raise ManagerRefused('SESSION_BINDING_CONFLICT')
                if existing.status!='ready':raise ManagerRefused('SESSION_UNRESOLVED')
            payload=json.dumps({'turnId':turn.turn_id,'parentRequestKey':turn.request_id},sort_keys=True)
            if existing is None:
                self._db.execute('INSERT INTO operations(request_id,operation,principal,target,request_digest,status,operation_ref,payload) VALUES(?,?,?,?,?,?,?,?)',
                    (key,'protocol-session',principal,target,'','active',turn.operation_ref,payload))
            else:
                self._db.execute("UPDATE operations SET status='active',operation_ref=?,payload=? WHERE request_id=? AND operation='protocol-session' AND status='ready'",
                    (turn.operation_ref,payload,key))
            self._db.execute('COMMIT')
            return self.operation(key,'protocol-session')
        except BaseException:
            if self._db.in_transaction:self._db.execute('ROLLBACK')
            raise

    def leave_protocol_session(self, session, *, resolved):
        status='ready' if resolved else 'unknown'
        try:
            changed=self._db.execute('UPDATE operations SET status=? WHERE request_id=? '
                "AND operation='protocol-session' AND status='active' AND operation_ref=? AND payload=?",
                (status,session.request_id,session.operation_ref,json.dumps(session.payload,sort_keys=True)))
            if changed.rowcount!=1:raise ManagerRefused('SESSION_CHANGED')
        except sqlite3.Error:raise ManagerRefused('RECORDS_UNAVAILABLE') from None

    # --- instance lifecycle control (Agent-owned writer fence) ---------------
    #
    # One explicitly versioned control row on the SAME original operations
    # ledger. It stores the original binding identity, current writer epoch and
    # the single pending lifecycle operation; it is not a resource authority.

    def publish_instance_control(self, provenance, start, principal_scope, *, binding_material):
        """Seed control in the SAME transaction that publishes the binding."""
        from .interactions import _canonical,_digest_of
        from ..instances.contracts import InstanceControl,InstanceBindingMaterial,instance_control_key
        if type(binding_material) is not InstanceBindingMaterial:
            raise ManagerRefused('INSTANCE_CONTROL_MATERIAL_REQUIRED')
        material=InstanceBindingMaterial.decode(binding_material.projection())
        self._validate_control_material(provenance,material)
        instance=provenance.instance_ref
        key=instance_control_key(instance)
        payload={'schemaVersion':'agent-instance-control-record/1',
            'bindingMaterial':material.projection(),'control':InstanceControl(instance.namespace,instance.instance_id,
            instance.binding_digest,principal_scope,provenance.endpoint_ref,0,
            'running',None,None).projection()}
        request_digest=_digest_of(payload)
        self._db.execute('INSERT INTO operations (request_id, operation, principal, target,'
            ' request_digest, endpoint_json, status, operation_ref, payload)'
            ' VALUES (?,?,?,?,?,?,?,?,?)',
            (key,'instance-control',principal_scope,_canonical(instance.projection()),
             request_digest,None,'ready','instance-control/'+key,
             json.dumps(payload,sort_keys=True)))
        return self.operation(key,'instance-control')

    @staticmethod
    def _validate_control_material(provenance,material):
        if (material.digest!=provenance.instance_ref.binding_digest or material.endpoint_ref!=provenance.endpoint_ref
                or material.profile_ref!=provenance.profile_ref or material.plan_digest!=provenance.prepared_plan_digest
                or material.directory_binding_digest!=provenance.directory_binding_digest
                or material.source_revision!=provenance.source_revision or material.configuration_refs!=provenance.configuration_refs):
            raise ManagerRefused('INSTANCE_BINDING_MISMATCH')

    def instance_control(self, instance_ref):
        """Read the control row; an old instance without one stays readable but
        is not a lifecycle-effect authority (callers refuse explicitly)."""
        from ..instances.contracts import InstanceControl,InstanceBindingMaterial,instance_control_key
        if type(instance_ref) is not AgentInstanceRef:
            raise ManagerRefused('INSTANCE_REF_REQUIRED')
        row=self.operation(instance_control_key(instance_ref),'instance-control')
        if row is None:
            return None,None
        try:
            if (set(row.payload)!={'schemaVersion','bindingMaterial','control'}
                    or row.payload['schemaVersion']!='agent-instance-control-record/1'):
                raise ManagerRefused('INSTANCE_CONTROL_MATERIAL_REQUIRED')
            value=row.payload['control']
            control=InstanceControl.decode(value)
            material=InstanceBindingMaterial.decode(row.payload['bindingMaterial'])
            from .interactions import BindingProvenance,_canonical,_digest_of
            original=self.operation(instance_control_key(instance_ref),'instance-binding')
            if original is None or original.principal!=control.principal_scope:
                raise ManagerRefused('INSTANCE_CONTROL_ORIGIN_UNAVAILABLE')
            self.validate_instance_origin(original)
            original_provenance=BindingProvenance.decode(original.payload['provenance'])
            self._validate_control_material(original_provenance,material)
            if (original_provenance.instance_ref!=instance_ref or material.digest!=control.binding_digest
                    or material.endpoint_ref!=control.endpoint_ref or row.principal!=control.principal_scope
                    or row.target!=_canonical(instance_ref.projection())
                    or row.status!='ready'):
                raise ManagerRefused('INSTANCE_BINDING_MISMATCH')
        except ManagerRefused:raise
        except Exception:
            raise ManagerRefused('INSTANCE_CONTROL_CORRUPT') from None
        if (control.namespace,control.instance_id,control.binding_digest)!=(instance_ref.namespace,
                instance_ref.instance_id,instance_ref.binding_digest):
            raise ManagerRefused('INSTANCE_BINDING_MISMATCH')
        if row.request_digest!=_digest_of(row.payload):
            raise ManagerRefused('INSTANCE_CONTROL_CORRUPT')
        return control,row

    def writer_epoch(self, instance_ref, principal_scope):
        """Only a current associated instance can reserve a NEW protocol write."""
        control,_row=self.instance_control(instance_ref)
        if control is None:raise ManagerRefused('INSTANCE_CONTROL_UNAVAILABLE')
        if control.principal_scope!=principal_scope:raise ManagerRefused('WRITER_SCOPE_MISMATCH')
        if control.association!='running' or control.active_operation_ref is not None:
            raise ManagerRefused('INSTANCE_WRITER_FENCED')
        return control.writer_epoch

    @contextmanager
    def guard_writer_epoch(self,instance_ref,principal_scope,epoch):
        """Fail-fast original-record fence, held ONLY over synchronous bytes.

        The same DB serializes a new lifecycle claim against this physical cut.
        No timer/lease/takeover or second writer registry is introduced.
        """
        if type(epoch) is not int or epoch<0:raise ManagerRefused('WRITER_EPOCH_UNAVAILABLE')
        if self._db.in_transaction:raise ManagerRefused('WRITER_TRANSACTION_ACTIVE')
        previous=self._db.execute('PRAGMA busy_timeout').fetchone()[0]
        self._db.execute('PRAGMA busy_timeout=0')
        try:
            self._db.execute('BEGIN IMMEDIATE')
            if self.writer_epoch(instance_ref,principal_scope)!=epoch:
                raise ManagerRefused('WRITER_EPOCH_STALE')
            yield
            self._db.execute('COMMIT')
        except BaseException:
            if self._db.in_transaction:self._db.execute('ROLLBACK')
            raise
        finally:self._db.execute('PRAGMA busy_timeout='+str(previous))

    def claim_lifecycle(self, instance_ref, action, *, request_id, principal_scope,
                        request_digest, force):
        """BEGIN IMMEDIATE: fence pending writers, then reserve ONE lifecycle op."""
        from .interactions import _canonical,_digest_of
        from ..instances.contracts import InstanceControl,instance_control_key
        key=_digest_of({'instance':instance_control_key(instance_ref),'action':action,
                        'requestId':request_id})
        operation=action
        target=_canonical(instance_ref.projection())
        previous=self._db.execute('PRAGMA busy_timeout').fetchone()[0]
        self._db.execute('PRAGMA busy_timeout=0')
        try:
            self._db.execute('BEGIN IMMEDIATE')
            control,row=self.instance_control(instance_ref)
            if control is None:
                self._db.execute('ROLLBACK')
                raise ManagerRefused('INSTANCE_CONTROL_UNAVAILABLE')
            if control.principal_scope!=principal_scope:
                self._db.execute('ROLLBACK')
                raise ManagerRefused('LIFECYCLE_OWNER_MISMATCH')
            existing=self.operation(key,operation)
            if existing is not None:
                self._db.execute('ROLLBACK')
                if (existing.principal!=principal_scope or existing.target!=target
                        or existing.request_digest!=request_digest):
                    raise ManagerRefused('REQUEST_CONFLICT')
                return 'existing',control,None,existing
            if control.active_operation_ref is not None:
                self._db.execute('ROLLBACK')
                raise ManagerRefused('LIFECYCLE_BUSY')
            epoch=control.writer_epoch+1
            operation_ref='instance-lifecycle/'+key
            payload={**row.payload,'control':InstanceControl(control.namespace,control.instance_id,
                control.binding_digest,control.principal_scope,control.endpoint_ref,epoch,
                control.association,operation_ref,action).projection()}
            changed=self._db.execute(
                'UPDATE operations SET payload=?, request_digest=? WHERE request_id=? '
                "AND operation='instance-control' AND status='ready' AND payload=?",
                (json.dumps(payload,sort_keys=True),_digest_of(payload),
                 instance_control_key(instance_ref),json.dumps(row.payload,sort_keys=True)))
            if changed.rowcount!=1:
                self._db.execute('ROLLBACK')
                raise ManagerRefused('RECORD_CHANGED')
            self._db.execute('INSERT INTO operations (request_id, operation, principal, target,'
                ' request_digest, endpoint_json, status, operation_ref, payload)'
                ' VALUES (?,?,?,?,?,?,?,?,?)',
                (key,operation,principal_scope,target,request_digest,None,'reserved',
                 operation_ref,json.dumps({'action':action,'force':force},sort_keys=True)))
            self._db.execute('COMMIT')
            return ('created',self.instance_control(instance_ref)[0],
                    json.dumps(payload,sort_keys=True),self.operation(key,operation))
        except ManagerRefused:
            raise
        except sqlite3.Error as error:
            if self._db.in_transaction:
                self._db.execute('ROLLBACK')
            raise ManagerRefused('RECORDS_UNAVAILABLE',str(error)) from None
        finally:
            self._db.execute('PRAGMA busy_timeout='+str(previous))

    def mark_possibly_effected(self, control, record):
        """Durable CAS reserved -> possibly-written immediately before the cut."""
        previous=self._db.execute('PRAGMA busy_timeout').fetchone()[0]
        self._db.execute('PRAGMA busy_timeout=0')
        try:
            changed=self._db.execute(
                'UPDATE operations SET status=? WHERE request_id=? AND operation=? '
                "AND status='reserved' AND operation_ref=? AND payload=?",
                ('possibly-written',record.request_id,record.operation,
                 record.operation_ref,json.dumps(record.payload,sort_keys=True)))
            if changed.rowcount!=1:
                raise ManagerRefused('RECORD_CHANGED')
        except sqlite3.Error as error:
            raise ManagerRefused('RECORDS_UNAVAILABLE',str(error)) from None
        finally:
            self._db.execute('PRAGMA busy_timeout='+str(previous))

    def complete_lifecycle(self, control, control_payload, record, *, status, payload):
        """CAS the row; publish control only against the ORIGINAL claim bytes.

        UNKNOWN keeps the association/epoch AND the active lifecycle operation:
        an unconfirmed instance must keep blocking new lifecycle effects until a
        separate authoritative observation resolves it.
        """
        from ..instances.contracts import InstanceControl,instance_control_key
        from .interactions import _digest_of
        previous=self._db.execute('PRAGMA busy_timeout').fetchone()[0]
        self._db.execute('PRAGMA busy_timeout=0')
        try:
            self._db.execute('BEGIN IMMEDIATE')
            original_control=self.operation(instance_control_key(
                AgentInstanceRef(control.namespace,control.instance_id,control.binding_digest)),
                'instance-control')
            if original_control is None or json.dumps(original_control.payload,sort_keys=True)!=control_payload:
                self._db.execute('ROLLBACK')
                raise ManagerRefused('RECORD_CHANGED')
            changed=self._db.execute(
                'UPDATE operations SET status=?, payload=? WHERE request_id=? AND operation=? '
                "AND status IN ('reserved','possibly-written') AND operation_ref=? AND payload=?",
                (status,json.dumps(payload,sort_keys=True),record.request_id,record.operation,
                 record.operation_ref,json.dumps(record.payload,sort_keys=True)))
            if changed.rowcount!=1:
                self._db.execute('ROLLBACK')
                raise ManagerRefused('RECORD_CHANGED')
            if status=='refused' or (record.operation=='detach' and status=='completed'
                                      and payload.get('associationDetached') is True):
                association=('detached' if record.operation=='detach'
                             and payload.get('associationDetached') is True else control.association)
                new_control=InstanceControl(control.namespace,control.instance_id,control.binding_digest,
                    control.principal_scope,control.endpoint_ref,control.writer_epoch,association,None,None)
                row=self.operation(instance_control_key(
                    AgentInstanceRef(control.namespace,control.instance_id,control.binding_digest)),
                    'instance-control')
                # Compare the EXACT claim-time control bytes, never a fresh read
                # merged with the stale claim control.
                changed=self._db.execute(
                    'UPDATE operations SET payload=?, request_digest=? WHERE request_id=? '
                    "AND operation='instance-control' AND status='ready' AND payload=?",
                    (json.dumps({**original_control.payload,'control':new_control.projection()},sort_keys=True),
                     _digest_of({**original_control.payload,'control':new_control.projection()}),
                     row.request_id,control_payload))
                if changed.rowcount!=1:
                    self._db.execute('ROLLBACK')
                    raise ManagerRefused('RECORD_CHANGED')
            self._db.execute('COMMIT')
        except ManagerRefused:
            raise
        except sqlite3.Error as error:
            if self._db.in_transaction:
                self._db.execute('ROLLBACK')
            raise ManagerRefused('RECORDS_UNAVAILABLE',str(error)) from None
        finally:
            self._db.execute('PRAGMA busy_timeout='+str(previous))
        return self.operation(record.request_id,record.operation)

    def record_instance_exit(self,instance_ref,control,control_payload):
        """Record independently observed exit; never rewrite a signal receipt."""
        from dataclasses import replace
        from ..instances.contracts import instance_control_key
        from .interactions import _digest_of
        if control.active_action not in (None,'stop'):
            return  # Exit does not prove an uncertain detach association.
        updated=replace(control,association='stopped',active_operation_ref=None,active_action=None)
        payload={**json.loads(control_payload),'control':updated.projection()}
        previous=self._db.execute('PRAGMA busy_timeout').fetchone()[0]
        self._db.execute('PRAGMA busy_timeout=0')
        try:
            self._db.execute('BEGIN IMMEDIATE')
            changed=self._db.execute(
                'UPDATE operations SET payload=?,request_digest=? WHERE request_id=? '
                "AND operation='instance-control' AND status='ready' AND payload=?",
                (json.dumps(payload,sort_keys=True),_digest_of(payload),instance_control_key(instance_ref),control_payload))
            if changed.rowcount!=1:raise ManagerRefused('RECORD_CHANGED')
            self._db.execute('COMMIT')
        except BaseException:
            if self._db.in_transaction:self._db.execute('ROLLBACK')
            raise
        finally:self._db.execute('PRAGMA busy_timeout='+str(previous))

    def publish_started_instance(self, start, provenance, session_id, protocol_id, receipt, *, binding_material):
        """Atomically publish original materialization and its start observation."""
        from .interactions import BindingProvenance,_digest_of,_canonical,_text
        from ..instances.contracts import AgentStartReceipt
        if type(provenance) is not BindingProvenance or type(receipt) is not AgentStartReceipt:
            raise ManagerRefused('PROVENANCE_REQUIRED')
        BindingProvenance.decode(provenance.projection())
        # Any bounded protocol id that carries an observed native session is a
        # recordable fact; a session-less start must not invent a session id.
        if protocol_id is not None:
            _text(protocol_id,'observed protocol id')
            _text(session_id,'observed native session')
        elif session_id is not None:raise ManagerRefused('PROTOCOL_UNSUPPORTED')
        if (receipt.state!='running' or receipt.instance_ref!=provenance.instance_ref
                or receipt.session_id!=session_id or receipt.operation_ref!=start.operation_ref):
            raise ManagerRefused('INSTANCE_BINDING_CONFLICT')
        key=_digest_of({'namespace':provenance.instance_ref.namespace,'instanceId':provenance.instance_ref.instance_id})
        payload={'provenance':provenance.projection(),'sessionId':session_id,'protocolId':protocol_id,
            'sourceStartRequestKey':start.request_id}
        try:
            self._db.execute('BEGIN IMMEDIATE')
            self._db.execute('INSERT INTO operations(request_id,operation,principal,target,request_digest,status,operation_ref,payload) VALUES(?,?,?,?,?,?,?,?)',
                (key,'instance-binding',start.principal,_canonical(provenance.instance_ref.projection()),
                 _digest_of(payload),'completed','instance-binding/'+key,json.dumps(payload,sort_keys=True)))
            changed=self._db.execute("UPDATE operations SET status='running',payload=? WHERE request_id=? AND operation='agent-start' AND status='reserved' AND operation_ref=? AND payload=?",
                (json.dumps({'agentStartReceipt':receipt.projection()},sort_keys=True),start.request_id,start.operation_ref,json.dumps(start.payload,sort_keys=True)))
            if changed.rowcount!=1:raise ManagerRefused('RECORD_CHANGED')
            self.publish_instance_control(provenance,start,start.principal,binding_material=binding_material)
            self._db.execute('COMMIT')
        except BaseException:
            if self._db.in_transaction:self._db.execute('ROLLBACK')
            raise


    def validate_instance_origin(self, record):
        """Check sealed original binding and its original start/phase facts."""
        from .interactions import BindingProvenance,_digest_of
        from ..instances.contracts import AgentStartReceipt
        try:
            value=record.payload
            required={'provenance','sessionId','protocolId'}
            if set(value) not in (required,required|{'sourceStartRequestKey'}):raise ValueError()
            if record.request_digest!=_digest_of(value):raise ValueError()
            provenance=BindingProvenance.decode(value['provenance'])
            if 'sourceStartRequestKey' not in value:return
            start=self.operation(value['sourceStartRequestKey'],'agent-start')
            receipt=AgentStartReceipt.decode(start.payload['agentStartReceipt'])
            if (start.status!='running' or receipt.state!='running'
                    or receipt.instance_id!=provenance.instance_ref.instance_id or start.principal!=record.principal
                    or receipt.operation_ref!=start.operation_ref or receipt.instance_ref!=provenance.instance_ref
                    or receipt.process_endpoint_ref!=provenance.endpoint_ref or receipt.session_id!=value['sessionId']):raise ValueError()
            if value['protocolId'] is None:
                if value['sessionId'] is not None:raise ValueError()
                return
            if value['protocolId']=='acp':
                phase=self.operation(start.operation_ref+'/session/new','bootstrap-frame')
                if phase is None or phase.status!='completed' or phase.principal!=start.principal:raise ValueError()
                binding=phase.payload['binding']
                if (binding['endpointRef']!=provenance.endpoint_ref.projection()
                        or binding['profileRef']!=provenance.projection()['profileRef']
                        or binding['planDigest']!=provenance.prepared_plan_digest
                        or binding['directoryBindingDigest']!=provenance.directory_binding_digest):raise ValueError()
                frames=phase.payload['observation']['protocol']['frames']
                replies=[frame for frame in frames if frame.get('id')==phase.operation_ref and 'result' in frame]
                if len(replies)!=1 or replies[0]['result'].get('sessionId')!=value['sessionId']:raise ValueError()
            else:
                # Provider-neutral bootstrap: the owner cannot read the plugin's
                # dialect, so it verifies the guarded-write evidence instead — a
                # completed native frame for this start whose binding matches the
                # published provenance. The session id itself is the trusted
                # provider's observation, exactly like an ACP readback.
                rows=self._db.execute("SELECT request_id,status,principal,payload FROM operations"
                    " WHERE operation='bootstrap-frame' AND request_id LIKE ?",
                    (start.operation_ref+'/%',)).fetchall()
                if not rows:raise ValueError()
                for request_id,status,principal,payload in rows:
                    if status!='completed' or principal!=start.principal:raise ValueError()
                    row_payload=json.loads(payload)
                    binding=row_payload['binding']
                    if (binding.get('schemaVersion')!='agent-lifecycle-native-write-binding/1'
                            or binding['endpointRef']!=provenance.endpoint_ref.projection()
                            or binding['profileRef']!=provenance.projection()['profileRef']
                            or binding['planDigest']!=provenance.prepared_plan_digest
                            or binding['directoryBindingDigest']!=provenance.directory_binding_digest):
                        raise ValueError()
        except Exception:raise ManagerRefused('INSTANCE_ORIGIN_CORRUPT') from None


class AgentManager:
    def __init__(self, resolver, records: Records, *, profile_service=None, harness_resolver=None,
                 preparation_resolver=None, lifecycle_authority=None):
        if not callable(getattr(resolver, 'resolve', None)):
            raise ManagerRefused('ENDPOINT_RESOLVER_UNAVAILABLE')
        if type(records) is not Records:
            raise ManagerRefused('RECORDS_UNAVAILABLE')
        self.resolver = resolver
        self.records = records
        self.profile_service=profile_service
        self.harness_resolver=harness_resolver
        self.preparation_resolver=preparation_resolver
        self.lifecycle_authority=lifecycle_authority

    @staticmethod
    def _same_binding(record, principal, target, request_digest):
        if record is None or not record.request_id:
            raise ManagerRefused('RECORD_CORRUPT')
        # Same request id may be replayed only for the same principal, the same
        # endpoint target and the same input (plan/stop/send) digest.
        if (record.principal != principal or record.target != target
                or record.request_digest != request_digest):
            raise ManagerRefused('REQUEST_CONFLICT')

    @staticmethod
    def _principal(invocation):
        """The caller identity from the platform owner scope (kind + ref)."""
        scope = getattr(invocation, 'owner_scope', None)
        kind = getattr(scope, 'kind', None)
        ref = getattr(scope, 'ref', None)
        if type(kind) is not str or not kind or type(ref) is not str or not ref:
            raise ManagerRefused('INVOCATION_PRINCIPAL_UNAVAILABLE')
        return f'{kind}:{ref}'

    async def _bound(self, endpoint_ref, invocation) -> BoundEndpoint:
        if type(endpoint_ref) is not EndpointRef:
            raise ManagerRefused('ENDPOINT_REF_INVALID')
        bound = await self.resolver.resolve(endpoint_ref, invocation)
        if type(bound) is not BoundEndpoint:
            raise ManagerRefused('ENDPOINT_RESOLUTION_INVALID')
        if bound.ref != endpoint_ref:
            raise ManagerRefused('ENDPOINT_IDENTITY_MISMATCH')
        return bound

    async def _run(self, request_id, operation, endpoint_ref, invocation, request_digest,
                   member, effect, *, extra_payload=None):
        principal = self._principal(invocation)
        target = endpoint_ref.projection()
        # 1) Read authority first: a replay needs history read permission, and a
        #    missing member must refuse *before* any claim exists.
        bound = await self._bound(endpoint_ref, invocation)
        existing = self.records.operation(request_id, operation)
        if existing is not None:
            self._same_binding(existing, principal, json.dumps(target, sort_keys=True),
                               request_digest)
            return existing.observation()
        # 2) A known pre-effect refusal is checked here, so it never leaves a
        #    reservation behind that a later caller could mistake for an attempt.
        if getattr(bound, member) is None:
            raise ManagerRefused(f'{member.upper()}_NOT_GRANTED')
        # 3) Claim: one durable owner per (request, operation). A relative loser
        #    observes the winner's row instead of launching.
        state, record = self.records.claim(
            request_id, operation, principal=principal,
            target=json.dumps(target, sort_keys=True), request_digest=request_digest,
            endpoint=target)
        if state == 'existing':
            self._same_binding(record, principal, json.dumps(target, sort_keys=True),
                               request_digest)
            return record.observation()
        try:
            observation = await effect(getattr(bound, member))
        except BaseException:
            # The reservation stays `reserved`: retrying reports unknown instead
            # of launching a second process.
            raise
        if type(observation) is not LaunchObservation:
            raise ManagerRefused('OBSERVATION_INVALID')
        if operation == 'start':
            validate_launch_observation(observation)
        payload = dict(observation.facts or {})
        if observation.error is not None:
            payload['error'] = observation.error.projection()
        if extra_payload:
            payload.update(extra_payload)
        self.records.complete(request_id, operation, status=observation.status,
                              operation_ref=observation.operation_ref, payload=payload)
        return observation

    async def _launch_once(self, request_id, plan: LaunchPlan, endpoint_ref, invocation) -> LaunchObservation:
        if type(plan) is not LaunchPlan:
            raise ManagerRefused('LAUNCH_PLAN_INVALID')

        async def effect(launcher):
            return await launcher.launch(plan, request_id, invocation)

        return await self._run(request_id, 'start', endpoint_ref, invocation,
                               plan.plan_digest, 'launcher', effect)

    async def start(self, request, endpoint, invocation):
        from ..instances.lifecycle import start_agent
        return await start_agent(self,request,endpoint,invocation)

    def get(self, request_id, invocation):
        from ..instances.lifecycle import read_start
        return read_start(self,request_id,invocation)

    # --- instance lifecycle (stop/detach) ------------------------------------
    #
    # The target is the sealed AgentInstanceRef, never an EndpointRef. Control
    # is read from the same Records ledger, the independent lifecycle authority
    # is consulted before any claim, and the effect runs only through the
    # mandatory guarded member; an unguarded member is a refusal, not a fallback.

    def _lifecycle_authority(self, invocation, control, action):
        authority = self.lifecycle_authority
        check = getattr(authority, 'check_instance_lifecycle', None)
        if not callable(check):
            raise ManagerRefused('LIFECYCLE_AUTHORITY_UNSUPPORTED')
        try:
            check(invocation, control.projection(), action=action)
        except ManagerRefused:
            raise
        except Exception:
            raise ManagerRefused('LIFECYCLE_AUTHORITY_REFUSED') from None

    @contextmanager
    def _lifecycle_authority_context(self, invocation, control, action):
        from contextlib import ExitStack
        guard = getattr(self.lifecycle_authority, 'guard_instance_lifecycle', None)
        if not callable(guard):
            raise ManagerRefused('LIFECYCLE_AUTHORITY_GUARD_UNSUPPORTED')
        with ExitStack() as stack:
            try:
                stack.enter_context(guard(invocation, control.projection(), action=action))
            except ManagerRefused:
                raise
            except Exception:
                raise ManagerRefused('LIFECYCLE_AUTHORITY_REFUSED') from None
            yield

    def _lifecycle_read_authority(self, invocation, instance_id):
        """A replay needs the current READ authority, never the write grant."""
        check = getattr(self.lifecycle_authority, 'check_read_instance', None)
        if not callable(check):
            raise ManagerRefused('LIFECYCLE_AUTHORITY_UNSUPPORTED')
        try:
            check(invocation, instance_id)
        except ManagerRefused:
            raise
        except Exception:
            raise ManagerRefused('LIFECYCLE_AUTHORITY_REFUSED') from None

    @staticmethod
    def _guarded_member(bound, action):
        member = getattr(bound, 'terminate' if action == 'stop' else 'detach', None)
        name = 'terminate_guarded' if action == 'stop' else 'detach_guarded'
        if member is None or not callable(getattr(member, name, None)):
            raise ManagerRefused('GUARDED_LIFECYCLE_UNAVAILABLE')
        return member

    def _lifecycle_guard(self, instance_ref, record, control, invocation, action, deadline):
        import asyncio, threading
        task, thread = asyncio.current_task(), threading.get_ident()
        state = {'used': False}

        @contextmanager
        def guard():
            if state['used']:
                raise ManagerRefused('LIFECYCLE_GUARD_REUSED')
            state['used'] = True
            if asyncio.current_task() is not task or threading.get_ident() != thread:
                raise ManagerRefused('LIFECYCLE_GUARD_CONTEXT_CHANGED')
            with self._lifecycle_authority_context(invocation, control, action):
                current, _row = self.records.instance_control(instance_ref)
                if (current is None or current.writer_epoch != control.writer_epoch
                        or current.active_operation_ref != record.operation_ref
                        or current.active_action != action
                        or current.principal_scope != control.principal_scope
                        or current.binding_digest != control.binding_digest
                        or current.endpoint_ref != control.endpoint_ref):
                    raise ManagerRefused('LIFECYCLE_EPOCH_CHANGED')
                if asyncio.get_running_loop().time()>=deadline:
                    raise ManagerRefused('LIFECYCLE_DEADLINE_ELAPSED')
                # Current original authority is rechecked at the physical cut.
                self._lifecycle_authority(invocation, current, action)
                # Durable possibly-effected CAS before the OS mutation.
                self.records.mark_possibly_effected(control, record)
                if asyncio.get_running_loop().time()>=deadline:
                    raise ManagerRefused('LIFECYCLE_DEADLINE_ELAPSED')
                yield
        return guard

    @staticmethod
    def _validate_lifecycle_observation(action, observation):
        try:
            return validate_lifecycle_observation(action, observation)
        except Exception:
            raise ManagerRefused('OBSERVATION_INVALID') from None

    async def _lifecycle(self, action, request_id, instance_ref, invocation, *, force=False, deadline=None):
        from .prepare import canonical_digest
        from ..instances.contracts import instance_control_key
        if type(instance_ref) is not AgentInstanceRef:
            raise ManagerRefused('INSTANCE_REF_REQUIRED')
        if type(request_id) is not str or not request_id:
            raise ManagerRefused('REQUEST_ID_REQUIRED')
        principal = self._principal(invocation)
        control, _row = self.records.instance_control(instance_ref)
        if control is None:
            # A v1 instance without authenticated control material stays readable;
            # it is not a lifecycle-effect authority.
            raise ManagerRefused('INSTANCE_CONTROL_UNAVAILABLE')
        if (control.namespace, control.instance_id) != (instance_ref.namespace, instance_ref.instance_id):
            raise ManagerRefused('INSTANCE_BINDING_MISMATCH')
        request_digest = canonical_digest({'action': action,
                                           'instance': instance_control_key(instance_ref),
                                           'force': bool(force),
                                           'endpoint': control.endpoint_ref.projection()})
        key = canonical_digest({'instance': instance_control_key(instance_ref),
                                'action': action, 'requestId': request_id})
        existing = self.records.operation(key, action)
        if existing is not None:
            if (existing.principal != principal
                    or existing.request_digest != request_digest):
                raise ManagerRefused('REQUEST_CONFLICT')
            self._lifecycle_read_authority(invocation, instance_ref.instance_id)
            return self._validate_lifecycle_observation(action, existing.observation())
        import asyncio,math
        if deadline is None:deadline=asyncio.get_running_loop().time()+30
        if (type(deadline) not in (int,float) or not math.isfinite(deadline)
                or deadline<=asyncio.get_running_loop().time()):
            raise ManagerRefused('LIFECYCLE_DEADLINE_ELAPSED')
        self._lifecycle_authority(invocation, control, action)
        bound = await self._bound(control.endpoint_ref, invocation)
        if bound.ref != control.endpoint_ref:
            raise ManagerRefused('ENDPOINT_IDENTITY_MISMATCH')
        # Mandatory guarded support is proven BEFORE the claim advances the
        # instance epoch/control; a missing member must not change writer state.
        self._guarded_member(bound, action)
        with self._lifecycle_authority_context(invocation, control, action):
            state, claimed, claimed_payload, record = self.records.claim_lifecycle(
                instance_ref, action, request_id=request_id, principal_scope=principal,
                request_digest=request_digest, force=bool(force))
        if state == 'existing':
            return self._validate_lifecycle_observation(action, record.observation())
        try:
            if action == 'stop':
                observation = await lifecycle_guarded(
                    bound, 'stop', request_id, invocation,
                    binding=claimed.projection(),
                    guard=self._lifecycle_guard(instance_ref, record, claimed, invocation, action, deadline),
                    force=bool(force))
            else:
                observation = await lifecycle_guarded(
                    bound, 'detach', request_id, invocation,
                    binding=claimed.projection(),
                    guard=self._lifecycle_guard(instance_ref, record, claimed, invocation, action, deadline))
        except ManagerRefused as error:
            # The guard is synchronous: a refusal there happens BEFORE the
            # durable possibly-effected CAS and before any OS mutation, so zero
            # effect is provable and the claim becomes a known refusal. A row
            # already in possibly-written means the cut was entered: keep it
            # uncertain and never describe it as a refusal.
            recorded = self.records.operation(record.request_id, record.operation)
            if recorded is not None and recorded.status == 'reserved':
                self.records.complete_lifecycle(
                    claimed, claimed_payload, record, status='refused',
                    payload={'error': {'code': error.code,
                                       'diagnostic': 'lifecycle guard refused before the cut'}})
            raise
        except EndpointValueError as error:
            recorded = self.records.operation(record.request_id, record.operation)
            known_zero = recorded is not None and recorded.status == 'reserved'
            self.records.complete_lifecycle(claimed, claimed_payload, record,
                status='refused' if known_zero else 'unknown',
                payload={'error': {'code': str(error) if known_zero else 'OPERATION_UNCONFIRMED',
                    'diagnostic': 'lifecycle member unavailable' if known_zero else 'lifecycle effect uncertain'}})
            raise ManagerRefused(str(error) if known_zero else 'OPERATION_UNCONFIRMED') from None
        except Exception:
            # A transport/endpoint error after the claim may have effected the
            # resource: record unknown, never a pre-effect refusal or a resend.
            self.records.complete_lifecycle(claimed, claimed_payload, record, status='unknown',
                                            payload={'error': {'code': 'OPERATION_UNCONFIRMED',
                                                               'diagnostic': 'lifecycle effect uncertain'}})
            raise ManagerRefused('OPERATION_UNCONFIRMED') from None
        self._validate_lifecycle_observation(action, observation)
        current=self.records.operation(record.request_id,record.operation)
        if observation.status in ('accepted','completed') and (current is None or current.status!='possibly-written'):
            self.records.complete_lifecycle(claimed,claimed_payload,record,status='unknown',
                payload={'error':{'code':'OPERATION_UNCONFIRMED','diagnostic':'physical lifecycle guard was not entered'}})
            raise ManagerRefused('OPERATION_UNCONFIRMED')
        payload = {**dict(observation.facts or {}),'endpointObservation':observation.projection()}
        if observation.error is not None:
            payload['error'] = observation.error.projection()
        completed = self.records.complete_lifecycle(claimed, claimed_payload, record,
                                                    status=observation.status, payload=payload)
        # Both the first call and its replay return the SAME stored receipt.
        return completed.observation()

    async def stop(self, request_id, instance_ref, invocation, *, force=False, deadline=None):
        return await self._lifecycle('stop', request_id, instance_ref, invocation, force=force, deadline=deadline)

    async def detach(self, request_id, instance_ref, invocation, *, deadline=None):
        return await self._lifecycle('detach', request_id, instance_ref, invocation, deadline=deadline)

    async def reconcile(self,instance_ref,invocation,*,deadline=None):
        """Explicit original observe only: no restart, reattach or resend."""
        import asyncio,math
        from .endpoint import ProcessObservation
        if type(instance_ref) is not AgentInstanceRef:raise ManagerRefused('INSTANCE_REF_REQUIRED')
        if deadline is not None and (type(deadline) not in (int,float) or not math.isfinite(deadline)
                                    or deadline<=asyncio.get_running_loop().time()):
            raise ManagerRefused('OBSERVATION_DEADLINE_ELAPSED')
        self._lifecycle_read_authority(invocation,instance_ref.instance_id)
        control,row=self.records.instance_control(instance_ref)
        if control is None:raise ManagerRefused('INSTANCE_CONTROL_UNAVAILABLE')
        if control.principal_scope!=self._principal(invocation):raise ManagerRefused('LIFECYCLE_OWNER_MISMATCH')
        captured=json.dumps(row.payload,sort_keys=True)
        bound=await self._bound(control.endpoint_ref,invocation)
        observe=getattr(bound.observe,'observe',None)
        if not callable(observe):raise ManagerRefused('OBSERVE_CAPABILITY_UNAVAILABLE')
        observed=await observe(deadline,invocation)
        if type(observed) is not ProcessObservation:raise ManagerRefused('OBSERVATION_INVALID')
        self._lifecycle_read_authority(invocation,instance_ref.instance_id)
        if observed.state=='exited' and control.association!='detached':
            self.records.record_instance_exit(instance_ref,control,captured)
        return observed

    async def send_prompt(self, request_id, instance_ref, invocation, *, prompt,
                          interaction_service, engineering_attempt_ref, write_guard, deadline):
        """Delegate to the SAME original parent owner; never claim after send."""
        from .interactions import InteractionService
        if type(interaction_service) is not InteractionService or interaction_service.records is not self.records:
            raise ManagerRefused('ORIGINAL_INTERACTION_RECORDS_REQUIRED')
        try:
            return await interaction_service.prompt_recorded(instance_ref,prompt,request_id=request_id,
                engineering_attempt_ref=engineering_attempt_ref,invocation=invocation,
                write_guard=write_guard,deadline=deadline)
        finally:
            # This exact externally issued operation ended, including cancellation
            # or a publication failure. No later handoff may revive its reserves.
            interaction_service.invalidate_invocation(invocation)


__all__ = ['ManagerRefused', 'Record', 'Records', 'AgentManager']
