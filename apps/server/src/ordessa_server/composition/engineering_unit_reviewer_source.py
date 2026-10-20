"""Read-only recorded Unit reviewer adapter; methods retain review policy.

Trusted composition supplies original run selection, method decoder and policy
constraint guard. No wire callable, execution, retry, file scan or human claim.
Missing selections/decoder/guards refuse. This module does not create a
Submission or establish a production selection authority.
"""
import json
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.reviewer_admission import VerifiedReviewResponse
from ordessa_engineering.application.usecases.changes.execution_capture import capture_execution_observation
from ordessa_engineering.application.usecases.reviews.admission import review_observations
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_engineering.domain.reviews.models import CurrentReviewTrust, observations_digest

UNIT_REVIEW_SOURCE_CAPABILITY = 'engineering.reviewer.unit'


@dataclass(frozen=True)
class RecordedUnitReview:
    """Trusted root binding, not a wire input or self-authenticating receipt.

    The original submission owner must select author_unit_utf8 and the exact
    plan; the actual source owner selects reviewer_unit_utf8/operation and
    captures observation through authorized original UnitRecords.
    """
    review_id: str
    plan_digest: object
    request_version: int
    fence: int
    author_unit_utf8: bytes
    reviewer_unit_utf8: bytes
    prompt_params_utf8: bytes
    observation: object


def unit_review_prompt_binding(plan, version, fence, author_unit, reviewer_unit):
    """One exact text block for the normal Unit prompt; no policy instructions."""
    return canonical_bytes({'ordessa.unit-review': {
        'plan': asdict(plan), 'request_version': version, 'fence': fence,
        'author_unit': author_unit, 'reviewer_unit': reviewer_unit}}).decode('utf-8')


def encode_recorded_unit_review(run):
    return canonical_bytes({'contract': 'ordessa.recorded-unit-review/1',
        'review_id': run.review_id, 'plan_digest': asdict(run.plan_digest),
        'request_version': run.request_version, 'fence': run.fence,
        'author_unit': json.loads(run.author_unit_utf8),
        'reviewer_unit': json.loads(run.reviewer_unit_utf8),
        'observation': asdict(run.observation)})


class OriginalUnitReviewerSource:
    def __init__(self, *, records, blobs, access, scope, method_control, runs,
                 query_factory, decode_answers, policy_guard, roles):
        self.records, self.blobs, self.access, self.scope = records, blobs, access, scope
        self.methods, self.runs = method_control, tuple(runs)
        self.query_factory, self.decoder, self.policy_guard = query_factory, decode_answers, policy_guard
        self.roles = tuple(roles)
        self.verifier_id, self.verifier_version = 'ordessa.recorded-unit-source', '1'
        if (getattr(getattr(method_control, 'factory', None), 'authority_id', None)
                != getattr(blobs, 'authority_id', None) or not getattr(blobs, 'authority_id', None)):
            raise ApplicationError('METHOD_AUTHORITY_MISMATCH')

    def _run(self, plan):
        matches = tuple(r for r in self.runs if r.review_id == plan.review_id
                        and r.plan_digest == plan.plan_digest)
        if len(matches) != 1 or type(matches[0]) is not RecordedUnitReview:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        return matches[0]

    @contextmanager
    def _guard(self, context, plan, run):
        if ((context.scope.realm_id, context.scope.project_id) != (self.scope.realm_id, self.scope.project_id)
                or plan.scope != context.scope or not self.roles
                or not set(plan.reviewer_requirements) <= set(self.roles)
                or not set(self.roles) <= set(plan.requirement.eligible_reviewer_roles)
                or not all(callable(v) for v in (self.query_factory, self.decoder, self.policy_guard))):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        with ExitStack() as guards:
            caller = guards.enter_context(self.access.guard_current_capability(
                context, self.scope, UNIT_REVIEW_SOURCE_CAPABILITY))
            snapshot = guards.enter_context(self.methods.guard_method(context, plan.requirement.method_ref))
            # Original configured policy owner validates selected actual Unit
            # identities and method constraints, holding its guard to COMMIT.
            # No global author!=reviewer rule is invented here.
            guards.enter_context(self.policy_guard(context, snapshot, plan, run))
            yield caller, snapshot

    def _answers(self, context, plan, run, raw_ref, standard):
        if self.blobs.read_verified(raw_ref) != encode_recorded_unit_review(run):
            raise ApplicationError('REVIEW_RAW_RESPONSE_INVALID')
        unit = json.loads(run.reviewer_unit_utf8)
        author = json.loads(run.author_unit_utf8)
        params = json.loads(run.prompt_params_utf8)
        expected_block = unit_review_prompt_binding(plan, run.request_version, run.fence, author, unit)
        if (type(params) is not dict or type(params.get('sessionId')) is not str
                or type(params.get('prompt')) is not list
                or sum(block == {'type': 'text', 'text': expected_block}
                       for block in params['prompt']) != 1):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        digest = self.records.acp_prompt_input_digest(unit, params)
        if run.observation.expected_prompt_digest != digest:
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        captured = capture_execution_observation(self.records, self.blobs,
            authority_id=self.blobs.authority_id, unit_ref=unit,
            operation_ref=run.observation.operation_ref, expected_prompt_digest=digest,
            query_invocation=self.query_factory(context, run))
        if captured != run.observation or captured.state != 'completed':
            raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        receipt = json.loads(self.blobs.read_verified(captured.blob_ref))
        summary = receipt.get('summary', {})
        if (receipt.get('input') != {'unitRef': unit, 'params': params}
                or summary.get('successfulRpcResponse') is not True
                or summary.get('stopReason') != 'end_turn' or type(summary.get('text')) is not str):
            raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        # The selected external method defines the structured output codec.
        # Original Engineering projection checks complete keys and dispositions.
        answers = self.decoder(plan, standard, summary['text'])
        observations = review_observations(plan, standard, answers)
        return answers, observations

    def _evidence(self, caller, plan, run, raw_ref, observations):
        identity = record_digest('recorded-unit-reviewer', json.loads(run.reviewer_unit_utf8))
        capability = record_digest('recorded-unit-review-source', {
            'scope': asdict(self.scope), 'principal_id': caller.principal_id,
            'credential_epoch': caller.credential_epoch, 'roles': self.roles,
            'unit_ref': json.loads(run.reviewer_unit_utf8),
            'capability': UNIT_REVIEW_SOURCE_CAPABILITY})
        return VerifiedReviewerEvidence(plan.scope, ActorRef('unit-'+identity.hex, 'agent', 'unit-records'),
            self.roles, self.verifier_id, self.verifier_version, caller.credential_epoch,
            plan.request_digest, raw_ref.digest, observations_digest(observations), capability)

    def verify_response(self, context, plan, request, raw_response_ref, *, standard):
        run = self._run(plan)
        if (request.state != 'requested' or request.version != run.request_version or request.fence != run.fence):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        with self._guard(context, plan, run) as (caller, _):
            answers, observations = self._answers(context, plan, run, raw_response_ref, standard)
            return VerifiedReviewResponse(self._evidence(caller, plan, run, raw_response_ref, observations), answers)

    @contextmanager
    def guard_trust(self, context, records):
        with ExitStack() as guards:
            current = []
            for record in records:
                plan, run = record.plan, self._run(record.plan)
                caller, snapshot = guards.enter_context(self._guard(context, plan, run))
                ref = plan.requirement.criterion_set_ref
                standards = tuple(s for s in snapshot.program.standard_definitions
                    if s.standard_id == ref.criterion_set_id and s.resource_ref.sha256 == ref.digest.hex)
                if len(standards) != 1:
                    raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
                _, observations = self._answers(context, plan, run, record.raw_response_ref, standards[0])
                if record.reviewer_evidence != self._evidence(caller, plan, run, record.raw_response_ref, observations):
                    raise ApplicationError('UNTRUSTED_REVIEWER')
                current.append(CurrentReviewTrust(record.ref, self.verifier_id, caller.credential_epoch))
            yield tuple(current)
