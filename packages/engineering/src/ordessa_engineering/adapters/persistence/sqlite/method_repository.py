"""Method histories and CAS on the original Engineering UoW, not a catalog."""
from dataclasses import asdict
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_controls import MethodControl, MethodAdoption
from ordessa_engineering.domain.common.models.values import Digest, MAX_VERSION
from ordessa_engineering.domain.common.mechanisms.codec import canonical_value
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from .method_schema import METHOD_SCHEMA_VERSION
from .implementation_schema import IMPLEMENTATION_SCHEMA_VERSION, IMPLEMENTATION_DDL, IMPLEMENTATION_TABLES
from .submission_schema import SUBMISSION_SCHEMA_VERSION, SUBMISSION_DDL, IMPLEMENTATION_APPLY_DDL
from .dispatch_schema import (DISPATCH_SCHEMA_VERSION, DISPATCH_DDL,
                              WORK_DISPATCH_SCHEMA_VERSION)
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .external_record_schema import EXTERNAL_RECORD_SCHEMA_VERSION


def _method(value):
    if type(value) is not dict or set(value) != {'method_id','release_version','schema_version','snapshot_digest'}:
        raise ApplicationError('METHOD_STATE_CORRUPT')
    digest=value['snapshot_digest']
    if type(digest) is not dict or set(digest) != {'algorithm','hex'}:
        raise ApplicationError('METHOD_STATE_CORRUPT')
    return MethodRef(value['method_id'],value['release_version'],value['schema_version'],Digest(**digest))


class SQLiteMethodRepository:
    def __init__(self, access):
        self.access=access

    def _check(self):
        self.access.check_active()
        if getattr(self.access._connection,'_ordessa_schema_version',None) not in (METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
            raise ApplicationError('METHOD_CONTROL_SCHEMA_REQUIRED')

    def _prefix(self):
        self._check()
        return (self.access.scope.realm_id,self.access.scope.project_id)

    def read_snapshot(self, method):
        """Verify the original immutable source inside this existing UoW."""
        self._check()
        if type(method) is not MethodRef:
            raise ApplicationError('INVALID_INPUT')
        from ordessa_engineering.methods.definitions.models import MethodRef as SnapshotRef
        from .snapshot_store import load_snapshot
        snapshot,_=load_snapshot(self.access._connection,self.access.authority_id,
            SnapshotRef(method.method_id,method.release_version,method.schema_version,method.snapshot_digest.hex))
        return snapshot

    def control(self, method):
        row=self.access.execute('SELECT enabled,version,event_ref FROM eng_method_controls WHERE realm_id=? AND project_id=? AND method_snapshot_digest=?',self._prefix()+(method.snapshot_digest.hex,)).fetchone()
        if row is None:
            raise ApplicationError('METHOD_CONTROL_UNAVAILABLE')
        event=self.access.execute('SELECT canonical_bytes FROM eng_method_control_events WHERE realm_id=? AND project_id=? AND method_snapshot_digest=? AND version=?',self._prefix()+(method.snapshot_digest.hex,row[1])).fetchone()
        if event is None:
            raise ApplicationError('METHOD_STATE_CORRUPT')
        value=canonical_value(event[0])
        if type(value) is not dict or set(value) != {'control','reason','occurred_at'}:
            raise ApplicationError('METHOD_STATE_CORRUPT')
        control=MethodControl(self.access.scope,method,bool(row[0]),row[1],Digest('sha256',row[2]))
        if canonical_bytes(value['control']) != canonical_bytes(asdict(control)):
            raise ApplicationError('METHOD_STATE_CORRUPT')
        return control

    def control_by_digest(self, digest):
        row=self.access.execute('SELECT e.canonical_bytes FROM eng_method_control_events e JOIN eng_method_controls c ON e.realm_id=c.realm_id AND e.project_id=c.project_id AND e.method_snapshot_digest=c.method_snapshot_digest AND e.version=c.version WHERE c.realm_id=? AND c.project_id=? AND c.method_snapshot_digest=?',self._prefix()+(digest,)).fetchone()
        if row is None:
            raise ApplicationError('METHOD_CONTROL_UNAVAILABLE')
        value=canonical_value(row[0])
        return self.control(_method(value['control']['method_ref']))

    def selected(self):
        row=self.access.execute('SELECT adoption_id,version,method_snapshot_digest,canonical_bytes FROM eng_method_adoptions WHERE realm_id=? AND project_id=? ORDER BY version DESC LIMIT 1',self._prefix()).fetchone()
        if row is None:
            raise ApplicationError('METHOD_SELECTION_UNAVAILABLE')
        value=canonical_value(row[3])
        if type(value) is not dict or set(value) != {'scope','adoption_id','method_ref','compiled_plan_digest','version','event_ref','occurred_at'}:
            raise ApplicationError('METHOD_STATE_CORRUPT')
        adoption=MethodAdoption(self.access.scope,value['adoption_id'],_method(value['method_ref']),Digest(**value['compiled_plan_digest']),value['version'],Digest(**value['event_ref']),value['occurred_at'])
        if (row[:3] != (adoption.adoption_id,adoption.version,adoption.method_ref.snapshot_digest.hex) or canonical_bytes(asdict(adoption)) != row[3]):
            raise ApplicationError('METHOD_STATE_CORRUPT')
        return adoption

    def select(self, method, adoption_id, expected_version, event_ref, occurred_at, compiled_plan_digest):
        self.access.require_write();self._check()
        try: current=self.selected().version
        except ApplicationError as exc:
            if exc.code != 'METHOD_SELECTION_UNAVAILABLE': raise
            current=0
        if current != expected_version:
            raise ApplicationError('METHOD_SELECTION_CHANGED')
        if current == MAX_VERSION:
            raise ApplicationError('VERSION_EXHAUSTED')
        try: control=self.control(method)
        except ApplicationError as exc:
            if exc.code != 'METHOD_CONTROL_UNAVAILABLE': raise
            control=MethodControl(self.access.scope,method,True,0,event_ref)
            self.access.execute('INSERT INTO eng_method_controls VALUES (?,?,?,?,?,?)',self._prefix()+(method.snapshot_digest.hex,1,0,event_ref.hex))
            self._event(control,'explicit adoption',occurred_at)
        if not control.enabled:
            raise ApplicationError('METHOD_DISABLED')
        adoption=MethodAdoption(self.access.scope,adoption_id,method,compiled_plan_digest,current+1,event_ref,occurred_at)
        self.access.execute('INSERT INTO eng_method_adoptions VALUES (?,?,?,?,?,?)',self._prefix()+(adoption_id,adoption.version,method.snapshot_digest.hex,canonical_bytes(asdict(adoption))))
        return adoption

    def _event(self, control, reason, occurred_at):
        self.access.execute('INSERT INTO eng_method_control_events VALUES (?,?,?,?,?)',self._prefix()+(control.method_ref.snapshot_digest.hex,control.version,canonical_bytes(dict(control=asdict(control),reason=reason,occurred_at=occurred_at))))

    def set_control(self, method, expected_version, enabled, event_ref, reason, occurred_at):
        self.access.require_write()
        current=self.control(method)
        if current.version != expected_version:
            raise ApplicationError('METHOD_CONTROL_CHANGED')
        if current.version == MAX_VERSION:
            raise ApplicationError('VERSION_EXHAUSTED')
        control=MethodControl(self.access.scope,method,enabled,current.version+1,event_ref)
        result=self.access.execute('UPDATE eng_method_controls SET enabled=?,version=?,event_ref=? WHERE realm_id=? AND project_id=? AND method_snapshot_digest=? AND version=?',(int(enabled),control.version,event_ref.hex)+self._prefix()+(method.snapshot_digest.hex,expected_version))
        if result.rowcount != 1:
            raise ApplicationError('METHOD_CONTROL_CHANGED')
        self._event(control,reason,occurred_at)
        return control

    def control_declaration(self, method, expected_version, enabled, event_ref, reason, occurred_at):
        """Explicit initial control for an already published declaration.

        Called only by the original guarded management command. It uses the
        original control/event tables and does not select or compile a method.
        Publication itself never calls this operation.
        """
        self.access.require_write();self._check()
        if type(method) is not MethodRef or method.schema_version != 2:
            raise ApplicationError('INVALID_INPUT')
        try:
            self.control(method)
        except ApplicationError as exc:
            if exc.code != 'METHOD_CONTROL_UNAVAILABLE':
                raise
            if expected_version != 0:
                raise ApplicationError('METHOD_CONTROL_CHANGED')
            control=MethodControl(self.access.scope,method,enabled,1,event_ref)
            self.access.execute('INSERT INTO eng_method_controls VALUES (?,?,?,?,?,?)',
                self._prefix()+(method.snapshot_digest.hex,int(enabled),1,event_ref.hex))
            self._event(control,reason,occurred_at)
            return control
        return self.set_control(method,expected_version,enabled,event_ref,reason,occurred_at)

    def check_guard(self, control, selection=None):
        if control.scope != self.access.scope:
            return  # different scope UoWs do not consume this temporary guard
        if self.control(control.method_ref) != control:
            raise ApplicationError('METHOD_CONTROL_CHANGED')
        if not control.enabled:
            raise ApplicationError('METHOD_DISABLED')
        if selection is not None and self.selected() != selection:
            raise ApplicationError('METHOD_SELECTION_CHANGED')
