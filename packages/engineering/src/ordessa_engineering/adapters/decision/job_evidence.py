"""Read original decision-job results for the existing Engineering verifier.

This is a data proof, not reviewer admission. The host must retain the original
MethodControl/trust guards around its use. It neither executes a job nor repairs
an unresolved request, and has no model, write or approval operation.
"""
from dataclasses import dataclass

from decision_runtime import DecisionAnswer, DecisionQuestion, FilesystemEvidenceStore, check_summary
from decision_runtime.definitions.values import digest_hex, job_document_bound
from decision_runtime.evidence import EvidenceScope

from ...application.contracts.errors import ApplicationError


@dataclass(frozen=True)
class OriginalReviewAnswers:
    operation_ref: str
    evidence_digest: str
    answers: tuple[DecisionAnswer, ...]


class OriginalReviewJobEvidence:
    def __init__(self, owner, scope, *, job_document_max_bytes=None):
        if type(owner) is not FilesystemEvidenceStore or type(scope) is not EvidenceScope:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        self._store = owner.scoped(scope)
        self._document_bound = job_document_bound(job_document_max_bytes)

    def read(self, request_id, job, questions, *, provider_binding, provider_settings, allow_ties=False):
        """Bind the original persisted result, summary and full answer projections.

        The producer must pin its explicit provider selection in the job input.
        Checking only an unbound summary or a caller-supplied answer is insufficient.
        """
        if type(allow_ties) is not bool:
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        questions = tuple(questions)
        if (not questions or any(type(q) is not DecisionQuestion for q in questions)
                or len({q.question_id for q in questions}) != len(questions)
                or type(provider_binding) is not str or not provider_binding
                or type(provider_settings) is not str or not provider_settings):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        try:
            if job['input']['review_provider'] != {
                    'binding_ref': provider_binding, 'settings_digest': provider_settings}:
                raise ValueError()
            asks = [s for s in job['steps'] if s['type'] == 'ask']
            if [s['id'] for s in asks] != [q.question_id for q in questions]:
                raise ValueError()
            for step, question in zip(asks, questions):
                projected = question.projection()
                expected = {key: projected[key] for key in (
                    'kind', 'version', 'options', 'scale', 'evidence_ids',
                    'allowed_answer_ids', 'bounded_state', 'policy_ref')}
                expected['text'] = projected['question_text']
                if step['payload'] != {'question': expected}:
                    raise ValueError()
            operation, recorded = self._store.read_run(
                request_id, digest_hex({'job': job, 'dryRun': False}, maximum=self._document_bound))
        except Exception:
            raise ApplicationError('REVIEW_SOURCE_UNAVAILABLE') from None
        if recorded is None or recorded.get('status') != 'completed':
            error = ApplicationError('DECISION_REVIEW_NOT_COMPLETED', retry='reconcile')
            error.decision_run_id = operation
            error.decision_status = 'unknown' if recorded is None else recorded.get('status')
            raise error
        try:
            if (set(recorded) != {'status', 'data', 'error', 'operationRef', 'evidenceRefs'}
                    or recorded['operationRef'] != operation or recorded['error'] is not None):
                raise ValueError()
            data = recorded['data']
            if set(data) != {'result', 'evidence'}:
                raise ValueError()
            digest = data['evidence']['digest']
            summary = check_summary(self._store.get(digest))
            projections = data['result']
            if (type(projections) is not list or len(projections) != len(questions)
                    or recorded['evidenceRefs'] != ['sha256:' + digest]
                    or summary['job_digest'] != digest_hex(job, maximum=self._document_bound)
                    or summary['input_digest'] != digest_hex(job['input'], maximum=self._document_bound)
                    or summary['result_digest'] != digest_hex(projections)
                    or summary['skipped']):
                raise ValueError()
            answers = []
            for question, projection in zip(questions, projections):
                if (type(projection) is not dict or set(projection) != {
                        'schema_version', 'question_id', 'kind', 'value',
                        'provider_receipt', 'usage_evidence'}
                        or projection['schema_version'] != 'decision-answer/1'):
                    raise ValueError()
                answer = DecisionAnswer(projection['question_id'], projection['kind'],
                    projection['value'], projection['provider_receipt'], projection['usage_evidence'])
                receipt = answer.provider_receipt
                tied = receipt.get('tied_option_ids') or ()
                valid_tie = (allow_ties and answer.value is None
                    and receipt.get('selection_status') == 'tie'
                    and type(tied) in (list, tuple) and all(type(item) is str for item in tied)
                    and len(tied) >= 2 and len(set(tied)) == len(tied)
                    and set(tied) <= set(question.options))
                if (answer.question_id != question.question_id or answer.kind != 'choice'
                        or (answer.value not in question.options and not valid_tie)
                        or receipt.get('question_digest') != question.question_digest
                        or receipt.get('provider_settings_digest') != provider_settings
                        or summary['answers'].get(question.question_id) != answer.answer_digest
                        or summary['receipt'].get(question.question_id) != receipt
                        or summary['usage'].get(question.question_id) != answer.usage_evidence
                        or summary['steps'].get(question.question_id) != digest_hex({
                            'type': 'ask', 'question': question.question_digest,
                            'answer': answer.answer_digest})):
                    raise ValueError()
                answers.append(answer)
            ids = {q.question_id for q in questions}
            if any(set(summary[key]) != ids for key in ('answers', 'receipt', 'usage')):
                raise ValueError()
        except Exception:
            raise ApplicationError('REVIEW_SOURCE_INVALID') from None
        return OriginalReviewAnswers(operation, digest, tuple(answers))
