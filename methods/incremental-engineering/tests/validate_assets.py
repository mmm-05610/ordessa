"""Asset conformance only. No model, approval, DID owner or runtime side effects."""
from __future__ import annotations
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
import yaml
from jsonschema import Draft202012Validator
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.compilation.encoding import program_to_canonical
from ordessa_engineering.methods.definitions.models import CapabilityDescriptor, CompilationCapabilities, MethodSource
from ordessa_engineering.methods.loading.loader import load_method

ROOT = Path(__file__).resolve().parents[1]
COMPILER = 'ordessa.methods/v2'

def catalog(root=ROOT):
    path = root / ('contracts/capability-catalog.json' if root == ROOT else 'catalog.json')
    raw = json.loads(path.read_text())
    assert raw['fixture_only'] is True
    return CompilationCapabilities(tuple(CapabilityDescriptor(
        row['capability_id'], row['kind'], row['interface_version'],
        row['contract_digest'], row['contract']) for row in raw['capabilities']),
        'method-asset-validation', 'fixture')

def compile_at(root, caps=None):
    loaded = load_method(MethodSource(root), FileResourceReader())
    assert loaded.ok, loaded.error
    result = compile_method(loaded.value, caps or catalog(), COMPILER)
    assert result.ok, result.error
    return loaded.value, result.value

def digest(value, kind):
    from ordessa_engineering.methods.definitions.models.identity import method_digest
    return method_digest(kind, value)

def build_lock(root=ROOT):
    """Explicit release artifact rebuild; does not publish/register/activate it."""
    with tempfile.TemporaryDirectory() as directory:
        staged = Path(directory) / 'method'
        shutil.copytree(root, staged)
        (staged / 'bundle-lock.json').unlink(missing_ok=True)
        loaded, compiled = compile_at(staged)
        program = program_to_canonical(compiled.program)
        plan_digest = digest(program, 'compiled-method-program')
        manifest = loaded.manifest
        manifest_digest = hashlib.sha256((root / 'method.yaml').read_bytes()).hexdigest()
        payload = {
            'schema_version': manifest['schema_version'], 'method_id': manifest['method_id'],
            'release_version': manifest['release_version'], 'manifest_sha256': manifest_digest,
            'resource_digests': [{'id': r['id'], 'sha256': r['sha256']}
                                 for r in sorted(manifest['resources'], key=lambda row: row['id'])],
            'required_capabilities': manifest['requires'], 'compiler_version': COMPILER,
            'compiled_plan_digest': {'algorithm': 'sha256', 'hex': plan_digest}}
        lock = {'schema_version': 1, 'method_ref': {
            'method_id': manifest['method_id'], 'release_version': manifest['release_version'],
            'schema_version': manifest['schema_version'],
            'snapshot_digest': {'algorithm': 'sha256', 'hex': digest(payload, 'method-snapshot')}},
            'snapshot_payload': payload, 'manifest_sha256': manifest_digest,
            'resource_hash_algorithm': 'sha256-raw-bytes',
            'snapshot_hash_domain': 'ordessa/method-snapshot/v1\n',
            'host_catalog_sha256': hashlib.sha256((root/'contracts/capability-catalog.json').read_bytes()).hexdigest(),
            'compiled_plan_path': 'contracts/compiled-program.json',
            'compiled_plan_digest': {'algorithm':'sha256','hex':plan_digest}}
        for path, value in [('bundle-lock.json', lock), ('contracts/compiled-program.json', program)]:
            (root/path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
        return lock

def verify_assets():
    loaded, compiled = compile_at(ROOT)
    program = program_to_canonical(compiled.program)
    assert program['schema_version'] == 2
    assert loaded.manifest['release_version'] == '2.1.0'
    # Check policy separation and block unknown/uncalibrated results.
    standards = [r.value for r in loaded.resources.values() if r.declaration['kind']=='standard']
    semantic_count = 0
    for standard in standards:
        for criterion in standard['criteria']:
            assert criterion['policy']['unknown'] != 'pass'
            if any(c['capability_id']=='ordessa.decision.evaluate' for c in criterion['checks']):
                semantic_count += 1
                assert criterion['policy']['satisfied'] == 'manual'
                assert 'decision_policy' not in criterion
    assert semantic_count >= 8
    assert {'summary-review','engineering-content','source-review','quality-review'} <= {s['standard_id'] for s in standards}
    for r in loaded.resources.values():
        if r.declaration['kind']=='document_schema':
            Draft202012Validator.check_schema(r.value)
    alternate = ROOT/'examples/alternate-method'
    alt_loaded, alt_compiled = compile_at(alternate, catalog(alternate))
    alt = program_to_canonical(alt_compiled.program)
    assert alt_loaded.manifest['method_id'] != loaded.manifest['method_id']
    assert [d['document_type'] for d in alt['documents']] == ['maintenance-note']
    assert [n['id'] for n in alt['workflow']['steps']] == ['await_note','review_note','reviewed']
    # Missing capability cannot compile, even with all resource declarations intact.
    missing = CompilationCapabilities((), 'empty-registry','fixture')
    rejected = compile_method(loaded, missing, COMPILER)
    assert not rejected.ok
    # Tampering resource bytes fails the real loader, no hand-coded gate.
    with tempfile.TemporaryDirectory() as directory:
        staged = Path(directory)/'method';shutil.copytree(ROOT,staged)
        (staged/'documents/did-change/template.md').write_text('tampered')
        rejected = load_method(MethodSource(staged),FileResourceReader())
        assert not rejected.ok and rejected.error.code == 'RESOURCE_DIGEST_MISMATCH', rejected.error
    # Remove actual schema evidence: exact NOR basis must be present and nonempty.
    schema = loaded.resources['document.did_change.schema'].value
    change_schema = schema['properties']['changes']['items']
    assert change_schema['properties']['basis_refs']['minItems'] == 1
    example = {'change_id':'C1','operation':'delete','target_locator':'SRS/R1','before':'requires human grant',
               'after':'','basis_refs':[],'semantic_support':'unknown','authority_kind':'hypothesis',
               'impact':['permission'],'disposition':'blocked'}
    assert not Draft202012Validator(change_schema).is_valid(example)
    # A blocked conversion must not fabricate applied DID or executable tasks.
    package_schema = loaded.resources['document.spec_kit_package.schema'].value
    blocked = {'document_type':'spec-kit-package','schema_version':2,'status':'CONVERSION_BLOCKED',
               'blocked_scopes':['missing trusted acceptance and DID application'],
               'questions':['select and accept the project standards'],
               'verification_state':'planned_not_executed'}
    assert Draft202012Validator(package_schema).is_valid(blocked)
    premature = dict(blocked, status='CONVERTED_DRAFT')
    assert not Draft202012Validator(package_schema).is_valid(premature)
    # Historical confirmation/ref data remains historical, never rewritten to M2.
    historical = json.loads((ROOT/'examples/minimal-change/fixture-refs.json').read_text())
    current = json.loads((ROOT/'bundle-lock.json').read_text())['method_ref']
    assert historical['method_ref']['release_version']=='1.1.0'
    assert historical['method_ref']['snapshot_digest'] != current['snapshot_digest']
    # The published workflow cannot jump from opinion/consent to derivation.
    nodes = {node['id']:node for node in program['workflow']['steps']}
    assert nodes['quality_review']['outcomes']['passed']=={'next':'await_notice'}
    assert nodes['request_approval']['outcomes']['granted']=={'next':'await_did_applied'}
    assert nodes['await_did_applied']['match']=={
        'proposal':'proposal_ref','grant':'approval_ref','baseline':'baseline_ref'}
    assert nodes['derive_package']['inputs']['apply_receipt']=='apply_receipt_ref'
    assert nodes['adopt']['outcomes']['adopted']=={'next':'await_feedback'}
    # v1 accepts explicit, traceable chat evidence without platform verification.
    confirmation_schema = loaded.resources['document.confirmation_evidence.schema'].value
    selected = loaded.manifest['metadata']['product_confirmation_policy']
    fref = {'object_id':'fixture.P1','revision':'1','digest':'1'*64,'locator':'fixture-only'}
    evidence = {'document_type':'confirmation-evidence','schema_version':1,'evidence_id':'fixture.E1',
        'policy_ref':{k:selected[k] for k in ('policy_id','revision','sha256')},
        'attestor_role':'main_agent','attestor_ref':fref,
        'question':'Do you accept P1/r1 for the stated DID application scope?',
        'necessary_context':'Exact proposal P1/r1 and changes were explained.',
        'user_answer':'Yes, accept that stated change.',
        'source':{'locator':'fixture conversation transcript','message_refs':[],
                  'locator_limitations':'Platform message refs unavailable in this fixture.',
                  'trust_level':'agent-attested','independent_platform_verification':False},
        'object_versions':[fref],'scope_by_action':{'DID_WRITE':['fixture.P1/r1']},
        'interpretation':'confirmed'}
    validator=Draft202012Validator(confirmation_schema)
    assert validator.is_valid(evidence)
    assert not validator.is_valid({'approved':True})
    no_question=dict(evidence);no_question.pop('question')
    assert not validator.is_valid(no_question)
    spoof=dict(evidence,source=dict(evidence['source'],independent_platform_verification=True))
    assert not validator.is_valid(spoof)
    elevated=dict(evidence,policy_ref=dict(evidence['policy_ref'],policy_id='arbitrary-method-policy'))
    assert not validator.is_valid(elevated)
    cases = json.loads((ROOT/'tests/judgment-cases.json').read_text())
    assert cases['quality_validation']=='not_run'
    assert len({c['case_id'] for c in cases['cases']}) == len(cases['cases'])
    assert cases['corpus_revision'] == 2
    historical_corpus=ROOT/'tests'/cases['previous_corpus']['path']
    assert hashlib.sha256(historical_corpus.read_bytes()).hexdigest()==cases['previous_corpus']['sha256']
    assert (ROOT/'tests'/cases['independent_review_ref']).is_file()
    groups={name:[c for c in cases['cases'] if c['evaluation_group']==name]
            for name in ('source_semantics','summary_fidelity','mechanical_gate')}
    assert tuple(len(groups[name]) for name in groups)==(6,1,5)
    mapping=cases['label_policy']['source_answer_to_review_opinion']
    assert mapping=={'supported':'SUPPORTED','contradicted':'CONFLICT','insufficient':'NEEDS_EVIDENCE'}
    for case in groups['source_semantics']:
        assert case['synthetic'] and case['context']['fixture_current']
        assert mapping[case['expected']['jev_choice']]==case['expected']['review_opinion']
        assert case['expected']['automatic_pass'] is False
        assert case['include_in_source_judgment_metrics'] is True
    for case in groups['mechanical_gate']:
        assert 'jev_choice' not in case['expected']
        assert case['expected']['jev_invocation_allowed_for_this_gate'] is False
        assert case['include_in_source_judgment_metrics'] is False
    by_id={c['case_id']:c for c in cases['cases']}
    assert by_id['reference-is-not-support']['context']['duration_explicitly_unspecified']
    assert by_id['valid-conflict']['context']['actual_project_decision'] is False
    deletion=by_id['delete-reviewed']
    assert deletion['before']['revision']=='1' and deletion['after']['text']==''
    assert '不要求独立验签或再次点浮窗' in deletion['before']['text']
    naming=by_id['ordinary-freedom']['context']
    assert not any(naming[k] for k in ('public_api_changed','reflection_or_string_lookup_present',
                                      'persisted_identifiers_changed','observable_behavior_changed'))
    interface=by_id['important-unknown']
    assert interface['before']['public_api']!=interface['after']['public_api']
    assert interface['before']['stored_format']!=interface['after']['stored_format']
    assert groups['summary_fidelity'][0]['proposal']['revision']==groups['summary_fidelity'][0]['summary']['revision']
    opinion=by_id['judgment-not-grant']['context']
    assert not opinion['independent_signature_required'] and not opinion['floating_window_required']
    assert {'source_semantics','source_integrity','summary_fidelity','engineering_quality','version_authority','authority','real_provider'} <= {c['boundary'] for c in cases['cases']}
    return {'loader':'passed','compiler':'passed','json_schema':'passed','unknown_and_uncalibrated_policy':'manual',
            'tampered_resource':'rejected','missing_capability':'rejected','missing_NOR_basis':'rejected_by_schema','premature_conversion':'rejected_by_schema',
            'notice_apply_feedback_boundaries':'compiled_owner_waits','historical_confirmation':'not_rebound_to_new_method',
            'alternate_method':'compiled_same_compiler','judgment_cases':len(cases['cases']),'judgment_groups':{'source_semantics':6,'summary_fidelity':1,'mechanical_gate':5},
            'corpus_revision':2,'corpus_prior_and_audit':'preserved_and_verified',
            'explicit_chat_evidence':'schema_accepts_agent_attested_without_platform_claim',
            'untraceable_or_elevated_confirmation':'rejected_by_schema','real_pi':'not_run','real_jev':'not_run','judgment_quality':'not_validated',
            'conflict_and_stale_confirmation_runtime':'awaiting_engineering_owner',
            'end_to_end':'not_complete'}

if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--rebuild-release',action='store_true');args=p.parse_args()
    if args.rebuild_release:build_lock()
    print(json.dumps(verify_assets(),ensure_ascii=False,indent=2))
