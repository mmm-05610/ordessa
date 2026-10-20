"""Source-level provenance checks for the public Decision evidence projection."""
from copy import deepcopy
from contextlib import contextmanager
import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from decision_runtime.historical.models import (
    BusinessOutcome, DecisionAnswer, DecisionQuestion, DecisionRequest,
    DecisionResult, FlowRef, PolicyRef, RunLimits, RunManifest, TaskBrief,
)
from decision_runtime import DecisionAnswer as CurrentAnswer, DecisionQuestion as CurrentQuestion, FilesystemEvidenceStore
from decision_runtime.evidence import EvidenceScope
from ordessa_engineering.adapters.decision.source_job import (
    SourceReviewJobServices, SourceReviewRequest, SourceReviewTask,
)

from ordessa_engineering.adapters.decision import source_reviewer
from ordessa_engineering.adapters.decision.source_reviewer import (
    DecisionReviewerSource, _verified_native_result,
)
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.models import ReviewRequestState


RUN_ID = 'controlled-decision-run'
PROVIDER_BINDING = 'controlled-provider/1'
POLICY = PolicyRef('source-review', '1', 'sha256:' + 'a' * 64)
FLOW_REF = FlowRef('source-review-flow', '1', 'sha256:' + 'b' * 64)


def _evidence():
    flow = SimpleNamespace(ref=FLOW_REF, policy_refs=(POLICY,))
    request = DecisionRequest('source-review-request',
        TaskBrief('source-review-task', '7', 'Review the pinned source.'),
        FLOW_REF, RunLimits(max_model_attempts=1, max_node_entries=1))
    manifest = RunManifest(request.request_digest, FLOW_REF, flow.policy_refs,
        request.limits, PROVIDER_BINDING)
    result = DecisionResult(RUN_ID, request.request_id, request.task.task_revision,
        FLOW_REF, manifest.manifest_digest, flow.policy_refs, 'completed',
        outcome=BusinessOutcome('revise', issues=({'code': 'source-review-answer'},)),
        call_evidence='recorded')
    native = {
        'status': 'completed',
        'call_evidence': 'recorded',
        'events': ({'payload': {
            'type': 'run.started', 'run_id': RUN_ID,
            'request_digest': request.request_digest,
            'flow_digest': FLOW_REF.content_digest,
            'manifest_digest': manifest.manifest_digest,
        }},),
        'terminal': {
            'run_id': RUN_ID, 'status': 'completed',
            'result': result.to_dict(), 'terminal_digest': result.result_digest,
        },
    }
    return native, request, flow


def test_native_projection_is_bound_to_request_manifest_and_provider():
    native, request, flow = _evidence()

    result = _verified_native_result(native, RUN_ID, request, flow, PROVIDER_BINDING)

    assert result.request_id == request.request_id
    assert result.run_manifest_digest == native['events'][0]['payload']['manifest_digest']
    assert native['status'] == 'completed'
    assert native['terminal']['result']['run_manifest_digest'] == native['events'][0]['payload']['manifest_digest']


@pytest.mark.parametrize('mutation', ('start_manifest', 'terminal_run', 'terminal_request',
                                      'terminal_flow', 'terminal_policy', 'terminal_digest',
                                      'provider_binding'))
def test_native_projection_rejects_manifest_or_result_provenance_mismatch(mutation):
    native, request, flow = _evidence()
    native = deepcopy(native)
    if mutation == 'start_manifest':
        native['events'][0]['payload']['manifest_digest'] = 'sha256:' + 'c' * 64
    elif mutation == 'terminal_run':
        native['terminal']['result']['run_id'] = 'another-run'
    elif mutation == 'terminal_request':
        native['terminal']['result']['request_id'] = 'another-request'
    elif mutation == 'terminal_flow':
        native['terminal']['result']['flow_ref']['content_digest'] = 'sha256:' + 'c' * 64
    elif mutation == 'terminal_policy':
        native['terminal']['result']['effective_policy_refs'][0]['content_digest'] = 'sha256:' + 'c' * 64
    elif mutation == 'terminal_digest':
        native['terminal']['terminal_digest'] = 'sha256:' + 'c' * 64

    binding = 'substituted-provider/1' if mutation == 'provider_binding' else PROVIDER_BINDING
    with pytest.raises(ApplicationError) as raised:
        _verified_native_result(native, RUN_ID, request, flow, binding)
    assert raised.value.code == 'REVIEW_SOURCE_INVALID'


@pytest.mark.parametrize('receipt_mismatch',
    (None, 'question_digest', 'provider_settings_digest'))
def test_adapter_run_review_and_verify_response_use_original_durable_run(
        tmp_path, monkeypatch, receipt_mismatch):
    """Controlled provider, real native runner and filesystem evidence; no network/model."""
    scope = Scope('decision-source-realm', 'decision-source-project')
    context = CommandContext(scope, 'decision-source-principal',
        ActorRef('decision-source-actor', 'service', 'decision-source-issuer'),
        'decision-source-command', '2026-10-14T00:00:00.000000Z', 'decision-source-trace')
    evidence_root = tmp_path / 'native-evidence'
    owner = FilesystemEvidenceStore(evidence_root)
    evidence_scope = EvidenceScope('principal', 'engineering-decision-source-test')

    class ControlledProvider:
        binding_ref = 'controlled-decision-review-provider/1'
        settings_digest = 'sha256:' + 'd' * 64
        calls = 0

        async def decide(self, question, invocation):
            self.calls += 1
            invocation.claim(question, self.settings_digest)
            provider_receipt = {'selection_status': 'unique', 'probabilities': {'pass': .9, 'fail': .1},
                'resolved_model': 'controlled', 'requested_model': 'controlled',
                'protocol_validation_version': 'controlled/1',
                'question_digest': question.question_digest,
                'provider_settings_digest': self.settings_digest}
            if receipt_mismatch == 'question_digest':
                provider_receipt['question_digest'] = 'sha256:' + 'c' * 64
            elif receipt_mismatch == 'provider_settings_digest':
                provider_receipt['provider_settings_digest'] = 'sha256:' + 'c' * 64
            return CurrentAnswer(question.question_id, 'choice', 'pass', provider_receipt)

    provider = ControlledProvider()
    services = SourceReviewJobServices(provider, owner, lambda ctx: ctx,
        lambda *_: evidence_scope, lambda ctx, request_id: __import__('dataclasses').replace(ctx, request_id=request_id))
    question = CurrentQuestion('source-review-criterion', '1', 'choice',
        {'pinned_input': 'sha256:' + 'e' * 64}, 'Choose the controlled result.',
        options={'pass': 'Pass', 'fail': 'Fail'}, allowed_answer_ids=('pass', 'fail'))
    request = SourceReviewRequest('review-request-version-zero',
        SourceReviewTask('review-request-version-zero', '0', 'Review the pinned source.',
            inputs=({'pinned_input': 'sha256:' + 'e' * 64},)), (question,), (),
        provider.binding_ref, provider.settings_digest, 5.0)
    job = request.to_job()
    selected = {'policy': {'reviewer_roles': ('reviewer',),
                           'options': {'pass': {'status': 'satisfied'},
                                       'fail': {'status': 'violated'}}},
                'standard': object()}
    plan = SimpleNamespace(review_id='decision-source-review',
        request_digest=Digest('sha256', 'f' * 64), check_keys=(),
        requirement=SimpleNamespace(method_ref='controlled-method-ref'))
    request_state = ReviewRequestState(scope, plan.review_id, 'requested', 1, 0)

    class Guard:
        @contextmanager
        def guard(self, *_args):
            yield

    class Bindings:
        def __init__(self, factory):
            self.factory = factory

        def review_inputs(self, *_args):
            return selected

    class Blobs:
        def __init__(self, library):
            self.library = library
            self.data = {}

        def put_verified(self, raw, expected_digest, media_type):
            actual = Digest('sha256', hashlib.sha256(raw).hexdigest())
            assert actual == expected_digest
            ref = BlobRef(actual, len(raw), media_type, 'decision-source-response')
            self.data[actual.hex] = raw
            return ref

        def read_verified(self, ref):
            return self.data[ref.digest.hex]

    library = object()
    @contextmanager
    def begin(*_args):
        yield SimpleNamespace(reviews=SimpleNamespace(get_request=lambda *_: request_state,
                                                      get_plan=lambda *_: plan))
    factory = SimpleNamespace(library=library, begin=begin)
    blobs, guard = Blobs(library), Guard()
    guard.factory = factory
    source = DecisionReviewerSource(factory, blobs, guard,
        SimpleNamespace(factory=factory), Bindings(factory), scope=scope,
        principal_id=context.principal_id,
        reviewer=ActorRef('decision-source-reviewer', 'service', 'decision-source-issuer'),
        roles=('reviewer',), services=services)

    def controlled_inputs(input_context, *_args):
        source._check(input_context)
        # Mirror the real _inputs contract: the questions element is a tuple.
        return selected, (question,), job, request

    source._inputs = controlled_inputs
    monkeypatch.setattr(source_reviewer, 'review_observations', lambda *_args: ())

    try:
        if receipt_mismatch is not None:
            # Current Decision validates provider identity at the original call
            # boundary, earlier than the old permissive runner. Preserve the
            # refusal invariant and prove UNKNOWN cannot publish/re-send.
            for _ in range(2):
                with pytest.raises(ApplicationError) as raised:
                    asyncio.run(source.run_review(context, plan, request_state))
                assert raised.value.code == 'DECISION_REVIEW_NOT_COMPLETED'
                assert raised.value.decision_status == 'unknown'
            assert provider.calls == 1 and blobs.data == {}
        else:
            raw_ref = asyncio.run(source.run_review(context, plan, request_state))
            receipt = json.loads(blobs.read_verified(raw_ref))
            assert receipt['request_version'] == 0 and receipt['fence'] == 1
            verified = source.verify_response(context, plan, request_state, raw_ref,
                                              standard=selected['standard'])
            assert verified.reviewer_evidence.request_digest == plan.request_digest
            assert verified.reviewer_evidence.trust_version == source.trust_version
            native = services.reader(context, request.request_id).read(request.request_id, job, (question,),
                provider_binding=provider.binding_ref, provider_settings=provider.settings_digest)
            assert native.operation_ref == receipt['run_id']
        if receipt_mismatch is None:
            source.roles = ('changed-reviewer-role',)
            with pytest.raises(ApplicationError, match='UNTRUSTED_REVIEWER'):
                source.verify_response(context, plan, request_state, raw_ref,
                                       standard=selected['standard'])
            source.roles = ('reviewer',)
            source.trust_version += 1
            with pytest.raises(ApplicationError, match='UNTRUSTED_REVIEWER'):
                source.verify_response(context, plan, request_state, raw_ref,
                                       standard=selected['standard'])
    finally:
        source.close()
