"""Original reference graph + official SDK, exclusively synthetic fake HTTP."""
import asyncio
import importlib.util
import json
from pathlib import Path

import httpx2
import pytest
from ordessa_decision.contracts import plain
from ordessa_decision.flows.agent_assignment.build import load_assignment_policy

SOURCE = Path(__file__).resolve().parents[2] / 'evaluation' / 'reference_flow_probe.py'
SPEC = importlib.util.spec_from_file_location('decision_reference_flow_probe', SOURCE)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def plan():
    frozen = json.loads(SOURCE.with_name('domain-cases-v2.json').read_text())
    case = next(c for c in frozen['cases'] if c['id'] == 'clear-full')
    return {'version': 'jev-reference-flow/1', 'synthetic_only': True, 'scope_id': 'reference-test',
        'settings': {'binding_ref': 'reference-test', 'secret_ref': 'fake-test-key',
            'base_url': 'https://opencode.ai/zen', 'model': 'jev-1.13-free',
            'accepted_response_models': ['jev-1.13-free'], 'timeout_seconds': 2},
        'limits': {'max_http_requests': 12, 'max_model_attempts': 12,
            'wall_timeout_seconds': 10, 'case_timeout_seconds': 4},
        'task': case['task'], 'policy': plain(load_assignment_policy(
            task_gate=frozen['task_gate_policy'], task_gate_facts=case['facts']))}


def passing(request, answer='pass'):
    data = json.loads(request.content)
    qid, question = next(iter(data['questions'].items()))
    keys = list(question['criteria'])
    return httpx2.Response(200, json={'model': 'jev-1.13-free',
        'usage': {'input_tokens': 10, 'output_tokens': 2}, 'answers': {qid: {
            'type': 'choice', 'choice': answer, 'confidence': 1,
            'probabilities': {key: 1 if key == answer else 0 for key in keys}}}})


@pytest.mark.asyncio
async def test_original_graph_six_gate_questions_and_actual_repair(tmp_path):
    data = plan(); data['limits']['max_model_attempts'] = 12
    frozen = probe.prepare(data)
    assert frozen['credential_reads'] == frozen['real_model_requests'] == 0
    assert len(frozen['questions']) == 6 and frozen['maximum_http_requests'] == 12
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    calls = []
    def handler(request): calls.append(request); return passing(request)
    result = await probe.run_plan(data, tmp_path / 'out', key, True,
        ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(handler))
    assert result['status'] == 'SCOPED_PASS'
    assert len(calls) == result['transport_attempts'] == 12
    assert result['real_model_requests'] == result['model_quality_passes'] == 0
    assert result['controlled_label_matches'] == 2
    ready, repaired = result['rows']
    assert all(row['terminal_verified'] and len(row['answers']) == 6 for row in result['rows'])
    assert ready['graph_trace'] == ['CheckPolicy', 'HardTaskGate', 'ReadFacts', 'SelectAssignment', 'FinishReady']
    assert repaired['graph_trace'] == ['CheckPolicy', 'HardTaskGate', 'ReadFacts', 'SelectAssignment', 'Repair', 'SelectAssignment', 'FinishReady']
    assert len(repaired['compose_calls']) == len(repaired['validate_calls']) == 2
    assert repaired['compose_calls'][1]['feedback']['issue_codes'] == ['configuration_ratio_revision_required']
    assert repaired['compose_calls'][0]['proposal_digest'] != repaired['compose_calls'][1]['proposal_digest']
    assert repaired['result']['consumed']['repair_rounds'] == 1
    for row in result['rows']:
        actual = row['result']['outcome']['proposals'][0]['preconditions'][0]['subject_ref']['identity']
        assert actual == {'id': data['task']['task_id'], 'revision': data['task']['task_revision']}
    original = (tmp_path / 'out' / 'receipt.json').read_bytes()
    with pytest.raises(probe.EvaluationError, match='case_already_claimed'):
        await probe.run_plan(data, tmp_path / 'out', key, True,
            ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(handler))
    assert (tmp_path / 'out' / 'receipt.json').read_bytes() == original and len(calls) == 12


@pytest.mark.asyncio
async def test_task_clarify_stops_composition(tmp_path):
    data = plan(); data['limits']['max_model_attempts'] = 12
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    result = await probe.run_plan(data, tmp_path / 'out', key, True, ledger_path=tmp_path / 'ledger',
        transport=httpx2.MockTransport(lambda request: passing(request, 'unknown')))
    assert result['status'] == 'PARTIAL' and result['transport_attempts'] == 12
    for row in result['rows']:
        assert row['result']['outcome']['disposition'] == 'clarify'
        assert row['compose_calls'] == row['validate_calls'] == []
        assert row['graph_trace'] == ['CheckPolicy', 'HardTaskGate', 'FinishBusiness']
        assert not row['quality_pass']


@pytest.mark.asyncio
async def test_bad_plan_no_credential_read(tmp_path, monkeypatch):
    data = plan(); data['limits']['max_model_attempts'] = 17
    key = tmp_path / 'never-read'; reads = []
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        if path == key: reads.append(path); raise AssertionError('credential read')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)
    with pytest.raises(probe.EvaluationError, match='plan_invalid'):
        await probe.run_plan(data, tmp_path / 'out', key, True, ledger_path=tmp_path / 'ledger')
    assert reads == [] and not (tmp_path / 'ledger').exists()


@pytest.mark.asyncio
async def test_failed_call_no_ready_and_no_hidden_retry(tmp_path):
    data = plan(); data['limits']['max_model_attempts'] = 12
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    result = await probe.run_plan(data, tmp_path / 'out', key, True, ledger_path=tmp_path / 'ledger',
        transport=httpx2.MockTransport(lambda request: httpx2.Response(500, json={'error': 'private-marker'})))
    assert result['status'] == 'PARTIAL' and result['transport_attempts'] == 2
    assert all(r['technical_status'] == 'failed' and r['terminal_verified'] and not r['quality_pass']
        and not r['compose_calls'] for r in result['rows'])
    assert 'private-marker' not in json.dumps(result)


@pytest.mark.asyncio
async def test_cancelled_call_retains_unknown_claim_no_ready(tmp_path):
    data = plan(); data['limits']['max_model_attempts'] = 12
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only'); entered = asyncio.Event()
    async def pending(request): entered.set(); await asyncio.Event().wait()
    task = asyncio.create_task(probe.run_plan(data, tmp_path / 'out', key, True,
        ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(pending)))
    await asyncio.wait_for(entered.wait(), 3); task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    result = json.loads((tmp_path / 'out' / 'receipt.json').read_text())
    assert result['status'] == 'PARTIAL' and result['transport_attempts'] == 1
    assert result['http_audit'][0]['status'] == 'CANCELLED_UNKNOWN'
    assert result['rows'][0]['quality_pass'] is False and not result['rows'][0]['compose_calls']


def test_observing_state_factory_binds_probe_code_and_frozen_plan():
    from ordessa_decision.flows.agent_assignment.build import build_assignment_flow
    data = plan(); first = probe.prepare(data)
    assert first['flow']['content_digest'] != plain(build_assignment_flow(data['policy']).ref)['content_digest']
    data['scope_id'] = 'other-reviewed-plan'
    assert probe.prepare(data)['flow']['content_digest'] != first['flow']['content_digest']


@pytest.mark.asyncio
async def test_global_deadline_preserves_cancelled_run_and_unrun_inventory(tmp_path):
    data = plan(); data['limits']['wall_timeout_seconds'] = 0.15
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    async def pending(request): await asyncio.Event().wait()
    result = await probe.run_plan(data, tmp_path / 'out', key, True,
        ledger_path=tmp_path / 'ledger', transport=httpx2.MockTransport(pending))
    first, second = result['rows']
    assert result['status'] == 'PARTIAL' and result['transport_attempts'] == 1
    assert first['technical_status'] == 'TIMEOUT_UNKNOWN' and first.get('run_id')
    assert not first['quality_pass'] and first['compose_calls'] == []
    assert second['technical_status'] == 'NOT_RUN' and second['error'] == 'global_deadline'
    assert result['http_audit'][0]['status'] == 'CANCELLED_UNKNOWN'


@pytest.mark.asyncio
async def test_external_negative_expectation_and_clarify_are_separate_from_ready(tmp_path):
    data = plan(); data['expected'] = {cid: {'disposition':'clarify','compose':0,'validate':0,'repair_rounds':0} for cid in probe.CASE_IDS}
    key = tmp_path / 'fake-key'; key.write_text('offline-test-only')
    result = await probe.run_plan(data, tmp_path / 'out', key, True, ledger_path=tmp_path / 'ledger',
        transport=httpx2.MockTransport(lambda request: passing(request, 'unknown')))
    assert result['status'] == 'SCOPED_PASS' and result['controlled_label_matches'] == 2
    assert result['model_quality_passes'] == result['actual_http_requests'] == 0
    assert all(row['result']['outcome']['disposition'] == 'clarify' and not row['compose_calls'] for row in result['rows'])
    data['expected'][probe.CASE_IDS[0]]['disposition'] = 'invented-private-label'
    with pytest.raises(probe.EvaluationError, match='plan_invalid'): probe.prepare(data)
