"""Actual Codex compiler + original graph + official SDK with fake transport."""
import importlib.util
import json
from pathlib import Path
import httpx2
import pytest

SOURCE=Path(__file__).resolve().parents[3]/'decision-tooling/evaluation/codex_flow_probe.py'
SPEC=importlib.util.spec_from_file_location('test_codex_probe',SOURCE)
probe=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(probe)


def plan():
    value=json.loads(SOURCE.with_name('codex-unknown-plan.json').read_text())
    value['scope_id']='offline-codex-owner';value['settings']['timeout_seconds']=2
    value['limits']['wall_timeout_seconds']=10
    return value


def response(request):
    data=json.loads(request.content);qid,q=next(iter(data['questions'].items()))
    return httpx2.Response(200,json={'model':'jev-1.13-free','usage':{'input_tokens':10,'output_tokens':2},
        'answers':{qid:{'type':'choice','choice':'pass','confidence':1,
            'probabilities':{key:1 if key=='pass' else 0 for key in q['criteria']}}}})


async def test_T61_T62_T67_actual_owner_original_graph_does_not_promote_unknown(tmp_path):
    data=plan();prepared=await probe.prepare(data)
    assert prepared['credential_reads']==prepared['real_model_requests']==0
    assert prepared['port_binding_digest']==probe.binding_digest()
    native=prepared['port_binding']
    assert native['owner']=='actual CodexRuntimeProvider' and native['offer']['complete'] is False
    assert native['offer']['offers'][0]['supportStatus']=='unknown'
    key=tmp_path/'fake-key';key.write_text('offline-test-only')
    result=await probe.run_plan(data,tmp_path/'out',key,True,ledger_path=tmp_path/'ledger',
        transport=httpx2.MockTransport(response))
    assert result['status']=='SCOPED_PASS' and result['native_effects']==0
    assert result['real_model_requests']==result['model_quality_passes']==0
    assert result['transport_attempts']==6 and result['controlled_label_matches']==1
    row=result['rows'][0];assert row['terminal_verified'] and row['result']['outcome']['disposition']=='clarify'
    assert row['result']['outcome']['proposals']==[]
    receipt=row['validate_calls'][0]
    assert receipt['status']=='unverifiable' and receipt['validation_scope'].startswith('codex.defaults.declaration-compile/')
    byid={v['obligation_id']:v for v in receipt['obligation_results']}
    assert byid['native_compile']['status']=='passed' and byid['configuration']['status']=='unknown'
    assert byid['native_compile']['evidence_refs'][0]['durability']=='computed_nonpersistent'
    original=(tmp_path/'out/receipt.json').read_bytes()
    with pytest.raises(probe.edge.EvaluationError,match='case_already_claimed'):
        await probe.run_plan(data,tmp_path/'out',key,True,ledger_path=tmp_path/'ledger',transport=httpx2.MockTransport(response))
    assert (tmp_path/'out/receipt.json').read_bytes()==original


@pytest.mark.parametrize('defect',['implementation','schema','provider_generation','offer_ref','evidence'])
async def test_T57_T62_tampered_native_bindings_are_refused_before_key(tmp_path,monkeypatch,defect):
    data=plan();offer=data['fixture']['offer']
    if defect=='implementation':offer['descriptor_digest']='sha256:'+'f'*64
    elif defect=='schema':offer['input_schema']['properties']['model']['maxLength']=999
    elif defect=='provider_generation':offer['provider_ref']['identity']['provider_ref']['generation']=2
    elif defect=='offer_ref':offer['offer_ref']['identity']['definition_ref']['environmentNamespace']='foreign'
    else:offer['evidence_refs']=[{'environmentNamespace':'spec031-codex-pure','evidenceId':'fabricated'}]
    path=tmp_path/'must-not-read';original=Path.read_text
    def guarded(p,*args,**kwargs):
        assert p!=path,'credential read before plan rejection'
        return original(p,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',guarded)
    with pytest.raises(probe.edge.EvaluationError):
        await probe.run_plan(data,tmp_path/'out',path,True,ledger_path=tmp_path/'ledger',transport=httpx2.MockTransport(response))
    assert not (tmp_path/'ledger').exists() and not (tmp_path/'out/receipt.json').exists()


async def test_T60_live_authorization_required_before_key(tmp_path):
    with pytest.raises(probe.edge.EvaluationError,match='live_authorization_required'):
        await probe.run_plan(plan(),tmp_path/'out',tmp_path/'not-read',False,ledger_path=tmp_path/'ledger')
    assert not (tmp_path/'ledger').exists()
