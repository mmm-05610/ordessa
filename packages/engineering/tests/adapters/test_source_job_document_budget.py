"""Original full captures reach all eight current asks under an explicit budget."""
import asyncio
from dataclasses import replace

import pytest
from ordessa_decision import DecisionAnswer, FilesystemEvidenceStore, default_host_limits
from ordessa_decision.definitions.values import MAX_JOB_DOCUMENT_BYTES, canonical_bytes
from ordessa_decision.evidence import EvidenceScope
from ordessa_engineering.adapters.decision.source_job import SourceReviewJobServices
from ordessa_engineering.application.contracts.errors import ApplicationError
from test_itemized_source_reviews import _full_input_reviewer


class Provider:
    binding_ref = 'gate-provider/1'
    settings_digest = 'sha256:' + 'd' * 64

    def __init__(self): self.questions = []

    async def decide(self, question, context):
        context.claim(question, self.settings_digest)
        self.questions.append(question)
        return DecisionAnswer(question.question_id, 'choice', 'passed', {
            'selection_status': 'unique', 'probabilities': {key: float(key == 'passed') for key in question.options},
            'resolved_model': 'controlled', 'requested_model': 'controlled',
            'protocol_validation_version': 'controlled/1', 'question_digest': question.question_digest,
            'provider_settings_digest': self.settings_digest})


@pytest.mark.parametrize('explicit', [False, True])
def test_full_capture_document_budget_never_raises_model_or_output_limits(tmp_path, explicit):
    reviewer, context, plan, _, _ = _full_input_reviewer()
    _, questions, job, request = reviewer._inputs(context, plan, 0, 1)
    assert len(canonical_bytes(job, maximum=MAX_JOB_DOCUMENT_BYTES)) > 512 * 1024
    provider = Provider()
    services = SourceReviewJobServices(provider, FilesystemEvidenceStore(tmp_path), lambda ctx: ctx,
        lambda *_: EvidenceScope('principal', 'full-capture-controlled'),
        lambda ctx, request_id: replace(ctx, request_id=request_id),
        host_limits={**default_host_limits(), 'timeout_seconds': 240.0},
        job_document_max_bytes=MAX_JOB_DOCUMENT_BYTES if explicit else None)
    result = asyncio.run(services.run(request, context, lambda: None))
    if not explicit:
        assert result.status == 'refused' and provider.questions == []
        assert list(tmp_path.rglob('.run-[0-9a-f]*.json')) == []
        return
    assert result.status == 'completed'
    assert len(provider.questions) == 8
    for question in provider.questions:
        state = question.bounded_state
        texts = [''.join(state['source_text_blocks'][span['block_id']] for span in source['segments'])
                 for source in state['sources']]
        assert [len(text.encode()) for text in texts] == [142430, 172039]
    proof = services.reader(context, request.request_id).read(request.request_id, job, questions,
        provider_binding=provider.binding_ref, provider_settings=provider.settings_digest)
    assert len(proof.answers) == 8 and proof.operation_ref == result.operation_ref
    assert job['limits']['max_model_calls'] == 8
    assert job['limits']['max_value_bytes'] == 65536
