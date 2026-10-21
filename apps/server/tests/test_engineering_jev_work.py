"""Original-authority pending JEV preparation/capture qualification fixture.

The helper supplies a valid frozen 2.3 DID document and controlled source
captures. Provider traffic in these tests is limited to httpx MockTransport;
this does not qualify a real model or authenticate a human grant.
"""
import asyncio
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path

import httpx2
import pytest

from ordessa_decision.definitions import PolicyRef, ReadContext, digest
from ordessa_decision.evidence import FileEvidenceSink
from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.reviews.target_codec import decode_subject_ref
from ordessa_server.composition.engineering_reviewer_source import (
    OriginalJevReviewerSource, encode_review_run,
)


_FIXTURE_PATH = Path(__file__).resolve().parents[3] / 'tests/fixtures/engineering/jev_pending_work.py'
_FIXTURE_SPEC = importlib.util.spec_from_file_location('ordessa_jev_pending_work_fixture', _FIXTURE_PATH)
if _FIXTURE_SPEC is None or _FIXTURE_SPEC.loader is None:
    raise RuntimeError('JEV pending work fixture is unavailable')
_FIXTURE_MODULE = importlib.util.module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(_FIXTURE_MODULE)
build_original_pending_work = _FIXTURE_MODULE.build_original_pending_work


@pytest.fixture
def pending_work(tmp_path):
    work = build_original_pending_work(tmp_path / 'jev-pending-work')
    try:
        yield work
    finally:
        work['library'].close()


def _mock_provider(calls):
    def handle(request):
        payload = json.loads(request.content)
        calls.append(payload)
        question_id = next(iter(payload['questions']))
        choices = ('supported', 'contradicted', 'insufficient')
        probabilities = {item: (1 if item == 'supported' else 0) for item in choices}
        return httpx2.Response(200, json={'model': 'jev-1.13.0', 'usage': {},
            'answers': {question_id: {'type': 'choice', 'choice': 'supported',
                'confidence': 1, 'probabilities': probabilities}}})
    return JevDecisionProvider(JevProviderSettings(binding_ref='controlled-pending-work'),
        secret_resolver=lambda _: 'mock-transport-only', transport=httpx2.MockTransport(handle))


def _policy(plan):
    return PolicyRef('controlled.pending-jev-policy', '1',
        digest('policy', {'requirement': plan.requirement.digest.hex}))


def test_original_work_captures_pending_evidence_and_refuses_formal_record(pending_work, tmp_path):
    work = pending_work
    calls = []
    provider = _mock_provider(calls)
    read_context = ReadContext(object(), 'controlled-pending-work-reader')
    evidence_root = tmp_path / 'durable-evidence'
    evidence_root.mkdir(mode=0o700)
    sink = FileEvidenceSink(evidence_root, read_context=read_context)
    try:
        with work['admitted']('engineering.reviewer.jev', 'prepare') as context:
            prepared = work['work'].prepare(context, work['plan'].review_id, _policy(work['plan']))
        assert work['request'].state == 'requested'
        assert len(prepared.questions) == 1
        assert prepared.questions[0].input_digest
        assert prepared.questions[0].input_truncated is False

        with work['admitted']('engineering.reviewer.jev', 'run') as context:
            run, flow, result = asyncio.run(work['work'].run(context, prepared,
                provider=provider, evidence_sink=sink, read_context=read_context,
                request_id='controlled-pending-work-decision-run', task_revision='1',
                review_ref='controlled-pending-work-source'))
        source = OriginalJevReviewerSource(access=work['access'],
            scope=work['server_scope'], blobs=work['blobs'], evidence_reader=sink,
            read_context=read_context, provider=provider, runs=(run,),
            roles=('reviewer',), accepted_models=('jev-1.13.0',), flows=(flow,))
        work['admission'].source = source

        with work['admitted']('engineering.artifacts.create', 'capture') as context:
            captured = work['work'].capture(context, prepared, run, source=source)
        assert captured.status == 'completed'
        revision_ref = decode_subject_ref(captured.result['revision_ref'])
        assert type(revision_ref) is ArtifactRevisionRef
        with work['factory'].begin(work['plan'].scope, 'read') as uow:
            artifact = uow.engineering.get_artifact(revision_ref.artifact_id)
            revision = uow.engineering.resolve_revision(revision_ref)
            request_after = uow.reviews.get_request(work['plan'].review_id)
        payload = revision.payload.value
        assert artifact.kind == 'other'
        assert payload['observed_review_state'] == 'requested'
        assert payload['request_version'] == work['request'].version
        assert payload['request_fence'] == work['request'].fence
        assert payload['input_receipt_ref']['digest']['hex'] == hashlib.sha256(
            prepared.receipt_bytes).hexdigest()
        assert payload['raw_response_ref']['digest']['hex'] == hashlib.sha256(
            encode_review_run(run)).hexdigest()
        assert len(payload['nominal_results']) == len(prepared.questions)
        assert all(item['quality_disposition'] == 'manual' for item in payload['nominal_results'])
        assert len(payload['unavailable_checks']) == 2
        assert payload['formal_review_record'] is False
        assert request_after.state == 'requested'
        assert request_after.version == work['request'].version
        assert request_after.fence == work['request'].fence
        assert len(calls) == len(prepared.questions)

        # Evidence-only runs cannot be promoted by ReviewUseCases into a
        # formal ReviewRecord; failed recording leaves the owner request intact.
        with work['admitted']('engineering.reviews.record', 'formal-refusal') as context:
            with pytest.raises(ApplicationError, match='REVIEW_SOURCE_INCOMPLETE'):
                work['reviews'].record_response(work['plan'].review_id,
                    encode_review_run(run), context,
                    expected_request_version=work['request'].version,
                    fence=work['request'].fence)
        with work['factory'].begin(work['plan'].scope, 'read') as uow:
            request_after_refusal = uow.reviews.get_request(work['plan'].review_id)
        assert request_after_refusal.state == 'requested'
        assert request_after_refusal.version == work['request'].version
        assert request_after_refusal.fence == work['request'].fence
    finally:
        asyncio.run(provider.close())
        asyncio.run(sink.close())


@pytest.mark.parametrize('mutation,code', [
    ('receipt', 'REVIEW_REQUEST_CHANGED'),
    ('question-digest', 'REVIEW_REQUEST_CHANGED'),
    ('request-version', 'REVIEW_REQUEST_CHANGED'),
])
def test_original_work_refuses_stale_request_or_frozen_input_before_provider(
        pending_work, tmp_path, mutation, code):
    work = pending_work
    calls = []
    provider = _mock_provider(calls)
    read_context = ReadContext(object(), 'controlled-pending-negative-reader')
    evidence_root = tmp_path / 'durable-evidence'
    evidence_root.mkdir(mode=0o700)
    sink = FileEvidenceSink(evidence_root, read_context=read_context)
    try:
        with work['admitted']('engineering.reviewer.jev', 'prepare-negative') as context:
            prepared = work['work'].prepare(context, work['plan'].review_id, _policy(work['plan']))
        if mutation == 'receipt':
            prepared = replace(prepared, receipt_bytes=prepared.receipt_bytes + b' ')
        elif mutation == 'question-digest':
            question = replace(prepared.questions[0], input_digest='sha256:' + '0' * 64)
            prepared = replace(prepared, questions=(question,))
        else:
            prepared = replace(prepared, request=replace(prepared.request,
                version=prepared.request.version + 1))
        with work['admitted']('engineering.reviewer.jev', 'run-negative') as context:
            with pytest.raises(ApplicationError, match=code):
                asyncio.run(work['work'].run(context, prepared,
                    provider=provider, evidence_sink=sink, read_context=read_context,
                    request_id='controlled-pending-negative-decision-run', task_revision='1',
                    review_ref='controlled-pending-work-source'))
        assert calls == []
    finally:
        asyncio.run(provider.close())
        asyncio.run(sink.close())
