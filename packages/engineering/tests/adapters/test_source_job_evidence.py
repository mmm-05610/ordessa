"""Actual Decision claim/result/summary readback; controlled provider only."""
import asyncio
from types import SimpleNamespace

import pytest
from decision_runtime import DecisionAnswer, DecisionQuestion, DecisionRunner, FilesystemEvidenceStore, RulesOutcome
from decision_runtime.capability import build_capability
from decision_runtime.definitions.values import digest_hex
from decision_runtime.evidence import EvidenceScope
from decision_runtime.settings import DecisionsSettings

from ordessa_engineering.adapters.decision.job_evidence import OriginalReviewJobEvidence
from ordessa_engineering.application.contracts.errors import ApplicationError


class Provider:
    binding_ref = 'explicit-controlled-review-provider'
    settings_digest = 'sha256:' + 'd' * 64

    def __init__(self, unknown=False):
        self.calls, self.unknown = 0, unknown

    async def decide(self, question, context):
        self.calls += 1
        context.claim(question, self.settings_digest)
        if self.unknown:
            raise TimeoutError('controlled unresolved response')
        choice = next(iter(question.options))
        return DecisionAnswer(question.question_id, 'choice', choice, {
            'selection_status': 'unique', 'probabilities': {key: float(key == choice) for key in question.options},
            'resolved_model': 'controlled', 'requested_model': 'controlled',
            'protocol_validation_version': 'controlled/1',
            'question_digest': question.question_digest,
            'provider_settings_digest': self.settings_digest}, {'status': 'reported'})


class Collect:
    engine_id = 'engineering-original-review-answer-collection/1'

    def validate(self, payload):
        assert payload == {'collect': ['one', 'two']}

    def evaluate(self, payload, facts):
        return RulesOutcome(values={'answers': [DecisionAnswer(key, 'choice',
            facts[key]['answer'], facts[key]['receipt'], facts[key]['usage']).projection()
            for key in payload['collect']]}, disposition='passed')

    def close(self):
        pass


class MisstatedCollection(Collect):
    def evaluate(self, payload, facts):
        result = super().evaluate(payload, facts)
        answers = [dict(answer) for answer in result.values['answers']]
        answers[0]['value'] = 'not_passed'
        return RulesOutcome(values={'answers': answers}, disposition='passed')


def setup(tmp_path, *, unknown=False, collection=None, options=None):
    provider = Provider(unknown)
    owner, scope = FilesystemEvidenceStore(tmp_path), EvidenceScope('principal', 'original-principal-method')
    capability = build_capability(DecisionsSettings(DecisionRunner, owner, provider, collection or Collect()),
        invocation_resolver=lambda context: context, evidence_scope_resolver=lambda *_: scope)
    questions = tuple(DecisionQuestion(key, '1', 'choice', {'request_version': 3, 'fence': 7},
        'Review exact captured source', options=options or {'passed': 'supported', 'not_passed': 'unsupported'},
        allowed_answer_ids=tuple(options or ('passed', 'not_passed'))) for key in ('one', 'two'))
    steps = []
    for question in questions:
        projection = question.projection()
        payload = {key: projection[key] for key in ('kind', 'version', 'options', 'scale',
            'evidence_ids', 'allowed_answer_ids', 'bounded_state', 'policy_ref')}
        payload['text'] = projection['question_text']
        steps.append({'id': question.question_id, 'type': 'ask', 'engine': None,
            'when': {'fact': 'input.run', 'op': 'eq', 'value': True}, 'payload': {'question': payload}})
    steps.append({'id': 'collect', 'type': 'rules', 'engine': None,
        'when': {'fact': 'input.run', 'op': 'eq', 'value': True}, 'payload': {'collect': ['one', 'two']}})
    job = {'spec_version': 'decision-job/1', 'job_id': 'original-review-fence7', 'version': 3,
        'input': {'run': True, 'review_provider': {'binding_ref': provider.binding_ref,
            'settings_digest': provider.settings_digest}}, 'steps': steps,
        'limits': {'max_model_calls': 2, 'max_steps': 3, 'max_value_bytes': 8192, 'timeout_seconds': 2.0},
        'result': {'from': 'collect', 'path': ['values', 'answers']}}
    return provider, owner, scope, capability, questions, job


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def read(reader, provider, job, questions):
    return reader.read('original-review-request', job, questions,
        provider_binding=provider.binding_ref, provider_settings=provider.settings_digest)


@pytest.mark.parametrize('unknown', [False, True])
def test_original_answers_or_unknown_are_read_without_execution_or_writes(tmp_path, unknown):
    provider, owner, scope, capability, questions, job = setup(tmp_path, unknown=unknown)
    result = asyncio.run(capability.handlers['decisions.run']({'job': job},
        SimpleNamespace(request_id='original-review-request')))
    reader = OriginalReviewJobEvidence(owner, scope)
    before = snapshot(tmp_path)
    if unknown:
        for _ in range(2):
            with pytest.raises(ApplicationError) as caught:
                read(reader, provider, job, questions)
            assert caught.value.code == 'DECISION_REVIEW_NOT_COMPLETED'
            assert caught.value.retry == 'reconcile'
            assert caught.value.decision_status == 'unknown'
        assert provider.calls == 1
    else:
        verified = read(reader, provider, job, questions)
        assert verified.operation_ref == result.operation_ref
        assert [answer.question_id for answer in verified.answers] == ['one', 'two']
        assert [answer.value for answer in verified.answers] == ['passed', 'passed']
        assert read(reader, provider, job, questions) == verified
        assert provider.calls == 2
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('change', ['provider', 'questions', 'scope', 'pending'])
def test_foreign_or_incomplete_proofs_cannot_be_accepted_or_repaired(tmp_path, change):
    provider, owner, scope, capability, questions, job = setup(tmp_path)
    if change == 'pending':
        owner.scoped(scope).claim_run('original-review-request', digest_hex({'job': job, 'dryRun': False}))
    else:
        asyncio.run(capability.handlers['decisions.run']({'job': job},
            SimpleNamespace(request_id='original-review-request')))
    if change == 'provider':
        provider.binding_ref = 'different-provider'
    if change == 'questions':
        questions = tuple(reversed(questions))
    if change == 'scope':
        scope = EvidenceScope('principal', 'foreign-method')
    reader = OriginalReviewJobEvidence(owner, scope)
    before, calls = snapshot(tmp_path), provider.calls
    with pytest.raises(ApplicationError):
        read(reader, provider, job, questions)
    assert provider.calls == calls
    assert snapshot(tmp_path) == before


def test_completed_rules_result_cannot_replace_the_original_model_answer(tmp_path):
    provider, owner, scope, capability, questions, job = setup(tmp_path, collection=MisstatedCollection())
    result = asyncio.run(capability.handlers['decisions.run']({'job': job},
        SimpleNamespace(request_id='original-review-request')))
    assert result.status == 'completed'
    before = snapshot(tmp_path)
    with pytest.raises(ApplicationError) as caught:
        read(OriginalReviewJobEvidence(owner, scope), provider, job, questions)
    assert caught.value.code == 'REVIEW_SOURCE_INVALID'
    assert provider.calls == 2
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('tied', ['ab', ['a', 1]])
def test_profile_tie_rejects_wrong_type_even_when_all_proof_hashes_match(tmp_path, tied):
    import json
    from decision_runtime.definitions.values import canonical_bytes
    provider, owner, scope, capability, questions, job = setup(tmp_path, options={'a':'one','b':'two'})
    result = asyncio.run(capability.handlers['decisions.run']({'job': job},
        SimpleNamespace(request_id='original-review-request')))
    assert result.status == 'completed'
    store = owner.scoped(scope)
    operation, recorded = store.read_run('original-review-request', digest_hex({'job':job,'dryRun':False}))
    summary = store.get(recorded['data']['evidence']['digest'])
    for question, projection in zip(questions, recorded['data']['result']):
        projection['value'] = None
        projection['provider_receipt'].update(selection_status='tie', tied_option_ids=tied)
        answer = DecisionAnswer(question.question_id, 'choice', None,
            projection['provider_receipt'], projection['usage_evidence'])
        summary['answers'][question.question_id] = answer.answer_digest
        summary['receipt'][question.question_id] = projection['provider_receipt']
        summary['steps'][question.question_id] = digest_hex({'type':'ask',
            'question':question.question_digest,'answer':answer.answer_digest})
    summary['result_digest'] = digest_hex(recorded['data']['result'])
    evidence = store.put(summary)
    recorded['data']['evidence']['digest'] = evidence.digest
    recorded['evidenceRefs'] = ['sha256:'+evidence.digest]
    path = next(tmp_path.rglob('.run-result-*.json'))
    envelope = json.loads(path.read_text())
    envelope['result'] = recorded
    envelope['resultDigest'] = digest_hex(recorded)
    path.write_bytes(canonical_bytes(envelope))
    # All store-level hashes are valid: the reader must reject receipt semantics.
    assert store.read_run('original-review-request', digest_hex({'job':job,'dryRun':False}))[0] == operation
    before = snapshot(tmp_path)
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_INVALID'):
        OriginalReviewJobEvidence(owner, scope).read('original-review-request', job, questions,
            provider_binding=provider.binding_ref, provider_settings=provider.settings_digest, allow_ties=True)
    assert provider.calls == 2
    assert snapshot(tmp_path) == before
