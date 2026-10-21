"""Explicit source-review input and one current Decision job, without Graph state."""
from dataclasses import asdict, dataclass
from hashlib import sha256

from ordessa_decision import DecisionAnswer, DecisionRunner, FilesystemEvidenceStore, RulesOutcome
from ordessa_decision.capability import build_capability
from ordessa_decision.evidence import EvidenceScope
from ordessa_decision.settings import DecisionsSettings
from ordessa_decision.definitions.values import canonical_bytes, MAX_JOB_DOCUMENT_BYTES

from ...application.contracts.errors import ApplicationError
from .job_evidence import OriginalReviewJobEvidence


@dataclass(frozen=True)
class SourceReviewTask:
    task_id: str
    task_revision: str
    goal: str
    inputs: tuple = ()
    boundaries: tuple = ()
    acceptance_criteria: tuple = ()
    context_refs: tuple = ()
    continuation_ref: object = None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class SourceReviewRequest:
    request_id: str
    task: SourceReviewTask
    questions: tuple
    policy_refs: tuple
    provider_binding: str
    provider_settings: str
    timeout_seconds: float

    def to_job(self):
        steps = []
        for question in self.questions:
            projected = question.projection()
            payload = {key: projected[key] for key in ('kind', 'version', 'options', 'scale',
                'evidence_ids', 'allowed_answer_ids', 'bounded_state', 'policy_ref')}
            payload['text'] = projected['question_text']
            steps.append({'id': question.question_id, 'type': 'ask', 'engine': None,
                'when': {'fact': 'input.run', 'op': 'eq', 'value': True}, 'payload': {'question': payload}})
        ids = [question.question_id for question in self.questions]
        steps.append({'id': 'collect-source-answers', 'type': 'rules', 'engine': None,
            'when': {'fact': 'input.run', 'op': 'eq', 'value': True}, 'payload': {'collect': ids}})
        return {'spec_version': 'decision-job/1', 'job_id': self.request_id, 'version': 1,
            'input': {'run': True, 'task': asdict(self.task),
                'policy_refs': [asdict(ref) for ref in self.policy_refs],
                'review_provider': {'binding_ref': self.provider_binding, 'settings_digest': self.provider_settings}},
            'limits': {'max_model_calls': len(ids), 'max_steps': len(steps),
                       'max_value_bytes': 65536, 'timeout_seconds': float(self.timeout_seconds)},
            'steps': steps, 'result': {'from': 'collect-source-answers', 'path': ['values', 'answers']}}

    @property
    def request_digest(self):
        # Same canonical digest as the original capability reservation. No run
        # right is issued by computing this value, including for over-limit jobs.
        return sha256(canonical_bytes({'job': self.to_job(), 'dryRun': False}, maximum=MAX_JOB_DOCUMENT_BYTES)).hexdigest()


class _CollectSourceAnswers:
    engine_id = 'engineering-source-review-answer-collection/1'

    def __init__(self, questions):
        self.ids = [question.question_id for question in questions]

    def validate(self, payload):
        if payload != {'collect': self.ids}:
            raise ApplicationError('REVIEW_SOURCE_INVALID')

    def evaluate(self, payload, facts):
        return RulesOutcome(values={'answers': [DecisionAnswer(key, 'choice',
            facts[key]['answer'], facts[key]['receipt'], facts[key]['usage']).projection()
            for key in self.ids]}, disposition='revise')

    def close(self):
        pass


class _GuardedProvider:
    def __init__(self, original, guard):
        self.original, self.guard = original, guard
        self.binding_ref, self.settings_digest = original.binding_ref, original.settings_digest

    async def decide(self, question, context):
        context.permit.bind_claim_guard(self.guard)
        return await self.original.decide(question, context)


@dataclass(frozen=True)
class SourceReviewJobServices:
    """Trusted process-local wiring, with explicit invocation and evidence scope.

    Resolvers authenticate outside this adapter. No wire context or reviewer
    label is made into a grant; no default scope/provider or extra budget exists.
    """
    decision_provider: object
    evidence: FilesystemEvidenceStore
    invocation_resolver: object
    evidence_scope_resolver: object
    invocation_context_factory: object
    host_limits: object = None
    job_document_max_bytes: int | None = None
    historical_reader: object = None
    historical_read_context: object = None

    def __post_init__(self):
        if (type(self.evidence) is not FilesystemEvidenceStore
                or not callable(getattr(self.decision_provider, 'decide', None))
                or any(not callable(value) for value in (self.invocation_resolver,
                    self.evidence_scope_resolver, self.invocation_context_factory))):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        # Validate and freeze configured host limits using the original owner.
        settings = DecisionsSettings(DecisionRunner, self.evidence, host_limits=self.host_limits,
                                     job_document_max_bytes=self.job_document_max_bytes)
        object.__setattr__(self, 'host_limits', settings.host_limits)

    def _context(self, context, request_id):
        native = self.invocation_context_factory(context, request_id)
        if getattr(native, 'request_id', None) != request_id:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        return native

    def reader(self, context, request_id):
        native = self._context(context, request_id)
        invocation = self.invocation_resolver(native)
        scope = self.evidence_scope_resolver(invocation, 'decisions.get')
        if type(scope) is not EvidenceScope:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        return OriginalReviewJobEvidence(self.evidence, scope,
                                         job_document_max_bytes=self.job_document_max_bytes)

    async def run(self, request, context, claim_guard):
        settings = DecisionsSettings(DecisionRunner, self.evidence,
            _GuardedProvider(self.decision_provider, claim_guard),
            _CollectSourceAnswers(request.questions), host_limits=self.host_limits,
            job_document_max_bytes=self.job_document_max_bytes)
        capability = build_capability(settings, invocation_resolver=self.invocation_resolver,
                                      evidence_scope_resolver=self.evidence_scope_resolver)
        return await capability.handlers['decisions.run']({'job': request.to_job()},
            self._context(context, request.request_id))

    async def read_history(self, run_id):
        from ordessa_decision.historical.reader import FileEvidenceReader
        from ordessa_decision.historical.context import ReadContext
        if (type(self.historical_reader) is not FileEvidenceReader
                or type(self.historical_read_context) is not ReadContext):
            raise ApplicationError('REVIEW_SOURCE_UNAVAILABLE')
        return await self.historical_reader.read(run_id, self.historical_read_context)
