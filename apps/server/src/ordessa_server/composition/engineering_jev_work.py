"""Original-authority preparation and capture of pending JEV evidence.

This service does not issue a Grant or complete unsupported checks. Dispatch
uses the original Decision runtime; callers must retain its run/intent and must
not resend an unknown operation. No new work/status table is introduced.
"""
from dataclasses import asdict, dataclass
import hashlib

from ordessa_decision.definitions import plain
from ordessa_decision.definitions.values import canonical
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
from ordessa_engineering.application.usecases.proposal_closure import resolve_record
from ordessa_engineering.domain.common.models.values import Digest

from .engineering_jev_questions import build_nominal_jev_questions
from .engineering_jev_run import execute_jev_review
from .engineering_reviewer_source import JEV_SOURCE_CAPABILITY, encode_review_run


@dataclass(frozen=True)
class PreparedJevInput:
    plan: object
    request: object
    standard: object
    proposal_ref: object
    questions: tuple
    unavailable_checks: tuple
    receipt_bytes: bytes


class OriginalJevWork:
    def __init__(self, *, factory, access, scope, methods, bindings, admission, blobs):
        if (getattr(methods, 'factory', None) is not factory
                or getattr(bindings, 'factory', None) is not factory
                or getattr(admission, 'factory', None) is not factory
                or getattr(blobs, 'authority_id', None) != factory.authority_id):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        self.factory, self.access, self.scope = factory, access, scope
        self.methods, self.bindings, self.admission, self.blobs = methods, bindings, admission, blobs

    def prepare(self, context, review_id, policy_ref):
        """Read the original request and complete immutable declared graph."""
        with self.access.guard_current_capability(context, self.scope, JEV_SOURCE_CAPABILITY):
            with self.factory.begin(context.scope, 'read') as uow:
                plan, request = uow.reviews.get_plan(review_id), uow.reviews.get_request(review_id)
            if plan is None or request is None or request.state != 'requested':
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            with self.admission.guard_plan(context, plan):
                with self.methods.guard_method(context, plan.requirement.method_ref) as snapshot:
                    proposal_ref = self.bindings.resolve_review_proposal(context,
                        plan.requirement.method_ref, plan.requirement.phase_key)
                    with self.factory.begin(context.scope, 'read') as uow:
                        budget = uow.proposals.validated_budget()
                        proposal = uow.proposals.get_proposal(proposal_ref, budget=budget)
                        resolve_record(proposal, uow.proposals, budget)
                        roots = tuple(m.proposed_ref for m in proposal.mutations) + tuple(
                            m.base_ref for m in proposal.mutations if m.base_ref is not None) + tuple(
                            c.owner_revision_ref for c in proposal.claim_refs)
                        revisions = uow.proposals.resolve_revision_graph(roots, budget)
                        standards = tuple(s for s in snapshot.program.standard_definitions
                            if s.standard_id == plan.requirement.criterion_set_ref.criterion_set_id
                            and s.resource_ref.sha256 == plan.requirement.criterion_set_ref.digest.hex)
                        if len(standards) != 1:
                            raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
                        standard = standards[0]
                        questions = build_nominal_jev_questions(uow=uow, budget=budget,
                            proposal=proposal, revisions=revisions, snapshot=snapshot,
                            plan=plan, request=request, standard=standard, policy_ref=policy_ref)
            selected = {q.check_key for q in questions}
            unavailable = tuple({'check_key':asdict(key), 'reason':'CHECK_SOURCE_UNAVAILABLE',
                'capabilities':tuple(c.capability_id for criterion in standard.criteria
                    if criterion.criterion_id == key.criterion_id for c in criterion.checks)}
                for key in plan.check_keys if key not in selected)
            receipt = canonical({'schema':'ordessa.jev-input-receipt/1',
                'authority_id':self.factory.authority_id, 'proposal_ref':asdict(proposal_ref),
                'plan':asdict(plan), 'request':asdict(request),
                'questions':[{'check_key':asdict(q.check_key), 'question':plain(q.question),
                    'input_digest':q.input_digest, 'input_truncated':q.input_truncated,
                    'evidence_refs':[asdict(r) for r in q.evidence_refs]} for q in questions],
                'unavailable_checks':unavailable}, max_bytes=2097152)
            return PreparedJevInput(plan, request, standard, proposal_ref, questions, unavailable, receipt)

    async def run(self, context, prepared, *, provider, evidence_sink, read_context,
            request_id, task_revision, review_ref, wall_timeout_seconds=120):
        """One original run; never complete the missing mixed-check sources."""
        with self.access.guard_current_capability(context, self.scope, JEV_SOURCE_CAPABILITY):
            current = self.prepare(context, prepared.plan.review_id, prepared.questions[0].question.policy_ref)
            if current != prepared:
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            return await execute_jev_review(plan=prepared.plan, request=prepared.request,
                questions=prepared.questions, standard=prepared.standard,
                provider=provider, evidence_sink=evidence_sink, read_context=read_context,
                request_id=request_id, task_revision=task_revision, review_ref=review_ref,
                wall_timeout_seconds=wall_timeout_seconds, nominal_evidence_only=True)

    def _capture_reads(self, prepared):
        try:
            from ordessa_engineering.application.contracts.commands import ReadSet
            from ordessa_engineering.domain.reviews.models import ReviewRequestExpectation
        except ImportError:
            raise ApplicationError('REVIEW_CAPTURE_AUTHORITY_UNAVAILABLE') from None
        expectation = ReviewRequestExpectation(prepared.plan.scope,
            prepared.plan.review_id, prepared.plan.plan_digest,
            prepared.request.version, prepared.request.fence)
        return ReadSet(prepared.plan.scope, (), review_requests=(expectation,))

    def capture(self, context, prepared, run, *, source):
        """Persist exact bytes in ordinary evidence Artifact, never ReviewRecord.

        This requires the original owner's atomic request expectation. It is a
        verified one-way evidence binding, not an attachment mutation of the
        frozen ReviewRequest or a new pending registry.
        """
        reads = self._capture_reads(prepared)
        with self.access.guard_current_capability(context, self.scope, JEV_SOURCE_CAPABILITY):
            current = self.prepare(context, prepared.plan.review_id, prepared.questions[0].question.policy_ref)
            if (current != prepared or not run.evidence_only
                    or run.plan_request_digest != prepared.plan.request_digest
                    or run.request_version != prepared.request.version or run.fence != prepared.request.fence
                    or run.scope != prepared.plan.scope or run.review_id != prepared.plan.review_id
                    or {c.check_key for c in run.checks} != {q.check_key for q in prepared.questions}):
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            raw = encode_review_run(run)
            input_ref = self.blobs.put_verified(prepared.receipt_bytes,
                Digest('sha256', hashlib.sha256(prepared.receipt_bytes).hexdigest()), 'application/json')
            raw_ref = self.blobs.put_verified(raw,
                Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/json')
            if self.blobs.read_verified(input_ref) != prepared.receipt_bytes or self.blobs.read_verified(raw_ref) != raw:
                raise ApplicationError('REVIEW_RAW_RESPONSE_INVALID')
            if (source.access is not self.access or source.blobs.authority_id != self.factory.authority_id):
                raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
            results = source.verify_pending_evidence(context, prepared.plan, prepared.request,
                raw_ref, standard=prepared.standard)
            with self.admission.guard_plan(context, prepared.plan):
                return self._create_evidence(context, prepared, run, results, input_ref, raw_ref, reads)

    def _create_evidence(self, context, prepared, run, results, input_ref, raw_ref, reads):
        return ArtifactUseCases(self.factory, self.access).create({'kind':'other', 'initial':{
                'media_type':'application/json', 'schema_id':'urn:ordessa:jev-pending-evidence:1',
                'inline_value':{'review_id':run.review_id, 'request_version':run.request_version,
                    'request_fence':run.fence, 'proposal_ref':asdict(prepared.proposal_ref),
                    'plan_request_digest':asdict(run.plan_request_digest),
                    'plan_digest':asdict(prepared.plan.plan_digest),
                    'input_receipt_ref':asdict(input_ref), 'raw_response_ref':asdict(raw_ref),
                    'decision_run_id':run.run_id, 'observed_review_state':'requested',
                    'nominal_results':[asdict(result) for result in results],
                    'unavailable_checks':list(prepared.unavailable_checks),
                    'formal_review_record':False, 'user_confirmation':False, 'grant':False}}}, context,
                    read_set=reads)
