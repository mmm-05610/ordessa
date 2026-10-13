"""Engineering ReviewerAdmission over exact snapshots and actual source ports.

No model invocation or invented source verifier lives here. Missing original
reviewer/trust/bindings owners refuse; no synthetic fallback is composed.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
from ordessa_infrastructure.encoding import canonical_bytes
from ...contracts.errors import ApplicationError
from ...contracts.reviewer_admission import VerifiedReviewResponse, CriterionAnswer
from ...orchestration.method_bridge import MethodBridge
from ...orchestration.method_answers import nominal_binding, nominal_requires_matching_evaluation
from ..proposal_closure import resolve_record
from ....domain.changes.refs import ProposalRef
from ....domain.artifacts.refs import ArtifactRevisionRef
from ....domain.reviews.refs import SubmissionRef
from ....domain.reviews.models import ReviewPlan, ReviewRecord, Observation, observations_digest
from ....domain.reviews.evidence import VerifiedReviewerEvidence
from ....domain.reviews.identity import RecordIdentity
from ....domain.common.models.values import Digest
from ....domain.common.mechanisms.hashing import record_digest
from .service import _trust


def review_observations(plan, standard, answers):
    if type(plan) is not ReviewPlan:
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    return _review_observations(plan, standard, answers, plan.check_keys)


def review_observations_subset(plan, standard, answers, check_keys):
    if (type(plan) is not ReviewPlan or type(check_keys) is not tuple or not check_keys or len(set(check_keys)) != len(check_keys)
            or not set(check_keys) <= set(plan.check_keys)):
        raise ApplicationError('REVIEW_SOURCE_INVALID')
    return _review_observations(plan, standard, answers, check_keys)


def _review_observations(plan, standard, answers, check_keys):
    """Project complete admitted answers using Engineering's frozen policies.

    Public pure conversion for actual source adapters: no authentication, model
    call or trust elevation. The caller must supply the exact frozen standard;
    admission independently calls this same function before recording evidence.
    """
    if (type(plan) is not ReviewPlan or type(answers) is not tuple
            or getattr(standard, 'standard_id', None) != plan.requirement.criterion_set_ref.criterion_set_id
            or getattr(getattr(standard, 'resource_ref', None), 'sha256', None)
                != plan.requirement.criterion_set_ref.digest.hex):
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    criteria = {c.criterion_id: c for c in standard.criteria}
    observations, seen = [], set()
    for answer in answers:
        if (type(answer) is not CriterionAnswer or answer.check_key not in check_keys
                or answer.check_key in seen or answer.status not in ('satisfied','violated','insufficient','unknown')):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        seen.add(answer.check_key)
        criterion = criteria.get(answer.check_key.criterion_id)
        if criterion is None:
            raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
        if len(criterion.checks) != 1 or criterion.decision_policy is not None:
            raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
        disposition = getattr(criterion.policy, answer.status)
        nominal = nominal_binding(criterion)
        if nominal is not None and nominal_requires_matching_evaluation(criterion):
            # Honor only an explicit method-level evaluation requirement.
            disposition = 'manual'
        result = {'pass':'pass','block':'fail','manual':'indeterminate','insufficient':'indeterminate'}[disposition]
        observations.append(Observation(answer.check_key, result, answer.evidence_refs, answer.rationale))
    if seen != set(check_keys):
        raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
    return tuple(sorted(observations, key=lambda o:o.check_key.sort_key))


class EngineeringReviewAdmission:
    def __init__(self, factory, method_control, bindings, reviewer_source=None):
        if getattr(method_control,'factory',None) is not factory:
            raise ApplicationError('METHOD_AUTHORITY_MISMATCH')
        self.factory,self.methods,self.bindings,self.source=factory,method_control,bindings,reviewer_source
        self.bridge=MethodBridge()

    def _expected(self, context, plan, snapshot):
        if self.bindings is None:
            raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
        binding=self.bindings.resolve_bindings(context,plan.requirement.method_ref,plan.requirement.phase_key)
        if binding.scope != context.scope or binding.phase_key != plan.requirement.phase_key:
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        self.bridge.require_workflow_phase(snapshot, binding)
        proposals={t.ref for t in binding.targets.targets if type(t.ref) is ProposalRef}
        selector = getattr(self.bindings, 'resolve_review_proposal', None)
        if callable(selector):
            selected = selector(context, plan.requirement.method_ref, plan.requirement.phase_key)
            if selected is not None:
                if (type(selected) is not ProposalRef
                        or (selected.realm_id, selected.project_id) != (context.scope.realm_id, context.scope.project_id)
                        or proposals and proposals != {selected}):
                    raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
                proposals = {selected}
            elif proposals:
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        submission_selector = getattr(self.bindings, 'resolve_review_submission', None)
        submission_ref = (submission_selector(context, plan.requirement.method_ref, plan.requirement.phase_key)
                          if callable(submission_selector) else None)
        if submission_ref is not None:
            if (type(submission_ref) is not SubmissionRef
                    or (submission_ref.realm_id, submission_ref.project_id) !=
                       (context.scope.realm_id, context.scope.project_id)):
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
            resolver = getattr(self.bindings, 'resolve_submission_bindings', None)
            if not callable(resolver):
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
            phase_bindings = resolver(context, plan.requirement.method_ref, submission_ref)
            if (type(phase_bindings) is not tuple or not phase_bindings or binding not in phase_bindings
                    or len({b.phase_key for b in phase_bindings}) != len(phase_bindings)):
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
            for phase in phase_bindings:
                if phase.scope != context.scope or phase.review_purpose != 'acceptance':
                    raise ApplicationError('METHOD_REVIEW_PURPOSE_UNAVAILABLE')
                self.bridge.require_workflow_phase(snapshot, phase)
            from ..changes.acceptance_closure import resolve_submission_acceptance
            with self.factory.begin(context.scope, 'read') as uow:
                closure = resolve_submission_acceptance(uow, submission_ref)
            if (closure.submission.ref != submission_ref
                    or closure.package.payload.method_ref != plan.requirement.method_ref):
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
            self.bridge.submission_review_requirements(snapshot, phase_bindings,
                requirements=closure.requirements, revisions=closure.artifact_revisions)
            expected = self.bridge.review_plan(snapshot, binding, plan.requirement,
                plan.review_id, revisions=closure.artifact_revisions,
                phase_bindings=phase_bindings, submission_requirements=closure.requirements)
            if expected != plan:
                raise ApplicationError('METHOD_REVIEW_PLAN_CHANGED')
            standards = [s for s in snapshot.program.standard_definitions
                if s.resource_ref.sha256 == plan.requirement.criterion_set_ref.digest.hex
                and s.standard_id == plan.requirement.criterion_set_ref.criterion_set_id]
            if len(standards) != 1:
                raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
            return standards[0]
        if any(type(t.ref) is SubmissionRef for t in binding.targets.targets):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        arguments={}
        materials=[]
        # Resolve every exact material target from the original authority.
        with self.factory.begin(context.scope,'read') as uow:
            for target in binding.targets.targets:
                if type(target.ref) is ArtifactRevisionRef:
                    materials.append(uow.engineering.resolve_revision(target.ref))
                elif type(target.ref) is not ProposalRef:
                    raise ApplicationError('METHOD_SUBJECT_OWNER_UNAVAILABLE')
        arguments['revisions']=tuple({m.ref:m for m in materials}.values())
        if proposals:
            if len(proposals)!=1:
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
            with self.factory.begin(context.scope,'read') as uow:
                proposal=uow.proposals.get_proposal(next(iter(proposals)))
                budget=uow.proposals.validated_budget()
                resolve_record(proposal,uow.proposals,budget)
                roots=tuple(m.proposed_ref for m in proposal.mutations)+tuple(m.base_ref for m in proposal.mutations if m.base_ref is not None)+tuple(c.owner_revision_ref for c in proposal.claim_refs)
                revisions=uow.proposals.resolve_revision_graph(roots,budget)
                owners=tuple(uow.engineering.get_artifact(m.artifact_id) for m in proposal.mutations)
                owners=tuple(replace(o,head_revision_id=None) if m.operation=='create' else o for o,m in zip(owners,proposal.mutations))
            arguments=dict(proposal=proposal,artifacts=owners,revisions=revisions)
            resolver = getattr(self.bindings, 'resolve_intent_bindings', None)
            if callable(resolver):
                phases = resolver(context, plan.requirement.method_ref, proposal.ref)
                if type(phases) is not tuple or binding not in phases:
                    raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
                for phase in phases:
                    self.bridge.require_workflow_phase(snapshot, phase)
                arguments['phase_bindings'] = phases
        expected=self.bridge.review_plan(snapshot,binding,plan.requirement,plan.review_id,**arguments)
        if expected != plan:
            raise ApplicationError('METHOD_REVIEW_PLAN_CHANGED')
        standards=[s for s in snapshot.program.standard_definitions if s.resource_ref.sha256==plan.requirement.criterion_set_ref.digest.hex and s.standard_id==plan.requirement.criterion_set_ref.criterion_set_id]
        if len(standards)!=1:
            raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
        return standards[0]

    @contextmanager
    def guard_plan(self, context, plan):
        if type(plan) is not ReviewPlan or plan.scope != context.scope:
            raise ApplicationError('INVALID_INPUT')
        with self.methods.guard_method(context,plan.requirement.method_ref) as snapshot:
            self._expected(context,plan,snapshot)
            yield

    def verify_response(self, context, plan, request, raw_response_ref):
        if self.source is None:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        with self.methods.guard_method(context,plan.requirement.method_ref) as snapshot:
            standard=self._expected(context,plan,snapshot)
        if (request.scope!=context.scope or request.review_id!=plan.review_id or request.state!='requested'):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        # The trusted source owner verifies actual provenance; Engineering owns
        # the disposition conversion. No source can directly submit a verdict.
        verified=self.source.verify_response(context,plan,request,raw_response_ref,standard=standard)
        if type(verified) is not VerifiedReviewResponse or type(verified.reviewer_evidence) is not VerifiedReviewerEvidence or type(verified.answers) is not tuple:
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        evidence=verified.reviewer_evidence
        if (evidence.scope!=context.scope or evidence.request_digest!=plan.request_digest or evidence.raw_response_digest!=raw_response_ref.digest or not set(evidence.roles)&set(plan.reviewer_requirements)):
            raise ApplicationError('UNTRUSTED_REVIEWER')
        observations=review_observations(plan,standard,verified.answers)
        if evidence.observations_digest != observations_digest(observations):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        return ReviewRecord(RecordIdentity(context.scope,plan.review_id,context.received_at,context.authenticated_actor,schema_version=2),plan,evidence,observations,raw_response_ref=raw_response_ref)

    @contextmanager
    def guard_trust(self, context, records):
        if self.source is None:
            raise ApplicationError('REVIEW_TRUST_UNAVAILABLE')
        if type(records) is not tuple or any(type(r) is not ReviewRecord or r.plan.scope!=context.scope for r in records):
            raise ApplicationError('INVALID_INPUT')
        with self.source.guard_trust(context,records) as current:
            yield _trust(records,current)
