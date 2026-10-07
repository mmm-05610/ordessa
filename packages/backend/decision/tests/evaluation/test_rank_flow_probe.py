"""Official SDK fake HTTP exercises the original assignment.rank branch."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import httpx2
import pytest
from ordessa_decision.contracts import TaskBrief, plain
from ordessa_decision.flows.agent_assignment.build import load_assignment_policy

SOURCE = Path(__file__).resolve().parents[2] / 'evaluation' / 'rank_flow_probe.py'
SPEC = importlib.util.spec_from_file_location('decision_rank_flow_probe', SOURCE)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def plan(expected='proposal_1'):
    frozen = json.loads(SOURCE.with_name('domain-cases-v2.json').read_text())
    case = next(c for c in frozen['cases'] if c['id'] == 'clear-full')
    policy = plain(load_assignment_policy(task_gate=frozen['task_gate_policy'], task_gate_facts=case['facts']))
    policy['selection']['rank_instructions'] = 'Synthetic preference only: choose the proposal marked preferred. These are controlled fictional metadata, not measured cost or owner capability.'
    candidate, drafts = probe.reference._fixture(TaskBrief.from_dict(case['task']), policy)
    original = drafts[0]
    proposals = tuple(replace(original, proposal_id='synthetic-' + str(i),
        payload={**plain(original.payload), 'synthetic_preference': 'preferred' if i else 'alternative'}) for i in range(2))
    ready = expected.startswith('proposal_')
    return {'version': 'jev-rank-flow/1', 'synthetic_only': True, 'scope_id': 'rank-test',
        'settings': {'binding_ref': 'rank-test', 'secret_ref': 'fake-test-key',
            'base_url': 'https://opencode.ai/zen', 'model': 'jev-1.13-free',
            'accepted_response_models': ['jev-1.13-free'], 'timeout_seconds': 2},
        'limits': {'max_http_requests': 7, 'max_model_attempts': 7, 'wall_timeout_seconds': 10},
        'task': case['task'], 'policy': policy, 'proposals': plain(proposals),
        'expected': {'disposition': 'ready' if ready else 'clarify', 'rank_value': expected,
            'selected_proposal_digest': proposals[int(expected[-1])].proposal_digest if ready else None}}


def response(request, ranked='proposal_1'):
    data = json.loads(request.content); qid, question = next(iter(data['questions'].items()))
    keys = list(question['criteria']); choice = ranked if qid == 'assignment.rank' else 'pass'
    probabilities = {key: 1 if key == choice else 0 for key in keys}
    if choice == 'tie':
        choice = 'proposal_0'
        probabilities = {key: 0.5 if key in ('proposal_0', 'proposal_1') else 0 for key in keys}
    if ranked == 'outside' and qid == 'assignment.rank': probabilities['proposal_0'] = 1
    return httpx2.Response(200, json={'model': 'jev-1.13-free', 'usage': {'input_tokens': 10, 'output_tokens': 2},
        'answers': {qid: {'type': 'choice', 'choice': choice, 'confidence': max(probabilities.values()), 'probabilities': probabilities}}})


@pytest.mark.asyncio
async def test_prepare_captures_actual_rank_question_without_http():
    data = plan(); frozen = await probe.prepare(data)
    assert frozen['credential_reads'] == frozen['real_model_requests'] == 0
    assert frozen['preparation_model_attempts'] == 7
    rank = frozen['questions'][-1]
    assert rank['question_id'] == 'assignment.rank'
    assert set(rank['options']) == {'proposal_0', 'proposal_1', 'none_suitable', 'insufficient_evidence'}
    assert rank['bounded_state']['proposals']['proposal_1']['payload']['synthetic_preference'] == 'preferred'
    assert rank['question_text'] == data['policy']['selection']['rank_instructions']
    assert frozen['preparation_quality'].startswith('not_evaluated')


@pytest.mark.asyncio
@pytest.mark.parametrize('ranked', ['proposal_0', 'proposal_1', 'none_suitable', 'insufficient_evidence', 'tie'])
async def test_original_rank_legal_selection_refusal_and_tie(tmp_path, ranked):
    data = plan(ranked); key = tmp_path / 'fake-key'; key.write_text('offline-test-only'); calls = []
    def handler(request): calls.append(json.loads(request.content)); return response(request, ranked)
    result = await probe.run_plan(data, tmp_path / 'out', key, True,
        ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(handler))
    assert result['status'] == 'SCOPED_PASS' and result['controlled_label_matches'] == 1
    assert result['model_quality_passes'] == result['real_model_requests'] == 0
    assert len(calls) == result['transport_attempts'] == 7
    assert list(calls[-1]['questions']) == ['assignment.rank']
    row = result['rows'][0]
    assert row['terminal_verified'] and row['quality_pass']
    assert row['rank_value'] == ranked
    assert row['selected_proposal_digest'] == data['expected']['selected_proposal_digest']
    assert row['result']['consumed']['repair_rounds'] == 0
    assert len(row['compose_calls']) == 1
    assert len(row['validate_calls']) == (1 if ranked.startswith('proposal_') else 0)
    assert row['graph_trace'][-1] == ('FinishReady' if ranked.startswith('proposal_') else 'FinishBusiness')
    if not ranked.startswith('proposal_'): assert row['result']['outcome']['proposals'] == []


@pytest.mark.asyncio
async def test_unknown_rank_id_fails_never_ready(tmp_path):
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    result = await probe.run_plan(plan(), tmp_path / 'out', key, True, ledger_path=tmp_path / 'ledger',
        transport=httpx2.MockTransport(lambda request: response(request, 'outside')))
    row = result['rows'][0]
    assert result['status'] == 'PARTIAL' and result['transport_attempts'] == 7
    assert row['technical_status'] == 'failed' and row['terminal_verified'] and not row['quality_pass']
    assert row['provider_error'] == 'protocol_invalid' and row['validate_calls'] == []
    assert len(row['answers']) == 6 and result['model_quality_passes'] == 0


@pytest.mark.asyncio
async def test_malformed_plan_no_credential_read(tmp_path, monkeypatch):
    data = plan(); data['proposals'][1]['preconditions'][0]['subject_ref']['identity']['id'] = 'wrong-task'
    key = tmp_path / 'must-not-read'; reads = []; original = Path.read_text
    def guarded(path, *args, **kwargs):
        if path == key: reads.append(path); raise AssertionError('credential read')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)
    with pytest.raises(probe.EvaluationError, match='plan_invalid'):
        await probe.run_plan(data, tmp_path / 'out', key, True, ledger_path=tmp_path / 'ledger')
    assert reads == [] and not (tmp_path / 'ledger').exists()

@pytest.mark.asyncio
async def test_deadline_keeps_dispatched_attempt_unknown(tmp_path):
    import asyncio
    data = plan(); data['limits']['wall_timeout_seconds'] = 0.05
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    async def stalled(request):
        await asyncio.sleep(10)
        return response(request)
    result = await probe.run_plan(data, tmp_path / 'out', key, True,
        ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(stalled))
    assert result['status'] == 'PARTIAL' and result['model_quality_passes'] == 0
    assert result['rows'][0]['technical_status'] == 'TIMEOUT_UNKNOWN'
    assert result['transport_attempts'] == result['usage_unknown_requests'] == 1
    assert result['rows'][0]['validate_calls'] == []
    with pytest.raises(probe.EvaluationError, match='case_already_claimed'):
        await probe.run_plan(data, tmp_path / 'again', key, True,
            ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(stalled))

@pytest.mark.asyncio
async def test_external_cancel_propagates_and_preserves_attempt(tmp_path):
    import asyncio
    data = plan(); key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    dispatched = asyncio.Event()
    async def stalled(request):
        dispatched.set(); await asyncio.sleep(10)
        return response(request)
    task = asyncio.create_task(probe.run_plan(data, tmp_path / 'out', key, True,
        ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(stalled)))
    await asyncio.wait_for(dispatched.wait(), 2); task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    result = json.loads((tmp_path / 'out/receipt.json').read_text())
    assert result['rows'][0]['technical_status'] == 'CANCELLED'
    assert result['transport_attempts'] == result['usage_unknown_requests'] == 1
    assert result['model_quality_passes'] == result['real_model_requests'] == 0
    assert result['rows'][0]['validate_calls'] == []
