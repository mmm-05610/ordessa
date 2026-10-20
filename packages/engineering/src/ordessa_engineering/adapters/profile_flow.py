"""Method-bounded Profile choice through one real current Decision job.

The same owner job-services composition supplies explicit scope/invocation and
original evidence; it carries no SourceReviewer policy in this adapter. Selection
never starts an Agent or supplies its authorization.
"""
from dataclasses import dataclass
from collections.abc import Mapping

from decision_runtime import DecisionError, DecisionQuestion, PolicyRef
from decision_runtime.job import validate_job
from .decision.source_job import SourceReviewJobServices
from ..application.contracts.errors import ApplicationError
from ..domain.common.outcomes.library_failures import EngineeringError


@dataclass(frozen=True)
class ProfileSelectionServices:
    jobs: SourceReviewJobServices
    policy_refs: tuple[PolicyRef, ...]


@dataclass(frozen=True)
class MethodProfileSelectionResult:
    """Engineering selection status, separate from its original Decision result."""
    status: str
    decision: object = None
    disposition: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class _ProfileRequest:
    request_id: str
    questions: tuple
    policy_refs: tuple
    review_ref: str
    limits: Mapping
    provider: object

    def to_job(self):
        question = self.questions[0]
        projected = question.projection()
        body = {key: projected[key] for key in ('kind', 'version', 'options', 'scale',
            'evidence_ids', 'allowed_answer_ids', 'bounded_state', 'policy_ref')}
        body['text'] = projected['question_text']
        return {'spec_version': 'decision-job/1', 'job_id': self.request_id, 'version': 1,
            'input': {'run': True, 'review_ref': self.review_ref,
                'policy_refs': [{'policy_id': ref.policy_id, 'version': ref.version,
                    'content_digest': ref.content_digest} for ref in self.policy_refs],
                'review_provider': {'binding_ref': self.provider.binding_ref,
                    'settings_digest': self.provider.settings_digest}},
            'limits': dict(self.limits),
            'steps': [{'id': question.question_id, 'type': 'ask', 'engine': None,
                'when': {'fact': 'input.run', 'op': 'eq', 'value': True}, 'payload': {'question': body}},
                {'id': 'collect-profile-answer', 'type': 'rules', 'engine': None,
                 'when': {'fact': 'input.run', 'op': 'eq', 'value': True},
                 'payload': {'collect': [question.question_id]}}],
            'result': {'from': 'collect-profile-answer', 'path': ['values', 'answers']}}


class _OriginalProfileJob:
    """Actual choice port over original capability execution and read proof."""
    def __init__(self, services, context, policy, request_id, review_ref, limits):
        self.services, self.context, self.policy = services, context, policy
        self.request_id, self.review_ref, self.limits = request_id, review_ref, limits
        self.operation = None

    async def decide(self, question):
        if type(question) is not DecisionQuestion or question.policy_ref != self.policy:
            raise DecisionError('flow_policy_mismatch')
        request = _ProfileRequest(self.request_id, (question,), (self.policy,),
            self.review_ref, self.limits, self.services.decision_provider)
        validate_job(request.to_job(), host_limits=self.services.host_limits)
        self.operation = await self.services.run(request, self.context, lambda: None)
        if self.operation.status != 'completed':
            raise ApplicationError('PROFILE_SELECTION_DECISION_NOT_COMPLETED', retry='reconcile')
        proof = self.services.reader(self.context, self.request_id).read(self.request_id,
            request.to_job(), (question,), provider_binding=request.provider.binding_ref,
            provider_settings=request.provider.settings_digest, allow_ties=True)
        return proof.answers[0]


async def run_method_profile_selection(selection, context, task, *, services,
                                       request_id, review_ref, limits):
    """Return fixed native Profile, exact durable answer, Engineering result.

    A tie/decline remains a failed selection even if the native job completed.
    Cancellation propagates; unresolved native requests remain UNKNOWN and are
    never retried by this adapter. ``review_ref`` is bound input data, not a
    Decision grant. Agent start requires a separate explicit create_agent call.
    """
    keys = {'max_model_calls', 'max_steps', 'max_value_bytes', 'timeout_seconds'}
    if (not isinstance(limits, Mapping) or set(limits) != keys
            or type(limits['max_model_calls']) is not int or limits['max_model_calls'] != 1
            or type(limits['max_steps']) is not int or limits['max_steps'] != 2):
        raise ApplicationError('PROFILE_SELECTION_LIMITS_INVALID')
    if type(review_ref) is not str or not review_ref:
        raise ApplicationError('PROFILE_SELECTION_FLOW_UNREVIEWED')
    if (type(services) is not ProfileSelectionServices
            or type(services.jobs) is not SourceReviewJobServices
            or not callable(getattr(services.jobs.decision_provider, 'decide', None))):
        raise ApplicationError('PROFILE_SELECTION_SERVICES_UNAVAILABLE')
    policy = selection.policy_ref(context)
    if services.policy_refs != (policy,):
        raise DecisionError('flow_policy_mismatch')
    original = _OriginalProfileJob(services.jobs, context, policy, request_id, review_ref, dict(limits))
    try:
        selected, answer = await selection.select(context, task, gateway=original, request_id=request_id)
    except (ApplicationError, EngineeringError) as error:
        status = (original.operation.status if original.operation is not None
                  and original.operation.status != 'completed' else 'failed')
        return None, None, MethodProfileSelectionResult(status, original.operation, error_code=getattr(error, 'code', str(error)))
    return selected, answer, MethodProfileSelectionResult('completed', original.operation, 'clarify')


__all__ = ['run_method_profile_selection', 'ProfileSelectionServices', 'MethodProfileSelectionResult']
