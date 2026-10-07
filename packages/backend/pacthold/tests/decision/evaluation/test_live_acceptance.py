"""Real graph/gateway/SDK with fake HTTP. No live model or private credential."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path

import httpx2
import pytest
from pacthold.decision.contracts import DecisionQuestion, DecisionAnswer, PolicyRef, TaskBrief, digest, plain
from pacthold.decision.flows.agent_assignment.task_gate import load_task_gate_policy

SOURCE = Path(__file__).resolve().parents[3] / 'decision-tooling' / 'evaluation' / 'live_acceptance.py'
SPEC = importlib.util.spec_from_file_location('decision_live_acceptance', SOURCE)
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


def plan():
    policy = plain(load_task_gate_policy())
    ref = PolicyRef(policy['policy_id'], policy['version'], digest('policy', policy))
    question = DecisionQuestion('q', '1', 'choice', {'synthetic': 'finite'},
        'Choose a', options={'a': 'suitable', 'b': 'unsuitable'}, policy_ref=ref)
    return {'version': 'jev-live-acceptance/1', 'scope_id': 'offline-scope', 'synthetic_only': True,
        'settings': {'binding_ref': 'offline-zen', 'secret_ref': 'offline-key', 'base_url': 'https://opencode.ai/zen',
            'model': 'jev-1.13-free', 'accepted_response_models': ['jev-1.13-free'], 'timeout_seconds': 2},
        'task_gate_policy': policy, 'policy_refs': [plain(ref)],
        'limits': {'max_http_requests': 1, 'wall_timeout_seconds': 5, 'case_timeout_seconds': 4},
        'cases': [{'id': 'finite', 'task': plain(TaskBrief('finite', '1', 'synthetic evaluation')),
            'questions': [plain(question)], 'expected': {'kind': 'choice_expected', 'values': {'q': 'a'}}}]}


def response():
    return httpx2.Response(200, json={'model': 'jev-1.13-free', 'usage': {'input_tokens': 10, 'output_tokens': 2},
        'answers': {'q': {'type': 'choice', 'choice': 'a', 'confidence': 0.8, 'probabilities': {'a': 0.8, 'b': 0.2}}}})


@pytest.mark.asyncio
async def test_illegal_capacity_never_reads_credential(tmp_path, monkeypatch):
    data = plan()
    data['cases'][0]['questions'][0]['options'] = {str(i): 'candidate' for i in range(64)} | {'refuse': 'no', 'need_info': 'unknown'}
    reads = []
    def forbidden(path, *args, **kwargs):
        reads.append(str(path)); raise AssertionError('must not read')
    monkeypatch.setattr(Path, 'read_text', forbidden)
    with pytest.raises(live.EvaluationError, match='plan_invalid'):
        await live.run_plan(data, tmp_path / 'out', tmp_path / 'key', True, ledger_path=tmp_path / 'ledger')
    assert reads == []


@pytest.mark.asyncio
async def test_real_graph_answer_survives_terminal_collection_failure(tmp_path):
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    async def reject(*args): raise RuntimeError('hostile exception never recorded')
    result = await live.run_plan(plan(), tmp_path / 'out', key, True, ledger_path=tmp_path / 'ledger',
        transport=httpx2.MockTransport(lambda request: response()), terminal_verifier=reject)
    retained = json.loads((tmp_path / 'out' / 'receipt.json').read_text())
    assert result['status'] == 'PARTIAL'
    assert retained['rows'][0]['answers'][0]['value'] == 'a'
    assert retained['rows'][0]['technical_status'] == 'COLLECTION_FAILED'
    assert retained['rows'][0]['quality_pass'] is False
    assert retained['transport_attempts'] == 1 and retained['actual_http_requests'] == 0
    assert 'hostile' not in json.dumps(retained)
    assert list((tmp_path / 'out' / 'durable').glob('*/terminal.json'))


@pytest.mark.asyncio
async def test_http_claim_persists_and_reexecution_preserves_receipt(tmp_path):
    data = plan(); key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    calls = []
    def handler(request): calls.append(request); return response()
    result = await live.run_plan(data, tmp_path / 'out', key, True, ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(handler))
    assert result['status'] == 'SCOPED_PASS' and result['controlled_label_matches'] == 1
    assert result['model_quality_passes'] == result['real_model_requests'] == 0
    assert result['evaluation_mode'] == 'injected_test_transport'
    assert result['credential_reads'] == 1
    original = (tmp_path / 'out' / 'receipt.json').read_bytes()
    with pytest.raises(live.EvaluationError, match='case_already_claimed'):
        await live.run_plan(data, tmp_path / 'out', key, True, ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(handler))
    assert len(calls) == 1 and (tmp_path / 'out' / 'receipt.json').read_bytes() == original
    ledger = live.ScopeLedger(tmp_path / 'ledger', data)
    try:
        with pytest.raises(live.EvaluationError, match='http_limit'): ledger.claim('another-case')
    finally: ledger.close()


@pytest.mark.asyncio
async def test_cancelled_http_remains_unknown_and_not_replayed(tmp_path):
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only'); entered = asyncio.Event()
    async def handler(request):
        entered.set(); await asyncio.Event().wait()
    task = asyncio.create_task(live.run_plan(plan(), tmp_path / 'out', key, True,
        ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(handler)))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    retained = json.loads((tmp_path / 'out' / 'receipt.json').read_text())
    assert retained['status'] == 'PARTIAL' and retained['transport_attempts'] == 1 and retained['actual_http_requests'] == 0
    assert retained['http_audit'][0]['status'] == 'CANCELLED_UNKNOWN'
    assert retained['rows'][0]['quality_pass'] is False
    assert retained['usage_unknown_requests'] == 1


def test_incomplete_answers_never_score_pass():
    data = plan(); _, _, cases = live.validate(data)
    case, _, questions, gate = cases[0]
    with pytest.raises(live.EvaluationError, match='answer_set_invalid'): live.score(case, questions, (), gate)
    wrong = DecisionAnswer('different', 'choice', 'a', {})
    with pytest.raises(live.EvaluationError, match='answer_set_invalid'): live.score(case, questions, (wrong,), gate)


def test_output_domain_and_profile_are_closed():
    for mutate in ('label', 'model', 'endpoint'):
        data = copy.deepcopy(plan())
        if mutate == 'label': data['cases'][0]['expected']['values']['q'] = 'noDelegation'
        elif mutate == 'model': data['settings']['accepted_response_models'] = ['paid-model']
        else: data['settings']['base_url'] = 'https://another.example'
        with pytest.raises(live.EvaluationError, match='plan_invalid'): live.prepare(data)


@pytest.mark.asyncio
async def test_protocol_diagnostic_survives_graph_failure_without_raw_body(tmp_path):
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    marker = 'private-error-body-marker'
    def malformed(request):
        value = response().json()
        value['answers']['q']['probabilities'] = {'a': 0.8, marker: 0.2}
        return httpx2.Response(200, json=value)
    result = await live.run_plan(plan(), tmp_path / 'out', key, True,
        ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(malformed))
    row = result['rows'][0]
    assert row['technical_status'] == 'failed' and row['terminal_verified']
    assert row['provider_error'] == 'protocol_invalid' and row['protocol_diagnostic'] == 'probability_keys'
    assert row['answers'] == [] and not row['quality_pass']
    assert result['actual_http_requests'] == result['model_quality_passes'] == 0
    assert result['transport_attempts'] == 1
    for path in (tmp_path / 'out').rglob('*'):
        if path.is_file(): assert marker.encode() not in path.read_bytes()
