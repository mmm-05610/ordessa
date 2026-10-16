"""Method-owned fixed review delivery on the original plan/request repositories.

Execution supplies an original Unit invocation and its authorized query. This
reader supplies actual immutable method/material facts, not another runtime or
reviewer authority. It never launches a model, scans code, or mints a query.
"""
from dataclasses import asdict
import hashlib

from ordessa_infrastructure.encoding import canonical_bytes

from ....application.contracts.errors import ApplicationError
from ....application.contracts.snapshots import EngineeringTargetBindings, ResolvedReviewMaterial
from ....application.contracts.unit_review import UnitReviewBinding, NativeReviewInvocation
from ....application.orchestration.decision_checks import GenericDecisionCheckSource
from ....application.orchestration.unit_review_answers import decode_unit_review_result
from ....domain.common.models.values import Digest
from ....domain.reviews.models import ReviewRequestState
from ....domain.reviews.models import ReviewRecord
from ....methods.definitions.models.compiled import thaw_value


def _fixed_material_inputs(materials):
    """Project only exact typed owner material resolutions into delivery JSON."""
    if (type(materials) is not tuple
            or any(type(material) is not ResolvedReviewMaterial for material in materials)
            or len({material.name for material in materials}) != len(materials)):
        raise ApplicationError('DECISION_INPUT_BINDING_UNAVAILABLE')
    return {
        material.name: {'ref': asdict(material.ref), 'value': material.value}
        for material in materials
    }



class SQLiteUnitReviewBindings:
    def __init__(self, factory, method_control, records, *, review_bindings,
                 invocation_resolver, author_unit_resolver=None, authorship_source=None):
        if (getattr(method_control,'factory',None) is not factory
                or getattr(review_bindings,'factory',None) is not factory
                or not callable(getattr(review_bindings,'resolve_plan_bindings',None))
                or not callable(getattr(review_bindings,'material_inputs_for_plan',None))
                or not callable(getattr(records,'acp_prompt_input_digest',None))
                or not callable(invocation_resolver)
                or (author_unit_resolver is not None and not callable(author_unit_resolver))):
            raise ApplicationError('UNIT_REVIEW_SOURCE_UNAVAILABLE')
        self.factory,self.methods,self.records=factory,method_control,records
        self.bindings=review_bindings
        self.invocations,self.authors=invocation_resolver,author_unit_resolver
        if authorship_source is not None and (
                getattr(authorship_source,'factory',None) is not factory
                or getattr(authorship_source,'methods',None) is not method_control
                or not callable(getattr(authorship_source,'resolve_authorship',None))):
            raise ApplicationError('REVIEW_AUTHOR_SOURCE_UNAVAILABLE')
        self.authorship_source=authorship_source

    def _request(self, context, plan, request):
        if context.scope != plan.scope or request.scope != plan.scope or request.review_id != plan.review_id:
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        with self.factory.begin(context.scope,'read') as uow:
            current_plan = uow.reviews.get_plan(plan.review_id)
            current = uow.reviews.get_request(plan.review_id)
        if current_plan != plan or current.fence != request.fence:
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        if not ((current.state == 'requested' and current.version == request.version)
                or (current.state == 'recorded' and current.version == request.version + 1)):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')

    def fixed_delivery(self, context, plan, request, *, standard):
        """Return the exact normal-prompt block required of the selected Unit."""
        self._request(context,plan,request)
        if request.state != 'requested':
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        current_guard=getattr(self.bindings,'guard_current_request',None)
        if callable(current_guard):
            current_guard(context,plan,request)
        with self.methods.guard_method(context,plan.requirement.method_ref) as snapshot:
            standards = tuple(s for s in snapshot.program.standard_definitions
                if s.standard_id == plan.requirement.criterion_set_ref.criterion_set_id
                and s.resource_ref.sha256 == plan.requirement.criterion_set_ref.digest.hex)
            if len(standards) != 1 or standard != standards[0]:
                raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
            nodes = tuple(n for n in snapshot.program.workflow.steps if n.id == plan.requirement.phase_key)
            if len(nodes) != 1 or getattr(nodes[0],'operation',None) != 'engineering.reviews.request':
                raise ApplicationError('METHOD_PHASE_BINDING_MISMATCH')
            config = thaw_value(nodes[0].config)
            declared = config.get('review_source')
            if (type(declared) is not dict or declared.get('response_codec') != 'exact_check_key_status/1'
                    or type(declared.get('response_document_type')) is not str):
                raise ApplicationError('UNIT_REVIEW_SCHEMA_UNAVAILABLE')
            documents = tuple(d for d in snapshot.program.document_definitions
                if d.document_type == declared['response_document_type'])
            if len(documents) != 1:
                raise ApplicationError('UNIT_REVIEW_SCHEMA_UNAVAILABLE')
            document = documents[0]
            authored = declared.get('response_schema')
            if authored not in ({'resource':document.schema_resource.resource_id}, asdict(document.schema_resource)):
                raise ApplicationError('UNIT_REVIEW_SCHEMA_MISMATCH')
            resource = next(r for r in snapshot.resources if r.resource_id == document.schema_resource.resource_id)
            schema = self.methods.snapshots.read_blob(resource.blob_ref)
            if hashlib.sha256(schema).hexdigest() != document.schema_resource.sha256:
                raise ApplicationError('UNIT_REVIEW_SCHEMA_MISMATCH')
            selected = self.bindings.resolve_plan_bindings(context,plan)
            if type(selected) is not EngineeringTargetBindings:
                raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
            with self.factory.begin(context.scope,'read') as uow:
                deliveries = tuple(uow.engineering.resolve_revision(t.ref) for t in selected.targets.targets)
            named = self.bindings.material_inputs_for_plan(context,plan)
            inputs = _fixed_material_inputs(named)
            keys = tuple(k for k in plan.check_keys if any(c.criterion_id == k.criterion_id
                and any(ch.capability_id == 'ordessa.decision.evaluate' for ch in c.checks) for c in standard.criteria))
            questions = GenericDecisionCheckSource._questions(snapshot,plan,standard,keys) if keys else ()
            slots = GenericDecisionCheckSource._input_slots(snapshot,questions)
            if not set(slots) <= set(inputs):
                raise ApplicationError('DECISION_INPUT_BINDING_UNAVAILABLE')
            strategy = config.get('unit_submission_review_strategy',{})
            constraint = strategy.get('roles',{}).get('identity_constraint')
            from ....application.contracts.review_authorship import (
                SOURCE_BOUND_POLICY, validate_authorship_policy, resolve_plan_authorship)
            validate_authorship_policy(constraint)
            origin = (resolve_plan_authorship(self.authorship_source,context,plan,
                tuple(r.ref for r in deliveries)) if constraint==SOURCE_BOUND_POLICY else None)
            author = (origin.author_unit_ref if origin is not None else
                self.authors(context,plan) if self.authors is not None else None)
            if (constraint is not None and (type(author) is not dict or set(author) !=
                    {'environmentNamespace','unitId','ownerProviderRef','sourceRevision'})
                    and not (origin is not None and origin.source_kind=='authenticated_material_submitter'
                             and author is None)):
                raise ApplicationError('UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE')
            constraints = {'identity_constraint':constraint,'authorUnitRef':author}
            if origin is not None:
                constraints['authorship']=asdict(origin)
            block = {'ordessa.method-unit-review':{
                'plan':asdict(plan),'request_version':request.version,'fence':request.fence,
                'delivery_refs':[asdict(r.ref) for r in deliveries],
                'delivery':[r.projection() for r in deliveries],
                'response_document_type':document.document_type,
                'response_schema_ref':asdict(document.schema_resource),
                'response_schema_digest':{'algorithm':'sha256','hex':resource.digest},
                'response_schema':schema.decode('utf-8'),
                'question_refs':[asdict(r) for r in questions],
                'question_resources':[{'ref':asdict(ref),'source':self.methods.snapshots.read_blob(
                    next(r.blob_ref for r in snapshot.resources if r.resource_id == ref.resource_id)).decode('utf-8')}
                    for ref in questions],
                'input_slots':list(slots),'inputs':inputs,
                'identity_constraints':constraints}}
            return block,document,schema,tuple(r.ref for r in deliveries),questions,slots,constraints

    def resolve_unit_review(self, context, plan, request, *, standard):
        block,document,schema,deliveries,questions,slots,constraints = self.fixed_delivery(
            context,plan,request,standard=standard)
        text = canonical_bytes(block).decode('utf-8')
        if len(text.encode('utf-8')) > 262144:
            raise ApplicationError('UNIT_REVIEW_PROMPT_BOUND_EXCEEDED')
        invocation = self.invocations(context,plan,request,prompt_binding=text)
        if (type(invocation) is not NativeReviewInvocation or type(invocation.params) is not dict
                or type(invocation.params.get('prompt')) is not list
                or sum(item == {'type':'text','text':text} for item in invocation.params['prompt']) != 1):
            raise ApplicationError('UNIT_REVIEW_PROMPT_BINDING_MISMATCH')
        constraints = {**constraints,'reviewerUnitRef':invocation.unit_ref}
        # These refs remain captured facts. The injected current Unit reviewer
        # authority authenticates both original identities/constraints to COMMIT.
        digest = self.records.acp_prompt_input_digest(invocation.unit_ref,invocation.params)
        return UnitReviewBinding(plan.plan_digest,request.version,request.fence,
            invocation.unit_ref,invocation.operation_ref,digest,invocation.query_invocation,
            deliveries,document.schema_resource,document.document_type,schema,
            Digest('sha256',hashlib.sha256(schema).hexdigest()),constraints,plan.check_keys,questions,slots)

    def decode_response(self, binding, response_value, *, plan, standard):
        if (binding.plan_digest != plan.plan_digest or type(response_value) is not dict
                or response_value.get('document_type') != binding.response_document_type):
            raise ApplicationError('UNIT_REVIEW_RESPONSE_INVALID')
        snapshot = self.methods.read_snapshot(plan.requirement.method_ref)
        return decode_unit_review_result(plan,standard,canonical_bytes(response_value).decode('utf-8'),
                snapshot=snapshot,document_type=binding.response_document_type)

    def resolve_record_request(self, context, plan, record):
        if (context.scope != plan.scope or type(record) is not ReviewRecord
                or record.plan != plan or record.identity.record_id != plan.review_id):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        with self.factory.begin(context.scope,'read') as uow:
            current_plan = uow.reviews.get_plan(plan.review_id)
            current = uow.reviews.get_request(plan.review_id)
            if current_plan != plan or current.fence <= 0:
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            if current.state == 'requested':
                # record_response validates and asks the trust source about this
                # exact in-memory ReviewRecord before insert_review. In that
                # path there must not yet be a durable review row.
                try:
                    uow.reviews.get_review(record.ref)
                except ApplicationError as exc:
                    if exc.code != 'NOT_FOUND':
                        raise
                    return ReviewRequestState(plan.scope, plan.review_id,
                        'requested', current.fence, current.version)
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            if current.state != 'recorded' or current.version < 1:
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            persisted = uow.reviews.get_review(record.ref).record
        if persisted != record:
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        # insert_review records once and increments version without changing
        # fence. Withdrawal cannot later become recorded; no latest-request guess.
        return ReviewRequestState(plan.scope,plan.review_id,'recorded',current.fence,current.version-1)


__all__ = ['NativeReviewInvocation','SQLiteUnitReviewBindings']
