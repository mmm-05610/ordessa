"""Actual Proposal commands on the original journal/UoW; no apply or grant."""
from ordessa_engineering.application.contracts.commands import read_set_projection
from dataclasses import asdict
from uuid import uuid4
import hashlib
from contextlib import nullcontext, ExitStack
from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes
from ....domain.changes.models import Change, Proposal, SourceChange
from ....domain.changes.codec import decode_draft
from ordessa_engineering.domain.changes.ref_codec import (decode_proposal_ref)
from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_engineering.domain.reviews.targets import SourceTargetRef
from ....domain.reviews.models import CurrentReviewTrust
from ....domain.common.models.values import (Digest)
from ....domain.common.outcomes.diagnostics import (ReferenceError)
from ....domain.common.mechanisms.codec import (canonical_value)
from ....domain.common.models.values import (MAX_VERSION, validate_text)
from ordessa_engineering.application.contracts.commands import CommandContext, CommandResult, ReadSet, request_digest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ..proposal_closure import validate_create
from ..artifacts import BUSINESS_REFUSALS
from ..material_closure import guard_method_resources, verify_source_change

_REFUSALS=BUSINESS_REFUSALS|frozenset({'PROPOSAL_UNAVAILABLE','PROPOSAL_CONTROL_CHANGED',
    'PROPOSAL_IDENTITY_CONFLICT','PROPOSAL_LIMIT','IMPLEMENTATION_BASELINE_AUTHORITY_UNAVAILABLE',
    'UNSUPPORTED_REFERENCE_KIND','UNSUPPORTED_CLAIM','SOURCE_VERSION_UNAVAILABLE',
    'SOURCE_CONTENT_MISMATCH','SOURCE_CHANGE_INVALID','METHOD_AUTHORITY_UNAVAILABLE',
    'METHOD_PIN_MISMATCH','METHOD_RESOURCE_MISMATCH','METHOD_REQUIREMENTS_CHANGED',
    'REVIEW_SOURCE_AUTHORITY_UNAVAILABLE','REVIEW_TRUST_UNAVAILABLE','UNTRUSTED_REVIEWER',
    'REVIEW_STALE','REVIEW_INCOMPLETE','REVIEW_CONFLICT','REVIEW_REQUEST_CHANGED',
    'PROPOSAL_REVIEW_ASSOCIATION_INVALID','IMPLEMENTATION_ENVELOPE_UNAVAILABLE'})
_ID={'type':'string','minLength':1,'maxLength':512}
_REF={'type':'object'}  # Complete closed typed ref codec validates before reserving.
_VERSION={'type':'integer','minimum':0,'maximum':MAX_VERSION}


def _schema(operation,properties,required,version=1):
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',
        '$id':f'urn:ordessa:engineering:operations:{operation}:input:{version}','type':'object',
        'properties':properties,'required':required,'additionalProperties':False}


_SCHEMAS={
    'engineering.proposals.create':_schema('engineering.proposals.create',
        {'change_id':{'anyOf':[_ID,{'type':'null'}]},'expected_version':_VERSION,'draft':{'type':'object'}},
        ['change_id','expected_version','draft'],version=2),
    'engineering.proposals.select':_schema('engineering.proposals.select',
        {'proposal_ref':_REF,'expected_version':_VERSION},['proposal_ref','expected_version']),
    'engineering.proposals.withdraw':_schema('engineering.proposals.withdraw',
        {'proposal_ref':_REF,'expected_version':_VERSION,'reason':{'type':'string','minLength':1,'maxLength':16384}},
        ['proposal_ref','expected_version','reason']),
    'engineering.proposals.supersede':_schema('engineering.proposals.supersede',
        {'proposal_ref':_REF,'expected_version':_VERSION,'replacement_ref':_REF,
         'reason':{'type':'string','minLength':1,'maxLength':16384}},
        ['proposal_ref','expected_version','replacement_ref','reason']),
    'engineering.proposals.associate_review':_schema('engineering.proposals.associate_review',
        {'proposal_ref':_REF,'expected_version':_VERSION,'review_ref':_REF},
        ['proposal_ref','expected_version','review_ref'])}
_SCHEMA_BYTES={operation:canonical_bytes(value) for operation,value in _SCHEMAS.items()}
del _SCHEMAS


def input_schema(operation):
    try:
        return canonical_value(_SCHEMA_BYTES[operation])
    except KeyError:
        raise ApplicationError('OPERATION_UNAVAILABLE') from None


class ProposalUseCases:
    def __init__(self,factory,access,control_admission=None,*,source_materials=None,
                 method_guard=None,review_admission=None):
        self.factory=factory
        self.access=access
        self.control_admission=control_admission
        self.source_materials=source_materials
        self.method_guard=method_guard
        self.review_admission=review_admission
        for port in (source_materials,method_guard):
            if port is not None and getattr(port,'factory',None) is not factory:
                raise ApplicationError('SOURCE_MATERIAL_AUTHORITY_MISMATCH')
        if review_admission is not None and getattr(review_admission,'factory',None) is not factory:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')

    def _authorize(self,context,operation):
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        if self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context,operation)

    def create(self,parameters,context,*,read_set=None):
        return self._command('engineering.proposals.create',parameters,context,read_set)

    def select(self,parameters,context,*,read_set=None):
        return self._command('engineering.proposals.select',parameters,context,read_set)

    def withdraw(self,parameters,context,*,read_set=None):
        return self._command('engineering.proposals.withdraw',parameters,context,read_set)

    def supersede(self,parameters,context,*,read_set=None):
        return self._command('engineering.proposals.supersede',parameters,context,read_set)

    def associate_review(self,parameters,context,*,read_set=None):
        return self._command('engineering.proposals.associate_review',parameters,context,read_set)

    def _command(self,operation,parameters,context,read_set):
        self._authorize(context,operation)
        try:
            value=canonical_value(canonical_bytes(parameters))
            schema=input_schema(operation)
            if not Draft202012Validator(schema).is_valid(value):
                raise ReferenceError('INVALID_SCHEMA')
            if operation=='engineering.proposals.create':
                if value['change_id'] is None and value['expected_version']!=0:
                    raise ReferenceError('INVALID_VERSION')
                if 'source_change' not in value['draft']:
                    raise ReferenceError('INVALID_PROPOSAL')
                decode_draft(context.scope,'draft',context.received_at,context.authenticated_actor,
                    value['change_id'] or 'new-change',value['draft'],schema_version=2)
            else:
                decode_proposal_ref(value['proposal_ref'])
                if operation=='engineering.proposals.associate_review':
                    decode_review_ref(value['review_ref'])
                if 'replacement_ref' in value:
                    decode_proposal_ref(value['replacement_ref'])
                if 'reason' in value:
                    validate_text(value['reason'])
            reads=ReadSet(context.scope,()) if read_set is None else read_set
            if type(reads) is not ReadSet or reads.scope!=context.scope:
                raise ReferenceError('INVALID_SCHEMA')
            digest=request_digest(operation,context,value,read_set_projection(reads),input_schema_id=schema['$id'],
                input_schema_digest=Digest('sha256',hashlib.sha256(_SCHEMA_BYTES[operation]).hexdigest()),
                interface_version='2' if operation=='engineering.proposals.create' else '1')
        except (ReferenceError,ValueError,TypeError,KeyError,RecursionError,OverflowError):
            raise ApplicationError('INVALID_INPUT') from None
        # Query the same durable key before any control callback, never dispatch
        # a pending retry. Access is rechecked above on every call.
        with self.factory.begin(context.scope,'read') as uow:
            repository=uow.proposals
            previous=uow.commands.get(context.key)
            if previous is not None:
                if previous.request_digest!=digest or previous.project_id!=context.scope.project_id:
                    raise ApplicationError('REQUEST_IDENTITY_CONFLICT')
                return CommandResult(uow.authority_id,previous.operation_id,previous.state,previous.result_bytes)
            if operation in {'engineering.proposals.withdraw','engineering.proposals.supersede'}:
                if self.control_admission is None:
                    raise ApplicationError('PROPOSAL_CONTROL_AUTHORITY_UNAVAILABLE')
                proposal=repository.get_proposal(decode_proposal_ref(value['proposal_ref']))
                control=repository.get_control(proposal.ref)
                replacement=repository.get_proposal(decode_proposal_ref(value['replacement_ref'])) if 'replacement_ref' in value else None
            else:
                proposal=control=replacement=None
        if operation=='engineering.proposals.associate_review':
            return self._associate_review_command(value,context,reads,digest)
        disposition='superseded' if operation=='engineering.proposals.supersede' else 'withdrawn'
        guard=nullcontext(()) if proposal is None else self.control_admission.guard_control(context,proposal,control,disposition,replacement)
        with ExitStack() as guards:
            evidence=guards.enter_context(guard)
            if operation=='engineering.proposals.create' and 'source_change' in value['draft']:
                source_proposal=decode_draft(context.scope,'draft',context.received_at,context.authenticated_actor,
                    value['change_id'] or 'new-change',value['draft'],schema_version=2)
                if self.source_materials is None:
                    raise ApplicationError('SOURCE_VERSION_UNAVAILABLE')
                if self.method_guard is None:
                    raise ApplicationError('METHOD_AUTHORITY_UNAVAILABLE')
                guards.enter_context(guard_method_resources(context,source_proposal.method_ref,
                    source_proposal.source_change.method_resource_refs,self.method_guard))
                verify_source_change(context,source_proposal.source_change,self.source_materials)
            if proposal is not None and (type(evidence) is not tuple or not evidence or any(type(e) is not Digest for e in evidence)):
                raise ApplicationError('PROPOSAL_CONTROL_AUTHORITY_INVALID')
            with self.factory.begin(context.scope) as uow:
                repository=uow.proposals
                reservation=uow.commands.reserve(context.key,project_id=context.scope.project_id,operation=operation,
                    operation_id=str(uuid4()),request_digest=digest)
                entry=reservation.entry
                if not reservation.created:
                    return CommandResult(uow.authority_id,entry.operation_id,entry.state,entry.result_bytes)
                state='completed'
                try:
                    with uow.isolate():
                        uow.engineering.check_read_set(reads)
                        result=self._mutate(repository,operation,value,context,evidence)
                except ReferenceError:
                    state,result='rejected',{'code':'INVALID_INPUT'}
                except ApplicationError as exc:
                    if exc.code not in _REFUSALS:
                        raise
                    state,result='rejected',{'code':exc.code}
                final=uow.commands.complete(context.key,expected_version=entry.version,result_bytes=canonical_bytes(result),state=state)
                answer=CommandResult(uow.authority_id,final.operation_id,final.state,final.result_bytes)
                uow.commit()
                return answer

    @staticmethod
    def _mutate(repository,operation,value,context,evidence):
        if operation=='engineering.proposals.create':
            change_id=value['change_id']
            if change_id is None:
                change_id=str(uuid4())
                repository.create_change(Change(context.scope,change_id,context.received_at))
            proposal=decode_draft(context.scope,str(uuid4()),context.received_at,context.authenticated_actor,
                change_id,value['draft'],schema_version=2)
            budget=repository.validated_budget()
            requirements=validate_create(proposal,repository,budget)
            ref=repository.create_proposal(proposal,expected_version=value['expected_version'],budget=budget,requirements=requirements)
            return {'proposal_ref':asdict(ref),'change':asdict(repository.get_change(change_id))}
        ref=decode_proposal_ref(value['proposal_ref'])
        if operation=='engineering.proposals.select':
            return {'change':asdict(repository.select(ref,expected_version=value['expected_version']))}
        control=repository.control(ref,expected_version=value['expected_version'],
            disposition='superseded' if operation=='engineering.proposals.supersede' else 'withdrawn',
            replacement_ref=decode_proposal_ref(value['replacement_ref']) if 'replacement_ref' in value else None,
            evidence=evidence,at=context.received_at,actor=context.authenticated_actor,reason=value['reason'])
        return {'control':asdict(control)}

    def _associate_review_command(self,value,context,reads,digest):
        if reads != ReadSet(context.scope,()):
            raise ApplicationError('PROPOSAL_READ_SET_UNSUPPORTED')
        proposal_ref=decode_proposal_ref(value['proposal_ref'])
        review_ref=decode_review_ref(value['review_ref'])
        if (type(review_ref) is not ReviewRef or
                (review_ref.realm_id,review_ref.project_id)!=(context.scope.realm_id,context.scope.project_id)):
            raise ApplicationError('SCOPE_MISMATCH')
        if self.review_admission is None:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        with self.factory.begin(context.scope,'read') as uow:
            proposal=uow.proposals.get_proposal(proposal_ref)
            if proposal.schema_version!=2 or type(proposal.source_change) is not SourceChange:
                raise ApplicationError('PROPOSAL_REVIEW_ASSOCIATION_INVALID')
            if uow.proposals.get_control(proposal_ref).disposition!='available':
                raise ApplicationError('PROPOSAL_REVIEW_ASSOCIATION_INVALID')
            current=uow.proposals.get_change(proposal.change_id)
            if (proposal_ref.proposal_id not in current.proposal_ids or
                    proposal_ref.change_id!=current.change_id):
                raise ApplicationError('PROPOSAL_REVIEW_ASSOCIATION_INVALID')
            controlled=uow.reviews.get_review(review_ref)
        record=controlled.record
        source_targets=tuple(t.ref for t in record.plan.requirement.expected_targets.targets
                             if type(t.ref) is SourceTargetRef)
        expected_sources=(proposal.source_change.baseline,proposal.source_change.candidate)
        if (controlled.control.state!='active' or record.ref!=review_ref or not record.complete
                or record.verdict!='pass' or record.plan.requirement.schema_version!=2
                or record.plan.requirement.method_ref!=proposal.method_ref
                or record.plan.requirement.method_resource_refs!=proposal.source_change.method_resource_refs
                or len(source_targets)!=len(record.plan.requirement.expected_targets.targets)
                or {target.source_ref.content_identity for target in source_targets}
                   != {source.content_identity for source in expected_sources}):
            raise ApplicationError('PROPOSAL_REVIEW_ASSOCIATION_INVALID')
        admission=self.review_admission
        with admission.guard_plan(context,record.plan), admission.guard_trust(context,(record,)) as trusted:
            if (type(trusted) is not tuple or len(trusted)!=1
                    or type(trusted[0]) is not CurrentReviewTrust
                    or trusted[0].review_ref!=review_ref
                    or trusted[0].verifier_id!=record.reviewer_evidence.verifier_id
                    or trusted[0].trust_version!=record.reviewer_evidence.trust_version):
                raise ApplicationError('UNTRUSTED_REVIEWER')
            with self.factory.begin(context.scope) as uow:
                entry=uow.commands.reserve(context.key,project_id=context.scope.project_id,
                    operation='engineering.proposals.associate_review',operation_id=str(uuid4()),request_digest=digest)
                if not entry.created:
                    return CommandResult(uow.authority_id,entry.entry.operation_id,
                        entry.entry.state,entry.entry.result_bytes)
                try:
                    with uow.isolate():
                        uow.engineering.check_read_set(reads)
                        parent=uow.proposals.get_proposal(proposal_ref)
                        latest=uow.proposals.get_change(parent.change_id)
                        parent_control=uow.proposals.get_control(proposal_ref)
                        actual=uow.reviews.get_review(review_ref)
                        if (latest.version!=value['expected_version'] or parent!=proposal
                                or parent_control.disposition!='available'
                                or actual.record!=record or actual.control.state!='active'):
                            raise ApplicationError('PROPOSAL_REVIEW_ASSOCIATION_INVALID')
                        source=parent.source_change
                        if review_ref in source.review_refs:
                            raise ApplicationError('PROPOSAL_REVIEW_ASSOCIATION_INVALID')
                        successor=Proposal(parent.scope,str(uuid4()),context.received_at,
                            context.authenticated_actor,parent.change_id,parent.intent,parent.rationale,
                            parent.mutations,parent.basis_sources,parent.claim_refs,parent.evidence_links,
                            parent.method_ref,parent.review_requirement_templates,parent.implementation_intent,
                            (parent.ref,),2,SourceChange(source.baseline,source.candidate,
                                source.method_resource_refs,source.review_refs+(review_ref,)))
                        budget=uow.proposals.validated_budget()
                        # Schema-2 closure validates canonical pin identity without requiring a
                        # second provider read after the external admission guards above.
                        from ..proposal_closure import validate_create
                        requirements=validate_create(successor,uow.proposals,budget)
                        new_ref=uow.proposals.create_proposal(successor,
                            expected_version=value['expected_version'],budget=budget,requirements=requirements)
                        result={'proposal_ref':asdict(new_ref),'change':asdict(uow.proposals.get_change(parent.change_id))}
                except ReferenceError:
                    state,result='rejected',{'code':'INVALID_INPUT'}
                except ApplicationError as exc:
                    if exc.code not in _REFUSALS:
                        raise
                    state,result='rejected',{'code':exc.code}
                else:
                    state='completed'
                final=uow.commands.complete(context.key,expected_version=entry.entry.version,
                    result_bytes=canonical_bytes(result),state=state)
                answer=CommandResult(uow.authority_id,final.operation_id,final.state,final.result_bytes)
                uow.commit()
                return answer

    def get(self,ref,context):
        self._authorize(context,'engineering.proposals.get')
        with self.factory.begin(context.scope,'read') as uow:
            return uow.proposals.get_proposal(ref)

    def get_change(self,change_id,context):
        self._authorize(context,'engineering.changes.get')
        with self.factory.begin(context.scope,'read') as uow:
            return uow.proposals.get_change(change_id)

    def get_control(self,ref,context):
        self._authorize(context,'engineering.proposals.get_control')
        with self.factory.begin(context.scope,'read') as uow:
            return uow.proposals.get_control(ref)
