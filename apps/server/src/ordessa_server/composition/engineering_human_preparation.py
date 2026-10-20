"""Fresh method-bound materials and exact human checklist on original owners.

Publication and project adoption are explicit upstream actions. This code does
not invent a capability catalog, publish a fixture, adopt a method or issue a
Grant. Configured exact subjects are trusted root business inputs, not wire.
"""
from dataclasses import asdict
from urllib.parse import urljoin

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.contracts.mixed_reviews import FrozenCheckRequest
from ordessa_engineering.application.orchestration.method_content import document_type_for_payload, document_spec
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
from ordessa_engineering.domain.artifacts.models import MethodContent, MethodPayload
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.targets import TargetSet
from ordessa_engineering.methods.definitions.models.compiled import thaw_value
from .engineering_human_source import QUESTION, human_review_checklist, captured_source_inputs


def create_fresh_human_material(factory, access, methods, context, *, method_ref,
                                document_type, value, sources, claims, evidence_links):
    """Selected exact method/schema -> original Artifact command and journal."""
    with methods.guard_selected(context) as snapshot:
        ref = snapshot.ref
        actual = MethodRef(ref.method_id,ref.release_version,ref.schema_version,Digest('sha256',ref.snapshot_digest))
        if actual != method_ref:
            raise ApplicationError('METHOD_SELECTION_CHANGED')
        spec = document_spec(snapshot,document_type)
        resource = next(r for r in snapshot.resources if r.resource_id == spec.schema_ref.resource_id)
        exact = ExactMethodResourceRef(actual,resource.logical_path,Digest('sha256',resource.digest),resource.resource_id)
        schema = thaw_value(spec.value_schema)
        schema_id = urljoin('https://ordessa.invalid/method/'+resource.logical_path,
                            schema.get('$id','https://ordessa.invalid/method/'+resource.logical_path))
        payload = MethodPayload('application/json',schema_id,MethodContent.from_value(exact,value))
        if document_type_for_payload(snapshot,payload) != document_type:
            raise ApplicationError('METHOD_RESOURCE_MISMATCH')
        return ArtifactUseCases(factory,access).create({'kind':'design','initial':payload.projection(),
            'sources':[asdict(s) for s in sources], 'claims':[asdict(c) for c in claims],
            'evidence_links':[asdict(e) for e in evidence_links], 'method_refs':[asdict(actual)],
            'generation_origin':None},context)


class ConfiguredHumanReviewBindings:
    """Exact configured business subjects; labels resolved from real snapshots."""
    def __init__(self,factory,methods,*,scope,method_ref,targets,input_slots,phase_key):
        self.factory,self.methods,self.scope = factory,methods,scope
        self.method,self.targets,self.slots,self.phase = method_ref,TargetSet(targets),input_slots,phase_key

    def resolve_bindings(self,context,method_ref,phase_key):
        if context.scope != self.scope or method_ref != self.method or phase_key != self.phase:
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        with self.methods.guard_method(context,method_ref) as snapshot:
            with self.factory.begin(context.scope,'read') as uow:
                revisions=tuple(uow.engineering.resolve_revision(t.ref) for t in self.targets.targets)
            labels=tuple((t,document_type_for_payload(snapshot,r.payload)) for t,r in zip(self.targets.targets,revisions))
            return EngineeringTargetBindings(context.scope,self.targets,labels,self.slots,
                ('reviewer',),phase_key,workflow_node_id=phase_key)

    def resolve_review_proposal(self,context,method_ref,phase_key):
        self.resolve_bindings(context,method_ref,phase_key)
        return None


def prepare_human_plan(factory, methods, bindings, reviews, context, *, review_id, method_ref, phase_key):
    """Original full Bridge/review request; no caller templates or CheckKeys."""
    with methods.guard_selected(context) as snapshot:
        actual=snapshot.ref
        if (actual.method_id,actual.release_version,actual.schema_version,actual.snapshot_digest) != (
                method_ref.method_id,method_ref.release_version,method_ref.schema_version,method_ref.snapshot_digest.hex):
            raise ApplicationError('METHOD_SELECTION_CHANGED')
        bound=bindings.resolve_bindings(context,method_ref,phase_key)
        with factory.begin(context.scope,'read') as uow:
            revisions=tuple(uow.engineering.resolve_revision(t.ref) for t in bound.targets.targets)
        bridge=MethodBridge()
        requirements=bridge.review_requirements(snapshot,bound,revisions=revisions)
        if len(requirements) != 1:
            raise ApplicationError('HUMAN_REVIEW_FULL_PLAN_UNAVAILABLE')
        plan=bridge.review_plan(snapshot,bound,requirements[0],review_id,revisions=revisions)
        return reviews.request({'plan':asdict(plan)},context)


def prepare_human_presentation(factory, admission, context, *, review_id):
    """Explicit preparation records mechanical proof only in original BlobStore."""
    with factory.begin(context.scope,'read') as uow:
        plan=uow.reviews.get_plan(review_id);request=uow.reviews.get_request(review_id)
        revisions=tuple(uow.engineering.resolve_revision(t.ref) for t in plan.requirement.expected_targets.targets)
    frozen=FrozenCheckRequest(plan.plan_digest,request.version,request.fence)
    with admission.guard_plan(context,plan), admission.methods.guard_method(context,plan.requirement.method_ref) as snapshot:
        matches=tuple(s for s in snapshot.program.standard_definitions
            if s.standard_id==plan.requirement.criterion_set_ref.criterion_set_id
            and s.resource_ref.sha256==plan.requirement.criterion_set_ref.digest.hex)
        if len(matches)!=1:raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
        standard=matches[0]
        caps={c.criterion_id:c.checks[0].capability_id for c in standard.criteria}
        keys=tuple(k for k in plan.check_keys if caps[k.criterion_id] in ('ordessa.sources.integrity','ordessa.claims.coverage'))
        proof=admission.mechanical.capture_proof(context,plan,frozen,standard=standard,check_keys=keys)
        answers=admission.mechanical.verify_checks(context,plan,frozen,proof,standard=standard,check_keys=keys).answers
        return {'question':QUESTION,'checklist':human_review_checklist(plan,frozen,standard,revisions,answers,
                    captured_source_inputs(factory,context,revisions)),
                'mechanical_proof_ref':asdict(proof),'frozen_request':asdict(frozen),'state':request.state,
                'review_is_implementation_grant':False}


class OriginalHumanReviewPresentation:
    """Read prepared proof by exact reference, project original pending state.

    Proof lookup is trusted root evidence wiring, not another pending store;
    returned bytes are independently verified against full original Plan.
    """
    def __init__(self,factory,admission,proof_lookup):
        self.factory,self.admission,self.proof_lookup=factory,admission,proof_lookup

    def project(self,context,plan,request):
        prepared=self.proof_lookup(plan.review_id)
        if prepared is None:
            return {'available':False,'reason':'MECHANICAL_PRESENTATION_PENDING',
                    'review_is_implementation_grant':False}
        if type(prepared) is not tuple or len(prepared)!=2:
            raise ApplicationError('HUMAN_REVIEW_PRESENTATION_CHANGED')
        proof,frozen=prepared
        if type(frozen) is not FrozenCheckRequest or frozen.plan_digest!=plan.plan_digest:
            raise ApplicationError('HUMAN_REVIEW_PRESENTATION_CHANGED')
        if request.state=='requested' and (request.version,request.fence)!=(frozen.request_version,frozen.fence):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        with self.admission.guard_plan(context,plan), self.admission.methods.guard_method(context,plan.requirement.method_ref) as snapshot:
            matches=tuple(s for s in snapshot.program.standard_definitions
                if s.standard_id==plan.requirement.criterion_set_ref.criterion_set_id
                and s.resource_ref.sha256==plan.requirement.criterion_set_ref.digest.hex)
            if len(matches)!=1:raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
            standard=matches[0]
            caps={c.criterion_id:c.checks[0].capability_id for c in standard.criteria}
            keys=tuple(k for k in plan.check_keys if caps[k.criterion_id] in ('ordessa.sources.integrity','ordessa.claims.coverage'))
            answers=self.admission.mechanical.verify_checks(context,plan,frozen,proof,standard=standard,check_keys=keys).answers
            with self.factory.begin(context.scope,'read') as uow:
                revisions=tuple(uow.engineering.resolve_revision(t.ref) for t in plan.requirement.expected_targets.targets)
            return {'available':True,'question':QUESTION,
                'checklist':human_review_checklist(plan,frozen,standard,revisions,answers,
                    captured_source_inputs(self.factory,context,revisions)),
                'mechanical_proof_ref':asdict(proof),'review_is_implementation_grant':False}
