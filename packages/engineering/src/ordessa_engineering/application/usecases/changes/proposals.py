"""Actual Proposal commands on the original journal/UoW; no apply or grant."""
from ordessa_engineering.application.contracts.commands import read_set_projection
from dataclasses import asdict
from uuid import uuid4
import hashlib
from contextlib import nullcontext
from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes
from ....domain.changes.models import Change, Proposal
from ....domain.changes.codec import decode_draft
from ordessa_engineering.domain.changes.ref_codec import (decode_proposal_ref)
from ....domain.common.models.values import (Digest)
from ....domain.common.outcomes.diagnostics import (ReferenceError)
from ....domain.common.mechanisms.codec import (canonical_value)
from ....domain.common.models.values import (MAX_VERSION, validate_text)
from ordessa_engineering.application.contracts.commands import CommandContext, CommandResult, ReadSet, request_digest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ..proposal_closure import validate_create
from ..artifacts import BUSINESS_REFUSALS

_REFUSALS=BUSINESS_REFUSALS|frozenset({'PROPOSAL_UNAVAILABLE','PROPOSAL_CONTROL_CHANGED',
    'PROPOSAL_IDENTITY_CONFLICT','PROPOSAL_LIMIT','IMPLEMENTATION_BASELINE_AUTHORITY_UNAVAILABLE',
    'UNSUPPORTED_REFERENCE_KIND','UNSUPPORTED_CLAIM'})
_ID={'type':'string','minLength':1,'maxLength':512}
_REF={'type':'object'}  # Complete closed typed ref codec validates before reserving.
_VERSION={'type':'integer','minimum':0,'maximum':MAX_VERSION}


def _schema(operation,properties,required):
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',
        '$id':f'urn:ordessa:engineering:operations:{operation}:input:1','type':'object',
        'properties':properties,'required':required,'additionalProperties':False}


_SCHEMAS={
    'engineering.proposals.create':_schema('engineering.proposals.create',
        {'change_id':{'anyOf':[_ID,{'type':'null'}]},'expected_version':_VERSION,'draft':{'type':'object'}},
        ['change_id','expected_version','draft']),
    'engineering.proposals.select':_schema('engineering.proposals.select',
        {'proposal_ref':_REF,'expected_version':_VERSION},['proposal_ref','expected_version']),
    'engineering.proposals.withdraw':_schema('engineering.proposals.withdraw',
        {'proposal_ref':_REF,'expected_version':_VERSION,'reason':{'type':'string','minLength':1,'maxLength':16384}},
        ['proposal_ref','expected_version','reason']),
    'engineering.proposals.supersede':_schema('engineering.proposals.supersede',
        {'proposal_ref':_REF,'expected_version':_VERSION,'replacement_ref':_REF,
         'reason':{'type':'string','minLength':1,'maxLength':16384}},
        ['proposal_ref','expected_version','replacement_ref','reason'])}
_SCHEMA_BYTES={operation:canonical_bytes(value) for operation,value in _SCHEMAS.items()}
del _SCHEMAS


def input_schema(operation):
    try:
        return canonical_value(_SCHEMA_BYTES[operation])
    except KeyError:
        raise ApplicationError('OPERATION_UNAVAILABLE') from None


class ProposalUseCases:
    def __init__(self,factory,access,control_admission=None):
        self.factory=factory
        self.access=access
        self.control_admission=control_admission

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
                decode_draft(context.scope,'draft',context.received_at,context.authenticated_actor,
                    value['change_id'] or 'new-change',value['draft'])
            else:
                decode_proposal_ref(value['proposal_ref'])
                if 'replacement_ref' in value:
                    decode_proposal_ref(value['replacement_ref'])
                if 'reason' in value:
                    validate_text(value['reason'])
            reads=ReadSet(context.scope,()) if read_set is None else read_set
            if type(reads) is not ReadSet or reads.scope!=context.scope:
                raise ReferenceError('INVALID_SCHEMA')
            digest=request_digest(operation,context,value,read_set_projection(reads),input_schema_id=schema['$id'],
                input_schema_digest=Digest('sha256',hashlib.sha256(_SCHEMA_BYTES[operation]).hexdigest()),interface_version='1')
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
        disposition='superseded' if operation=='engineering.proposals.supersede' else 'withdrawn'
        guard=nullcontext(()) if proposal is None else self.control_admission.guard_control(context,proposal,control,disposition,replacement)
        with guard as evidence:
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
            proposal=decode_draft(context.scope,str(uuid4()),context.received_at,context.authenticated_actor,change_id,value['draft'])
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
