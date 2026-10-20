"""Read existing original records without using execution/replay as a reader."""
import asyncio
import json
from types import SimpleNamespace
import pytest
from decision_runtime import DecisionAnswer, DecisionRunner, RulesOutcome
from decision_runtime.capability import build_capability
from decision_runtime.definitions.values import DecisionError,canonical_bytes,digest_hex
from decision_runtime.evidence import EvidenceScope,FilesystemEvidenceStore
from decision_runtime.settings import DecisionsSettings


def snapshot(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_missing_and_pending_reads_never_make_or_complete_claims(tmp_path):
    store=FilesystemEvidenceStore(tmp_path).scoped(EvidenceScope('principal','original'))
    digest='a'*64
    before=snapshot(tmp_path)
    with pytest.raises(DecisionError,match='evidence_scope_unavailable'):store.read_run('request',digest)
    assert snapshot(tmp_path)==before
    created,operation,_=store.claim_run('request',digest)
    assert created
    with pytest.raises(DecisionError,match='run_not_found'):store.read_run('absent-request',digest)
    before=snapshot(tmp_path)
    assert store.read_run('request',digest)==(operation,None)
    assert store.read_run('request',digest)==(operation,None)
    assert snapshot(tmp_path)==before
    with pytest.raises(DecisionError,match='run_request_conflict'):store.read_run('request','b'*64)
    assert snapshot(tmp_path)==before


@pytest.mark.parametrize('field',['claimDigest','resultDigest','schemaVersion'])
def test_original_result_tampering_is_refused_without_repair(tmp_path,field):
    store=FilesystemEvidenceStore(tmp_path).scoped(EvidenceScope('principal','original'))
    store.claim_run('request','a'*64);store.complete_run('request','a'*64,{'status':'unknown'})
    target=next(tmp_path.rglob('.run-result-*.json'));value=json.loads(target.read_bytes());value[field]='tampered'
    target.write_bytes(canonical_bytes(value));before=snapshot(tmp_path)
    with pytest.raises(DecisionError,match='run_record_corrupt'):store.read_run('request','a'*64)
    assert snapshot(tmp_path)==before


class Provider:
    binding_ref='controlled-existing-provider'
    settings_digest='sha256:'+'b'*64
    def __init__(self,unknown=False):self.calls=0;self.answers=[];self.unknown=unknown
    async def decide(self,question,context):
        self.calls+=1;context.claim(question,self.settings_digest)
        if self.unknown:raise TimeoutError('controlled lost response')
        receipt={'selection_status':'unique','probabilities':{'yes':.9,'no':.1},
            'resolved_model':'controlled','requested_model':'controlled',
            'protocol_validation_version':'controlled/1','question_digest':question.question_digest,
            'provider_settings_digest':self.settings_digest}
        answer=DecisionAnswer(question.question_id,'choice','yes',receipt,{'status':'reported'})
        self.answers.append(answer);return answer


class Collect:
    engine_id='controlled-existing-answer-collection'
    def validate(self,payload):assert payload=={'collect':['one','two']}
    def evaluate(self,payload,facts):
        answers=[DecisionAnswer(key,'choice',facts[key]['answer'],facts[key]['receipt'],
                   facts[key]['usage']).projection() for key in payload['collect']]
        return RulesOutcome(values={'answers':answers},disposition='passed')
    def close(self):pass


@pytest.mark.parametrize('unknown',[False,True])
def test_real_job_result_and_summary_readback_preserve_all_answers_or_unknown_without_resend(tmp_path,unknown):
    provider=Provider(unknown);owner=FilesystemEvidenceStore(tmp_path);scope=EvidenceScope('principal','original')
    capability=build_capability(DecisionsSettings(DecisionRunner,owner,provider,Collect()),
        invocation_resolver=lambda context:context,evidence_scope_resolver=lambda *_:scope)
    question={'kind':'choice','text':'Controlled finite question','options':{'yes':'yes','no':'no'},
              'bounded_state':{'requestVersion':3,'fence':2},'allowed_answer_ids':['yes','no']}
    job={'spec_version':'decision-job/1','job_id':'original-review-request','version':1,
        'input':{'run':True},'limits':{'max_model_calls':2,'max_steps':3,'max_value_bytes':8192,'timeout_seconds':2.0},
        'steps':[{'id':key,'type':'ask','engine':None,'when':{'fact':'input.run','op':'eq','value':True},
                  'payload':{'question':question}} for key in ['one','two']]+[
                 {'id':'collect','type':'rules','engine':None,'when':{'fact':'input.run','op':'eq','value':True},
                  'payload':{'collect':['one','two']}}],
        'result':{'from':'collect','path':['values','answers']}}
    result=asyncio.run(capability.handlers['decisions.run']({'job':job},SimpleNamespace(request_id='original-request')))
    store=owner.scoped(scope);before=snapshot(tmp_path)
    operation,recorded=store.read_run('original-request',digest_hex({'job':job,'dryRun':False}))
    assert operation==result.operation_ref and recorded['status']==result.status
    assert store.read_run('original-request',digest_hex({'job':job,'dryRun':False}))==(operation,recorded)
    assert snapshot(tmp_path)==before
    assert provider.calls==(1 if unknown else 2)
    if unknown:
        assert result.status=='unknown' and recorded['error']['retryable'] is False
    else:
        assert result.status=='completed'
        assert recorded['data']['result']==[a.projection() for a in provider.answers]
        summary=store.get(recorded['data']['evidence']['digest'])
        assert summary['job_digest']==digest_hex(job)
        assert summary['result_digest']==digest_hex(recorded['data']['result'])
        assert summary['answers']=={a.question_id:a.answer_digest for a in provider.answers}
        assert 'manifest' not in summary and 'events' not in summary
    foreign=owner.scoped(EvidenceScope('principal','foreign'))
    with pytest.raises(DecisionError,match='evidence_scope_unavailable'):
        foreign.read_run('original-request',digest_hex({'job':job,'dryRun':False}))
    assert snapshot(tmp_path)==before
