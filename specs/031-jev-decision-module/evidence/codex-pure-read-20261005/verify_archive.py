"""Independent archived proof verification; no credential, HTTP or Harness call."""
import asyncio
import importlib.util
import json
from pathlib import Path
from pacthold.agents.public import OwnerProposalInput
from ordessa_decision.contracts import ReadContext, ProposalDraft, digest, plain
from ordessa_decision.evidence import FileEvidenceReader

BASE=Path(__file__).resolve().parent/'live'
def load(name):return json.loads((BASE/name).read_text())
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

async def verify():
    plan=load('plan.json');receipt=load('receipt.json');frozen=load('frozen-inputs.json')
    probe=module('archived_codex_probe',BASE/'source/codex_flow_probe.py')
    native=module('archived_codex_owner',BASE/'source/owner/provider.py')
    probe.native=native;probe.CodexRuntimeProvider=native.CodexRuntimeProvider
    binding=probe.binding_digest()
    assert binding==frozen['port_binding_digest']
    values=probe.edge.validate(plan,binding_digest=binding)
    assert plain(values[-2].ref)==frozen['flow']
    assert frozen['input_hash']==digest('policy',plan)
    assert receipt['status']=='SCOPED_PASS' and receipt['actual_http_requests']==6
    assert receipt['credential_reads']==1 and receipt['retry']==receipt['native_effects']==0
    row=receipt['rows'][0];result=row['result']
    assert row['quality_pass'] and row['terminal_verified'] and result['status']=='completed'
    assert digest('result',result)==row['result_digest']
    context=ReadContext(object(),'independent-native-archive')
    reader=FileEvidenceReader(BASE/'durable',read_context=context)
    try:observed=await reader.read(row['run_id'],context)
    finally:await reader.close()
    assert observed['status']=='completed' and observed['terminal']['result']==result
    assert observed['terminal']['terminal_digest']==row['result_digest']
    assert observed['events'][0]['payload']['manifest_digest']==result['run_manifest_digest']
    assert result['outcome']['disposition']=='clarify' and result['outcome']['proposals']==[]
    assert row['candidate_reads']==1 and len(row['compose_calls'])==len(row['validate_calls'])==1
    intents=[e['payload'] for e in observed['events'] if e['payload']['type']=='call.intent']
    responses=[e['payload'] for e in observed['events'] if e['payload']['type']=='call.response']
    assert len(intents)==len(responses)==len(row['answers'])==6
    assert [e['question_digest'] for e in intents]==frozen['question_digests']
    assert [e['answer_digest'] for e in responses]==[digest('answer',v) for v in row['answers']]
    assert all(v['value']=='pass' for v in row['answers'])
    assert observed['events'][-1]['payload']['type']=='terminal.commit'
    port=row['port_binding'];offer=port['offer'];proposal=ProposalDraft.from_dict(port['composed_proposal'])
    assert offer['complete'] is False and offer['offers'][0]['supportStatus']=='unknown'
    definition=plan['fixture']['offer']['provider_ref']['identity']['definition_ref']
    native_input=OwnerProposalInput(definition,offer['ownerRef'],offer['descriptorRevision'],
        {'declarations':[{'declarationId':plan['fixture']['template_id'],
            'configurationKind':plan['fixture']['offer']['configuration_kind'],
            'schemaVersion':plan['fixture']['offer']['schema_version'],
            'action':'value','requirement':'required','payload':plain(proposal.payload['configuration'])}]},
        (definition,),tuple({'obligationId':o.obligation_id,'requirement':o.requirement,
            'checkerId':o.validator_kind,'checkerVersion':o.version_constraint}
            for o in proposal.required_validation_obligations))
    validation=row['validate_calls'][0];checks={o['obligation_id']:o for o in validation['obligation_results']}
    assert validation['proposal_digest']==proposal.proposal_digest and validation['status']=='unverifiable'
    assert validation['validation_scope']=='codex.defaults.declaration-compile/'+native.DEFAULTS_SCHEMA
    assert checks['native_compile']['status']=='passed' and checks['configuration']['status']=='unknown'
    evidence=checks['native_compile']['evidence_refs'][0]
    assert evidence['inputDigest']==native_input.input_digest and evidence['durability']=='computed_nonpersistent'
    assert checks['configuration']['evidence_refs']==[]
    value={'verified_runs':1,'run_id':row['run_id'],
        'verified':'HASH_CHAIN_TERMINAL_MANIFEST_SOURCE_PLAN_FLOW_NATIVE_INPUT_MAPPING_OBLIGATIONS_COUNTS',
        'credential_reads':0,'real_model_requests':0,'native_effects':0,
        'scope':'actual Codex compiler only; controlled candidate; no Harness or actual apply'}
    (BASE/'independent-verification.json').write_text(json.dumps(value,indent=2)+'\n')
    print('archived native compiler + original graph proof verified; no key, HTTP or Harness')

if __name__=='__main__':asyncio.run(verify())
