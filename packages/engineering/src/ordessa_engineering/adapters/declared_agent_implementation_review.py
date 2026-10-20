"""Schema17 holistic Agent report review bound to original Work and source.

No verdict, assignment, execution, authorization or selected-result state is
owned here. Original Unit declarations are not a fallback for Agent reports.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
from collections.abc import Mapping

from ordessa_execution_agents.profiles import ProfileRevisionRef, ProfileService, encode_revision_ref
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ..application.contracts.agent_report_review import (AgentReportAuthorship,
    AGENT_REPORT_REVIEW_CONTRACT, CAPABILITY, INTERFACE_VERSION)
from ..application.contracts.errors import ApplicationError
from ..application.contracts.reviewer_admission import SourceReviewBinding
from ..application.contracts.work_context import WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, WorkBinding, decode_work_binding
from ..application.usecases.changes.agent_declared_report import (resolve_agent_declared_report_binding,
    DeclaredAgentWorkReportSource)
from ..application.usecases.material_closure import verify_external_source
from ..domain.changes.agent_submission_report import AgentSubmissionReport
from ..domain.common.models.values import Digest
from ..domain.packages.models import ImplementationPackage, PreparedPackagePayload
from ..domain.reviews.models import (AggregationPolicy, CheckKey, CheckPolicy, CriterionSetRef,
    ReviewPlan, ReviewRequirement, Target, TargetSet)
from ..domain.reviews.refs import SubmissionRef
from ..methods.definitions.models import (CheckDefinition, CriterionDefinition, DispositionSpec,
    ResourceRef, ReductionSpec, StandardDefinition, freeze_value)

CONTRACT_RESOURCE = 'agent-report-review-contract'
CRITERIA_RESOURCE = 'implementation-review-criteria'


class DeclaredAgentImplementationReviewBindings:
    def __init__(self, factory, method_guard, profiles, expected_reviewer_profile_ref, *, report_source, source_materials):
        if (getattr(method_guard,'factory',None) is not factory or type(profiles) is not ProfileService
                or type(expected_reviewer_profile_ref) is not ProfileRevisionRef
                or getattr(getattr(factory,'library',None),'schema_version',None)!=17
                or type(report_source) is not DeclaredAgentWorkReportSource
                or report_source.factory is not factory or report_source.methods is not method_guard
                or getattr(source_materials,'factory',None) is not factory
                or not callable(getattr(source_materials,'read',None))
                or any(not callable(getattr(method_guard,name,None)) for name in ('guard','resource_ref','read_resource'))):
            raise ApplicationError('IMPLEMENTATION_REVIEW_AUTHORITY_UNAVAILABLE')
        self.factory,self.methods,self.profiles=factory,method_guard,profiles
        self.expected_profile_ref=expected_reviewer_profile_ref
        self.report_source,self.source_materials=report_source,source_materials

    @staticmethod
    def requirement_id(work, submission_ref, reviewer_profile):
        raw={'work_id':work.work_id,'revision':work.revision,'method_ref':asdict(work.method_ref),
             'submission_ref':asdict(submission_ref),'reviewer_profile':reviewer_profile}
        return 'implementation-review-'+hashlib.sha256(canonical_bytes(raw)).hexdigest()[:40]

    def _reviewer_profile(self, supplied):
        expected=encode_revision_ref(self.expected_profile_ref)
        if type(supplied) is not dict or supplied != expected:
            raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        profile=self.profiles.get(self.expected_profile_ref.profile_id)
        revision=self.profiles.get_revision(self.expected_profile_ref)
        if profile.archived_at is not None or revision.ref != self.expected_profile_ref:
            raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        return expected

    def _persisted_binding(self,context,work,submission,package):
        if (type(work) is not WorkBinding or type(submission) is not AgentSubmissionReport
                or type(package) is not ImplementationPackage or type(package.payload) is not PreparedPackagePayload
                or context.scope != work.scope or submission.scope != work.scope or package.scope != work.scope):
            raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        with self.factory.begin(context.scope,'read') as uow:
            head=uow.workflow.head_ref(WORK_CONTEXT_KIND,WORK_STABLE_ID_PREFIX+work.work_id)
            if head is None or head.revision != work.revision:raise ApplicationError('WORK_REVISION_STALE')
            current=decode_work_binding(uow.workflow.read(head))
            binding=resolve_agent_declared_report_binding(uow,submission)
            grant=uow.authorization.get_grant(binding.approval_ref)
            environments=tuple(env for _,scope in grant.intent.authorization.scope_by_action for env in scope.environment_refs)
            expected=self.expected_profile_ref
            if not any(env.environment_id==expected.environment_namespace and env.profile_id==expected.profile_id
                    and env.profile_digest.hex==expected.digest.removeprefix('sha256:') for env in environments):
                raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
            if (current != work or current.method_ref != package.payload.method_ref
                    or uow.submissions.resolve(submission.ref) != submission
                    or binding.work['work_id'] != work.work_id
                    or binding.work['action_id'] != 'incremental.implement-package'
                    or uow.implementation.resolve_package(binding.package_ref) != package):
                raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        return binding

    @contextmanager
    def guard_authorship(self,context,plan):
        """Hold exact method/report/source owners; no await or reviewer role grant."""
        targets=plan.requirement.expected_targets.targets
        if len(targets)!=1 or targets[0].role!='primary' or type(targets[0].ref) is not SubmissionRef:
            raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        with self.methods.guard(context,plan.requirement.method_ref):
            with self.factory.begin(context.scope,'read') as uow:
                submission=uow.submissions.resolve(targets[0].ref)
                binding=resolve_agent_declared_report_binding(uow,submission)
                package=uow.implementation.resolve_package(binding.package_ref)
            if (type(submission) is not AgentSubmissionReport or package.payload.method_ref != plan.requirement.method_ref
                    or submission.output_refs != (submission.method_content.rendered_body_ref,)):
                raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
            invocation=self.report_source.query_factory(binding)
            captured=self.report_source.records.capture_reference(submission.execution_ref,read_invocation=invocation)
            with self.report_source.guard_report(context,package,submission,captured):
                for ref in (package.payload.baseline,package.payload.candidate)+tuple(doc.source_ref for doc in package.payload.documents):
                    verify_external_source(context,ref,self.source_materials)
                yield AgentReportAuthorship(context.scope,plan.requirement.method_ref,submission.ref,
                    submission.execution_ref,submission.output_refs[0])

    @staticmethod
    def _step(definition,work,step_id=None):
        declared=definition.method_ref
        digest=declared.snapshot_digest.hex if hasattr(declared.snapshot_digest,'hex') else declared.snapshot_digest
        if (definition.schema_version!=2 or declared.method_id!=work.method_ref.method_id
                or declared.release_version!=work.method_ref.release_version
                or declared.schema_version!=work.method_ref.schema_version or digest!=work.method_ref.snapshot_digest.hex):
            raise ApplicationError('METHOD_PIN_MISMATCH')
        actions=tuple(a for a in definition.actions if a.action_id=='incremental.implement-package')
        steps=() if len(actions)!=1 else tuple(s for s in actions[0].steps if s.name=='independently-review-report'
            and s.kind=='invoke' and (step_id is None or s.step_id==step_id))
        if len(steps)!=1 or CONTRACT_RESOURCE not in {r.resource_id for r in actions[0].resources}:
            raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        if CONTRACT_RESOURCE not in {i.source_name for i in steps[0].inputs if i.source_kind=='resource'}:
            raise ApplicationError('AGENT_REVIEW_METHOD_CONTRACT_MISMATCH')
        return steps[0]

    def _build(self,context,work,submission,package,*,review_id,requirement_id,definition,step_id=None,resources=None):
        step=self._step(definition,work,step_id)
        if resources is not None and not isinstance(resources,Mapping):raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        exact=tuple(self.methods.resource_ref(context,work.method_ref,r.resource_id) for r in definition.resources)
        by_id={ref.resource_id:ref for ref in exact}; texts={}
        for item in step.inputs:
            if item.source_kind!='resource':continue
            ref=by_id.get(item.source_name)
            if ref is None:raise ApplicationError('METHOD_RESOURCE_MISMATCH')
            raw=self.methods.read_resource(context,ref)
            if type(raw) is not bytes or not raw or resources is not None and resources.get(item.name)!=raw:
                raise ApplicationError('METHOD_RESOURCE_MISMATCH')
            texts[item.source_name]=raw
        required={CONTRACT_RESOURCE,CRITERIA_RESOURCE,'independent-review-prompt','profile-selection-prompt'}
        if not required <= set(texts) or decode_json(texts[CONTRACT_RESOURCE]) != AGENT_REPORT_REVIEW_CONTRACT:
            raise ApplicationError('AGENT_REVIEW_METHOD_CONTRACT_MISMATCH')
        target=Target('primary',submission.ref); key=CheckKey(target,'implementation-review')
        criterion=CriterionDefinition(criterion_id='implementation-review',statement=texts[CRITERIA_RESOURCE].decode('utf-8'),
            checks=(CheckDefinition(capability_id=CAPABILITY,interface_version=INTERFACE_VERSION,
                bindings=freeze_value({'method_resource_id':CRITERIA_RESOURCE})),),
            policy=DispositionSpec(satisfied='pass',violated='block',insufficient='insufficient',unknown='insufficient'))
        standard=StandardDefinition(schema_version=1,standard_id=CRITERIA_RESOURCE,revision='1',criteria=(criterion,),
            reduction=ReductionSpec(required_criteria='all_applicable',empty_applicable_set='error',priority=('block','manual','pass')),
            resource_ref=ResourceRef(CRITERIA_RESOURCE,by_id[CRITERIA_RESOURCE].resource_digest.hex,'criteria'),purpose='acceptance')
        requirement=ReviewRequirement(context.scope,requirement_id,1,'acceptance',TargetSet((target,)),work.method_ref,
            CriterionSetRef(CRITERIA_RESOURCE,1,by_id[CRITERIA_RESOURCE].resource_digest),(key,),('reviewer',),step.step_id,
            schema_version=2,method_resource_refs=exact)
        return SourceReviewBinding(ReviewPlan(review_id,requirement,(CheckPolicy(key,True,True),),AggregationPolicy(),('reviewer',)),standard)

    def implementation_plan(self,context,work,*,review_id,submission,package,reviewer_profile_ref,requirement_id,resources):
        profile=self._reviewer_profile(reviewer_profile_ref)
        self._persisted_binding(context,work,submission,package)
        if requirement_id!=self.requirement_id(work,submission.ref,profile):raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        with self.methods.guard(context,work.method_ref) as definition:
            return self._build(context,work,submission,package,review_id=review_id,requirement_id=requirement_id,
                definition=definition,resources=resources).plan

    def resolve_declared_submission_plan(self,context,plan,definition):
        if type(plan) is not ReviewPlan:raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        targets=plan.requirement.expected_targets.targets
        if len(targets)!=1 or targets[0].role!='primary' or type(targets[0].ref) is not SubmissionRef:
            raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        profile=self._reviewer_profile(encode_revision_ref(self.expected_profile_ref))
        with self.factory.begin(context.scope,'read') as uow:
            submission=uow.submissions.resolve(targets[0].ref)
            binding=resolve_agent_declared_report_binding(uow,submission)
            head=uow.workflow.head_ref(WORK_CONTEXT_KIND,WORK_STABLE_ID_PREFIX+binding.work['work_id'])
            if head is None:raise ApplicationError('WORK_NOT_FOUND')
            work=decode_work_binding(uow.workflow.read(head));package=uow.implementation.resolve_package(binding.package_ref)
        self._persisted_binding(context,work,submission,package)
        expected=self._build(context,work,submission,package,review_id=plan.review_id,
            requirement_id=self.requirement_id(work,submission.ref,profile),definition=definition,step_id=plan.requirement.phase_key)
        if expected.plan!=plan:raise ApplicationError('METHOD_REVIEW_PLAN_CHANGED')
        return expected
