"""Original graph edge cases and real SDK with fake HTTP, never model quality."""
import importlib.util
import json
from pathlib import Path

import httpx2
import pytest
from ordessa_decision.contracts import digest

SOURCE = Path(__file__).resolve().parents[2]/'evaluation'/'edge_flow_probe.py'
SPEC = importlib.util.spec_from_file_location('decision_edge_flow_probe',SOURCE)
probe = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(probe)


def plan(name):
    value = json.loads(SOURCE.with_name('edge-'+name+'-plan.json').read_text())
    value['scope_id'] = 'offline-edge-'+name
    value['settings']['timeout_seconds'] = 2
    value['limits']['wall_timeout_seconds'] = 10
    return value


def response(request):
    data = json.loads(request.content); qid,q = next(iter(data['questions'].items()))
    return httpx2.Response(200,json={'model':'jev-1.13-free','usage':{'input_tokens':10,'output_tokens':2},
        'answers':{qid:{'type':'choice','choice':'pass','confidence':1,
            'probabilities':{key:1 if key=='pass' else 0 for key in q['criteria']}}}})


@pytest.mark.asyncio
@pytest.mark.parametrize('name',['empty','main','configuration','injection'])
async def test_original_graph_edge_routes_with_frozen_questions(tmp_path,name):
    data = plan(name); frozen = await probe.prepare(data)
    assert frozen['real_model_requests'] == frozen['credential_reads'] == 0
    assert len(frozen['questions']) == frozen['maximum_http_requests'] == 6
    assert frozen['preparation_quality'].startswith('not_evaluated')
    key = tmp_path/'fake-key'; key.write_text('offline-test-only'); calls=[]
    def handler(request): calls.append(request); return response(request)
    result = await probe.run_plan(data,tmp_path/'out',key,True,
        ledger_path=tmp_path/'ledger',transport=httpx2.MockTransport(handler))
    row=result['rows'][0]; expected=data['expected']
    assert result['status']=='SCOPED_PASS' and row['terminal_verified']
    assert len(calls)==result['transport_attempts']==6
    assert result['controlled_label_matches']==1
    assert result['model_quality_passes']==result['real_model_requests']==0
    assert row['candidate_reads']==expected['candidate_reads']
    assert len(row['compose_calls'])==expected['compose'] and len(row['validate_calls'])==expected['validate']
    assert row['result']['outcome']['disposition']==expected['disposition']
    assert 'SelectAssignment' in row['graph_trace']
    if name=='main':
        assert row['result']['outcome']['proposals'][0]['payload']['action']=='noDelegation'
        assert row['candidate_reads']==0 and not row['compose_calls'] and not row['validate_calls']
    elif name=='configuration':
        assert row['result']['outcome']['proposals']==[]
        receipt=row['validate_calls'][0]
        assert receipt['status']=='unverifiable' and receipt['obligation_results'][0]['status']=='unknown'
        assert row['compose_calls'][0]['offer']==data['fixture']['offer']
        assert row['compose_calls'][0]['configuration']==data['fixture']['configuration']
        assert row['result']['outcome']['issues'][0]['code']=='proposal_unverifiable'
    elif name=='empty':
        assert row['result']['outcome']['proposals']==[] and not row['validate_calls']
    else:
        assert row['result']['outcome']['proposals'][0]['payload']['action']=='reuse'
    original=(tmp_path/'out'/'receipt.json').read_bytes()
    with pytest.raises(probe.EvaluationError,match='case_already_claimed'):
        await probe.run_plan(data,tmp_path/'out',key,True,
            ledger_path=tmp_path/'ledger',transport=httpx2.MockTransport(handler))
    assert len(calls)==6 and (tmp_path/'out'/'receipt.json').read_bytes()==original


@pytest.mark.asyncio
async def test_external_configuration_fields_not_hardcoded(tmp_path):
    data=plan('configuration'); fixture=data['fixture']; schema=fixture['offer']['input_schema']
    schema['properties']['threshold']=schema['properties'].pop('ratio'); schema['required']=['threshold']
    fixture['configuration']={'threshold':0.4}; fixture['offer']['configuration_kind']='synthetic.threshold.v1'
    fixture['offer']['descriptor_digest']=digest('descriptor',schema)
    key=tmp_path/'fake-key'; key.write_text('offline-test-only')
    result=await probe.run_plan(data,tmp_path/'out',key,True,ledger_path=tmp_path/'ledger',
        transport=httpx2.MockTransport(response))
    assert result['status']=='SCOPED_PASS'
    assert result['rows'][0]['compose_calls'][0]['configuration']=={'threshold':0.4}
    assert result['rows'][0]['validate_calls'][0]['status']=='unverifiable'


@pytest.mark.asyncio
@pytest.mark.parametrize('defect',['schema','boundary','expected','boolean_count'])
async def test_bad_plan_never_reads_key(tmp_path,monkeypatch,defect):
    data=plan('main' if defect=='boundary' else 'configuration')
    if defect=='schema': data['fixture']['configuration']['ratio']=0
    elif defect=='boundary': data['task']['boundaries']=[]
    elif defect=='boolean_count': data['expected']['candidate_reads']=True
    else: data['expected']['disposition']='ready'
    key=tmp_path/'never-read'; reads=[]; original=Path.read_text
    def guarded(path,*args,**kwargs):
        if path==key: reads.append(path); raise AssertionError('key read')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',guarded)
    with pytest.raises(probe.EvaluationError,match='plan_invalid'):
        await probe.run_plan(data,tmp_path/'out',key,True,ledger_path=tmp_path/'ledger')
    assert reads==[] and not (tmp_path/'ledger').exists()
