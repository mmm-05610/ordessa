"""Static candidate integrity only; no activation, approval, runtime or model calls."""
from pathlib import Path
import argparse, copy, hashlib, json, shutil, tempfile
import yaml
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods.definitions.models import CapabilityDescriptor, CompilationCapabilities, MethodSource
from ordessa_engineering.methods.definitions.models.identity import method_digest
from ordessa_engineering.methods.definitions.models.compiled import FrozenObject, thaw_value
from ordessa_engineering.methods.compilation.encoding import program_to_canonical, stored_program_from_canonical

ROOT=Path(__file__).resolve().parents[1]
PRIOR=ROOT.parent / "2.3.0"
ASSET_ROOT=ROOT.parents[1]
COMPILER='ordessa.methods/v2'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def compile_at(root):
    loaded=load_method(MethodSource(root),FileResourceReader())
    assert loaded.ok, loaded.error
    raw=json.loads((root/'contracts/capability-catalog.json').read_bytes())
    assert raw['fixture_only'] is True
    caps=CompilationCapabilities(tuple(CapabilityDescriptor(r['capability_id'],r['kind'],r['interface_version'],r['contract_digest'],r['contract']) for r in raw['capabilities']),'candidate-static-validation','fixture')
    compiled=compile_method(loaded.value,caps,COMPILER)
    assert compiled.ok, compiled.error
    return loaded.value,compiled.value

def build():
    assert not (ROOT/'bundle-lock.json').exists(), 'cannot silently reseal an existing candidate'
    loaded,compiled=compile_at(ROOT)
    program=program_to_canonical(compiled.program)
    assert program['capability_bindings']==loaded.manifest['requires']
    plan_digest=method_digest('compiled-method-program',program)
    payload={'schema_version':loaded.manifest['schema_version'],'method_id':loaded.manifest['method_id'],
        'release_version':loaded.manifest['release_version'],'manifest_sha256':sha(ROOT/'method.yaml'),
        'resource_digests':[{'id':r['id'],'sha256':r['sha256']} for r in sorted(loaded.manifest['resources'],key=lambda x:x['id'])],
        'required_capabilities':program['capability_bindings'],'compiler_version':COMPILER,
        'compiled_plan_digest':{'algorithm':'sha256','hex':plan_digest}}
    lock={'schema_version':1,'method_ref':{'method_id':loaded.manifest['method_id'],'release_version':'2.4.0',
        'schema_version':loaded.manifest['schema_version'],'snapshot_digest':{'algorithm':'sha256','hex':method_digest('method-snapshot',payload)}},
        'snapshot_payload':payload,'manifest_sha256':sha(ROOT/'method.yaml'),'resource_hash_algorithm':'sha256-raw-bytes',
        'snapshot_hash_domain':'ordessa/method-snapshot/v1\n','host_catalog_sha256':sha(ROOT/'contracts/capability-catalog.json'),
        'compiled_plan_path':'contracts/compiled-program.json','compiled_plan_digest':{'algorithm':'sha256','hex':plan_digest}}
    write(ROOT/'contracts/compiled-program.json',program)
    write(ROOT/'bundle-lock.json',lock)

def verify():
    loaded,compiled=compile_at(ROOT)
    program=program_to_canonical(compiled.program)
    assert program==json.loads((ROOT/'contracts/compiled-program.json').read_bytes())
    assert program_to_canonical(stored_program_from_canonical(program))==program
    source=loaded.resources['standard.source_review'].value
    criterion=next(c for c in source['criteria'] if c['criterion_id']=='claim_support')
    binding=criterion['checks'][0]['bindings']
    assert binding['claim_selection']=='all_declared_claims' and binding['empty_claim_set']=='error'
    assert binding['iteration']=='each_evidence_required_claim'
    expected=json.loads((ROOT/'tests/declared-contract.json').read_bytes())
    assert binding['nominal_answer_conversion']==expected['nominal_answer_conversion']
    assert binding['quality_admission']==expected['quality_admission']
    nominal=binding['nominal_answer_conversion'];quality=binding['quality_admission']
    assert set(nominal['option_statuses'])=={o['option_id'] for o in criterion['answer_vocabulary']['options']}
    assert set(nominal['option_statuses'].values()) <= {'satisfied','violated','insufficient','unknown'}
    assert all(nominal[k]=='unknown' for k in ('tie','missing_answer','incomplete_answer','truncated_input','unmapped_option'))
    assert quality['activation']=='matching_validated_evaluation_required'
    assert quality['missing_evaluation']==quality['unresolved_model']=='manual'
    assert 'decision_policy' not in criterion
    human=json.loads((ROOT/'tests/human-contract.json').read_bytes())
    policy_path=ROOT/'policies/product-chat-human-review.v1.yaml'
    policy=yaml.safe_load(policy_path.read_bytes())
    assert human['policy_digest']=='sha256:'+sha(policy_path)
    assert policy['policy_id']==human['policy_id'] and policy['revision']==human['policy_revision']
    assert policy['status_dispositions']==human['status_dispositions']
    assert policy['selection_authority']=='product_composition_and_configured_engineering_admission'
    assert policy['review_is_implementation_grant'] is False
    assert policy['whole_plan_answer']=='explicit_complete_checklist'
    assert policy['missing_answer']==policy['ambiguous_answer']=='pending'
    assert policy['mechanical_integrity']=='required'
    assert policy['accepted_source_trust_level']=='agent-attested'
    assert policy['authorized_attestor_role']=='registered_main_agent'
    added=[]
    for c in source['criteria']:
        hb=c['checks'][0]['bindings'].get('human_review_admission')
        if hb is not None:
            assert hb==human;added.append(c['criterion_id'])
    assert set(added)=={'claim_coverage','claim_support'}
    assert criterion['policy']=={'satisfied':'manual','violated':'block','insufficient':'block','unknown':'manual'}
    assert sha(ROOT/'decisions/source-support.yaml')==sha(PRIOR/'decisions/source-support.yaml')
    typed=next(s for s in compiled.program.standard_definitions if s.standard_id=='source-review')
    for c in typed.criteria:
        hb=thaw_value(c.checks[0].bindings).get('human_review_admission')
        assert (hb == human) if c.criterion_id in {'claim_coverage','claim_support'} else (hb is None)
    typed_criterion=next(c for c in typed.criteria if c.criterion_id=='claim_support')
    frozen=typed_criterion.checks[0].bindings
    assert type(frozen) is FrozenObject
    assert thaw_value(frozen)['human_review_admission']==human
    thawed=thaw_value(frozen)
    assert thawed['claim_selection']==binding['claim_selection'] and thawed['empty_claim_set']==binding['empty_claim_set']
    assert thawed['nominal_answer_conversion']==nominal and thawed['quality_admission']==quality
    before=yaml.safe_load((PRIOR/'standards/source-review.yaml').read_bytes())
    baseline=copy.deepcopy(source)
    baseline['revision']=before['revision']
    change=next(c for c in baseline['criteria'] if c['criterion_id']=='claim_support')['checks'][0]['bindings']
    del change['human_review_admission']
    del next(c for c in baseline['criteria'] if c['criterion_id']=='claim_coverage')['checks'][0]['bindings']['human_review_admission']
    assert baseline==before, 'unrequested criterion/policy/question/reduction drift'
    # Frozen value cannot be mutated through a decoded plain projection.
    thawed['claim_selection']='skip_design_choices'
    assert thaw_value(frozen)['claim_selection']=='all_declared_claims'
    preserved=json.loads((ROOT/'tests/preserved-releases.json').read_bytes())
    for path,digest in preserved.items(): assert sha(ASSET_ROOT/path)==digest, path
    old=json.loads((PRIOR/'bundle-lock.json').read_bytes())['method_ref']
    new=json.loads((ROOT/'bundle-lock.json').read_bytes())['method_ref']
    assert old['release_version']=='2.3.0' and new['release_version']=='2.4.0'
    assert old['snapshot_digest']!=new['snapshot_digest']
    with tempfile.TemporaryDirectory() as tmp:
        staged=Path(tmp)/'candidate';shutil.copytree(ROOT,staged)
        std=staged/'standards/source-review.yaml'
        std.write_text(std.read_text().replace('all_declared_claims','skip_design_choices'))
        result=load_method(MethodSource(staged),FileResourceReader())
        assert not result.ok and result.error.code=='RESOURCE_DIGEST_MISMATCH', result.error
    with tempfile.TemporaryDirectory() as tmp:
        staged=Path(tmp)/'candidate';shutil.copytree(ROOT,staged)
        mp=staged/'method.yaml';mp.write_text(mp.read_text().replace('release_version: 2.4.0','release_version: 2.3.0',1))
        result=load_method(MethodSource(staged),FileResourceReader())
        assert not result.ok, 'stale lock accepted a substituted release'
    cases=json.loads((ROOT/'tests/human-cases.json').read_bytes())
    assert all(c['runtime_validation']=='pending_engineering_consumer' for c in cases['cases'])
    return {'method_ref':new,'standard_raw_sha256':sha(ROOT/'standards/source-review.yaml'),
        'loader':'passed','compiler':'passed','typed_frozen_bindings':'passed','stored_program_round_trip':'passed',
        'unchanged_question_iteration_policy_reduction':'passed','prior_2_1_2_2_2_3_files_unchanged':len(preserved),
        'tampered_claim_selection':'rejected_by_resource_digest','stale_release_lock':'rejected',
        'nominal_contract_and_quality_separation':'unchanged','human_semantic_scope_policy_digest':'declaration_verified','original_three_option_question_bytes':'unchanged','consumer_counterexamples':len(cases['cases']),'consumer_execution':'not_run',
        'publication':'not_run_fixture_catalog','real_jev':'not_run','real_pi':'not_run','final_acceptance':'not_complete'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--build-lock',action='store_true');args=parser.parse_args()
    if args.build_lock: build()
    result=verify();write(ROOT/'tests/validation-result.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
