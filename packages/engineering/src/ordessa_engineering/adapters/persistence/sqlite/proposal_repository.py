"""Proposal/change/control records on the caller's original Engineering UoW."""
from .submission_schema import SUBMISSION_SCHEMA_VERSION
from .dispatch_schema import (DISPATCH_SCHEMA_VERSION, DISPATCH_DDL,
                              WORK_DISPATCH_SCHEMA_VERSION)
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .external_record_schema import EXTERNAL_RECORD_SCHEMA_VERSION
from dataclasses import asdict
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.changes.refs import (ProposalRef)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.models.values import (Digest, validate_id)
from ordessa_engineering.domain.common.mechanisms.hashing import (record_digest)
from ordessa_engineering.domain.common.mechanisms.codec import (canonical_value)
from ordessa_engineering.domain.common.models.values import (utc_instant)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.domain.common.mechanisms.codec import (require_object, decode_actor, decode_digest)
from ordessa_engineering.domain.changes.models import Change, Proposal, ProposalControl
from ordessa_engineering.domain.changes.codec import (
    encode_proposal,
    decode_proposal,
    encode_control,
    decode_control,
)
from ordessa_engineering.domain.changes.operations import validate_change_set
from ordessa_engineering.domain.common.models.values import (validate_version, validate_text, MAX_VERSION)
from .artifact_repository import SQLiteArtifactRepository
from .material_validation import MaterialBudget
from ordessa_engineering.application.usecases.proposal_closure import coordinate_closure
from ordessa_engineering.application.contracts.access import proposal_validation_key

_BYTES="CASE WHEN typeof(canonical_bytes)='blob' AND length(canonical_bytes)<=2097152 THEN canonical_bytes ELSE NULL END"


def _decode(function,raw):
    try:
        return function(raw)
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ApplicationError('RECORD_CORRUPT') from None


def _event(control,at,actor,reason):
    utc_instant(at)
    if type(actor) is not ActorRef:
        raise ReferenceError('INVALID_SCHEMA')
    validate_text(reason)
    data={'control':asdict(control),'created_at':at,'created_by':asdict(actor),'reason':reason}
    return canonical_bytes({**data,'digest':asdict(record_digest('proposal-control-event',data))})


def _decode_event(raw):
    value=canonical_value(raw)
    require_object(value,{'control','created_at','created_by','reason','digest'}, code='INVALID_REVISION')
    control=decode_control(canonical_bytes(value['control']))
    actor=decode_actor(value['created_by'])
    if _event(control,value['created_at'],actor,value['reason'])!=raw:
        raise ReferenceError('INVALID_SCHEMA')
    return control,value['created_at'],actor,value['reason']


class SQLiteProposalRepository:
    def __init__(self,access):
        self.access=access
        self.artifacts=SQLiteArtifactRepository(access)

    def _prefix(self):
        self.access.check_active()
        if type(self.access.scope) is not Scope:
            raise ApplicationError('SCOPE_MISMATCH')
        return self.access.scope.realm_id,self.access.scope.project_id

    def _ref(self,ref):
        if type(ref) is not ProposalRef:
            raise ApplicationError('INVALID_ARGUMENT')
        if (ref.realm_id,ref.project_id)!=self._prefix():
            raise ApplicationError('SCOPE_MISMATCH')

    def create_change(self,change):
        self.access.require_write()
        if type(change) is not Change or change.scope!=self.access.scope or change.version!=0 or change.proposal_ids or change.selected_proposal_id is not None:
            raise ApplicationError('INVALID_ARGUMENT')
        self.access.execute('INSERT INTO eng_changes VALUES (?,?,?,?,NULL,0)',self._prefix()+(change.change_id,change.created_at))

    def get_change(self,change_id):
        try:
            validate_id(change_id)
        except ReferenceError:
            raise ApplicationError('INVALID_ARGUMENT') from None
        row=self.access.execute('SELECT created_at,selected_proposal_id,version FROM eng_changes WHERE realm_id=? AND project_id=? AND change_id=?',self._prefix()+(change_id,)).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        proposals=self.access.execute('SELECT proposal_id FROM eng_proposals WHERE realm_id=? AND project_id=? AND change_id=? ORDER BY proposal_id LIMIT 4097',self._prefix()+(change_id,)).fetchall()
        try:
            return Change(self.access.scope,change_id,row[0],tuple(p[0] for p in proposals),row[1],row[2])
        except (ReferenceError,TypeError,ValueError):
            raise ApplicationError('RECORD_CORRUPT') from None

    def read_proposal(self,ref,budget):
        """Read + canonical-decode one proposal record on this active scope.

        Adapter read primitive only (no business validation). The application
        closure consumes it through ``ProposalReadPort``.
        """
        self._ref(ref)
        if ref in budget.proposal_rows:
            return budget.proposal_rows[ref]
        row=self.access.execute('SELECT change_id,digest,schema_version,'+_BYTES+' FROM eng_proposals WHERE realm_id=? AND project_id=? AND proposal_id=?',self._prefix()+(ref.proposal_id,)).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        record=_decode(decode_proposal,row[3])
        if record.ref!=ref or row[:3]!=(record.change_id,record.digest.hex,record.schema_version):
            raise ApplicationError('RECORD_CORRUPT')
        budget.record(('proposal',ref),row[3])
        rows=self.access.execute('SELECT position,artifact_id,operation,base_revision_id,proposed_revision_id FROM eng_proposal_mutations WHERE realm_id=? AND project_id=? AND proposal_id=? ORDER BY position LIMIT 4097',self._prefix()+(ref.proposal_id,)).fetchall()
        expected=[(i,m.artifact_id,m.operation,None if m.base_ref is None else m.base_ref.revision_id,m.proposed_ref.revision_id) for i,m in enumerate(record.mutations)]
        if rows!=expected:
            raise ApplicationError('RECORD_CORRUPT')
        budget.proposal_rows[ref]=record
        return record

    def resolve_revision_graph(self,roots,budget):
        """Adapter read primitive: resolve the exact revision graph on this scope."""
        return self.artifacts.resolve_graph(roots,budget=budget)

    def select_artifact(self,scope,artifact_id):
        """Adapter read primitive: select one artifact owner on this scope."""
        return self.artifacts._select_artifact(scope,artifact_id)

    def get_proposal(self,ref,*,budget=None):
        budget=MaterialBudget(self.access) if budget is None else budget
        if type(budget) is not MaterialBudget or budget.access is not self.access:
            raise ApplicationError('INVALID_ARGUMENT')
        self._ref(ref)
        if ref in budget.proposals:
            return budget.proposals[ref]
        record=self.read_proposal(ref,budget)
        try:
            # Read-integrity closure, orchestrated by the application coordinate.
            _,validated=coordinate_closure(record,self,budget)
        except ReferenceError as exc:
            raise ApplicationError('RECORD_CORRUPT') from exc
        budget.proposals.update({ref:value for ref,value in validated.items() if ref in budget.proposal_rows})
        budget.proposals[ref]=record
        return record

    def resolve_repository_baseline(self, ref, budget):
        from .implementation_schema import IMPLEMENTATION_SCHEMA_VERSION
        from .implementation_repository import SQLiteImplementationRepository
        from ordessa_engineering.domain.changes.repository_baseline_codec import encode_repository_baseline
        if getattr(self.access._connection, '_ordessa_schema_version', None) not in (IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
            raise ApplicationError('IMPLEMENTATION_BASELINE_AUTHORITY_UNAVAILABLE')
        if type(budget) is not MaterialBudget or budget.access is not self.access:
            raise ApplicationError('INVALID_ARGUMENT')
        record = SQLiteImplementationRepository(self.access).resolve_repository_baseline(ref)
        budget.record(('repository-baseline', ref), encode_repository_baseline(record))
        for file in record.files:
            budget.read(file.blob_ref)
        return record

    def validated_budget(self):
        """Open a short-lived per-operation validation budget on this UoW/readset.

        The application triggers ``validate_create`` (proposal_closure) against
        it; ``create_proposal`` then requires the same budget to carry the
        marker. One UoW may open several independent budgets (per-operation
        accounting preserved).
        """
        budget=MaterialBudget(self.access)
        self._material_budget=budget
        return budget

    def create_proposal(self,record,*,expected_version,budget,requirements):
        self.access.require_write()
        if type(record) is not Proposal or record.scope!=self.access.scope:
            raise ApplicationError('INVALID_ARGUMENT')
        validate_version(expected_version)
        raw=encode_proposal(record)
        if decode_proposal(raw)!=record:
            raise ApplicationError('INVALID_ARGUMENT')
        key=proposal_validation_key(record)
        if type(budget) is not MaterialBudget or budget.access is not self.access or not budget.is_validated(key):
            raise ApplicationError('PROPOSAL_VALIDATION_REQUIRED')
        bound=budget.validated_result(key)
        if bound is None or requirements!=bound:
            # The write consumes only the validated result; a substituted or
            # emptied argument cannot match the bound value.
            raise ApplicationError('PROPOSAL_VALIDATION_REQUIRED')
        budget.record(('proposal',record.ref),raw)
        change=self.get_change(record.change_id)
        existing=self.access.execute('SELECT '+_BYTES+' FROM eng_proposals WHERE realm_id=? AND project_id=? AND proposal_id=?',self._prefix()+(record.proposal_id,)).fetchone()
        if existing is not None:
            if existing[0]!=raw:
                raise ApplicationError('PROPOSAL_IDENTITY_CONFLICT')
            return self.get_proposal(record.ref).ref
        if change.version!=expected_version:
            raise ApplicationError('VERSION_CONFLICT')
        if change.version==MAX_VERSION or len(change.proposal_ids)>=4096:
            raise ApplicationError('VERSION_EXHAUSTED')
        self.access.execute('INSERT INTO eng_proposals VALUES (?,?,?,?,?,?,?)',self._prefix()+(record.proposal_id,record.change_id,record.digest.hex,record.schema_version,raw))
        for i,m in enumerate(record.mutations):
            self.access.execute('INSERT INTO eng_proposal_mutations VALUES (?,?,?,?,?,?,?,?)',self._prefix()+(record.proposal_id,i,m.artifact_id,m.operation,None if m.base_ref is None else m.base_ref.revision_id,m.proposed_ref.revision_id))
        control=ProposalControl(record.ref)
        self.access.execute('INSERT INTO eng_proposal_controls VALUES (?,?,?,0,?)',self._prefix()+(record.proposal_id,encode_control(control)))
        self.access.execute('INSERT INTO eng_proposal_control_events VALUES (?,?,?,0,?)',self._prefix()+(record.proposal_id,_event(control,record.created_at,record.created_by,'created')))
        cursor=self.access.execute('UPDATE eng_changes SET version=version+1 WHERE realm_id=? AND project_id=? AND change_id=? AND version=?',self._prefix()+(record.change_id,expected_version))
        if cursor.rowcount!=1:
            raise ApplicationError('VERSION_CONFLICT')
        # Freeze only a reread of the actual immutable row/index in this TX.
        self.read_proposal(record.ref,budget)
        budget.proposals[record.ref]=record
        from .review_repository import SQLiteReviewRepository
        reviews=SQLiteReviewRepository(self.access)
        for requirement in bound:
            reviews.ensure_requirement(requirement,budget=budget)
        return record.ref

    def get_control(self,ref,*,budget=None):
        record=self.get_proposal(ref,budget=budget)
        row=self.access.execute('SELECT version,'+_BYTES+' FROM eng_proposal_controls WHERE realm_id=? AND project_id=? AND proposal_id=?',self._prefix()+(ref.proposal_id,)).fetchone()
        if row is None:
            raise ApplicationError('RECORD_CORRUPT')
        control=_decode(decode_control,row[1])
        if control.proposal_ref!=ref or control.version!=row[0] or control.version>1:
            raise ApplicationError('RECORD_CORRUPT')
        events=self.access.execute('SELECT version,'+_BYTES+' FROM eng_proposal_control_events WHERE realm_id=? AND project_id=? AND proposal_id=? ORDER BY version LIMIT 3',self._prefix()+(ref.proposal_id,)).fetchall()
        if len(events)!=control.version+1:
            raise ApplicationError('RECORD_CORRUPT')
        for i,(v,raw) in enumerate(events):
            event,at,actor,reason=_decode(_decode_event,raw)
            if v!=i or event.version!=i or event.proposal_ref!=ref:
                raise ApplicationError('RECORD_CORRUPT')
            if i==0 and (event!=ProposalControl(ref) or at!=record.created_at or actor!=record.created_by or reason!='created'):
                raise ApplicationError('RECORD_CORRUPT')
            if i==control.version and event!=control:
                raise ApplicationError('RECORD_CORRUPT')
        return control

    def control_by_digest(self, digest):
        """Exact scoped immutable Proposal identity for a ReadVersion fence."""
        if type(digest) is not str or len(digest) != 64:
            raise ApplicationError('INVALID_ARGUMENT')
        rows = self.access.execute('SELECT change_id,proposal_id,digest FROM eng_proposals '
            'WHERE realm_id=? AND project_id=? AND digest=? LIMIT 2',
            self._prefix() + (digest,)).fetchall()
        if len(rows) != 1:
            raise ApplicationError('NOT_FOUND' if not rows else 'RECORD_CORRUPT')
        change_id, proposal_id, actual = rows[0]
        ref = ProposalRef(self.access.scope.realm_id, self.access.scope.project_id,
                          change_id, proposal_id, Digest('sha256',actual))
        return self.get_control(ref)

    def select(self,ref,*,expected_version):
        self.access.require_write()
        validate_version(expected_version)
        self.get_proposal(ref)
        change=self.get_change(ref.change_id)
        if change.version!=expected_version:
            raise ApplicationError('VERSION_CONFLICT')
        if change.version==MAX_VERSION:
            raise ApplicationError('VERSION_EXHAUSTED')
        cursor=self.access.execute('UPDATE eng_changes SET selected_proposal_id=?,version=version+1 WHERE realm_id=? AND project_id=? AND change_id=? AND version=?',(ref.proposal_id,)+self._prefix()+(ref.change_id,expected_version))
        if cursor.rowcount!=1:
            raise ApplicationError('VERSION_CONFLICT')
        return self.get_change(ref.change_id)

    def control(self,ref,*,expected_version,disposition,replacement_ref,evidence,at,actor,reason):
        self.access.require_write()
        validate_version(expected_version)
        current=self.get_control(ref)
        if current.version!=expected_version:
            raise ApplicationError('PROPOSAL_CONTROL_CHANGED')
        if current.disposition!='available':
            raise ApplicationError('PROPOSAL_UNAVAILABLE')
        if replacement_ref is not None:
            self.get_proposal(replacement_ref)
        updated=ProposalControl(ref,disposition,replacement_ref,evidence,current.version+1)
        event=_event(updated,at,actor,reason)
        cursor=self.access.execute('UPDATE eng_proposal_controls SET version=?,canonical_bytes=? WHERE realm_id=? AND project_id=? AND proposal_id=? AND version=?',(updated.version,encode_control(updated))+self._prefix()+(ref.proposal_id,expected_version))
        if cursor.rowcount!=1:
            raise ApplicationError('PROPOSAL_CONTROL_CHANGED')
        self.access.execute('INSERT INTO eng_proposal_control_events VALUES (?,?,?,?,?)',self._prefix()+(ref.proposal_id,updated.version,event))
        return self.get_control(ref)

    def validate_change_set(self,refs):
        if type(refs) is not tuple or not refs or len(refs)>4096:
            raise ApplicationError('INVALID_ARGUMENT')
        budget=MaterialBudget(self.access)
        result=validate_change_set(tuple(self.get_proposal(ref,budget=budget) for ref in refs),
            tuple(self.get_control(ref,budget=budget) for ref in refs))
        if result.error is not None:
            # Preserve this repository port's existing exception boundary.
            raise ReferenceError(result.error.code.value)
        return result.value
