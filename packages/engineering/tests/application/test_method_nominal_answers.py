"""Real immutable nominal snapshots: legacy gating and method-owned policy.

No real provider or authenticated source is invented by these mechanism tests.
"""
from dataclasses import replace
import json
import hashlib
import shutil
import yaml
import pytest
from test_method_per_claim import ROOT, published, revision, binding
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.orchestration.method_answers import (
    nominal_criterion_answer, nominal_decision_answer,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer
from ordessa_engineering.application.usecases.reviews.admission import review_observations
from ordessa_engineering.methods.definitions.models.compiled import freeze_value, thaw_value, DecisionPolicySpec
from ordessa_engineering.methods.validation.nominal import nominal_declaration_error
from ordessa_engineering.methods import validate_method, compile_method
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, CapabilityDescriptor, MethodSource
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.domain.common.models.values import Digest

SOURCE = ROOT/'candidates/2.3.0'
CURRENT_SOURCE = ROOT/'candidates/2.6.0'
CASES = json.loads((SOURCE/'tests/nominal-cases.json').read_bytes())['cases']


def current_capabilities(root=CURRENT_SOURCE, *, trust_class='fixture'):
    # Actual owner descriptor functions are isolated test inputs, never a host
    # registration or a claim that the candidate has been published.
    from ordessa_engineering.application.api import EngineeringService
    from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
    from ordessa_engineering.application.orchestration.check_capabilities import (
        mechanical_review_check_capabilities, invariant_review_check_capabilities,
    )
    from ordessa_engineering.application.orchestration.decision_checks import generic_decision_check_capability
    available = (*EngineeringService.operation_capabilities().capabilities,
        *owner_capabilities(), *mechanical_review_check_capabilities().capabilities,
        *invariant_review_check_capabilities().capabilities, generic_decision_check_capability())
    requirements = yaml.safe_load((root/'method.yaml').read_bytes())['requires']
    descriptors = []
    for requirement in requirements:
        matches = [item for item in available if
            (item.capability_id,item.kind,item.interface_version,item.contract_digest) ==
            (requirement['capability_id'],requirement['kind'],requirement['interface_version'],requirement['contract_digest'])]
        assert len(matches) == 1, requirement['capability_id']
        descriptors.append(matches[0])
    return CompilationCapabilities(tuple(descriptors), 'isolated-nominal-test-owner-descriptors', trust_class)


def current_snapshot(library):
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
    from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
    # Host trust is explicitly supplied only by this test's in-process Catalog.
    # There is no product MethodRef, candidate bundle lock, or release claim.
    caps = current_capabilities(trust_class='host')
    loaded = load_method(MethodSource(CURRENT_SOURCE), FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, caps, 'test.nominal78/1')
    assert compiled.ok, compiled.error
    class Catalog:
        def read_current(self): return caps
    store = SQLiteSnapshotStore(library)
    frozen = freeze_method(compiled.value, store, store, capability_catalog=Catalog())
    assert frozen.ok, frozen.error
    return store.get(frozen.value.ref)


@pytest.fixture
def nominal(tmp_path):
    lib = EngineeringLibrary.create((tmp_path/'nominal.sqlite').resolve(),library_id='nominal',schema_version=7)
    try:
        snapshot = published(lib,SOURCE)
        r = revision(); bindings = binding((r,)); bridge = MethodBridge()
        requirements = bridge.review_requirements(snapshot,bindings,revisions=(r,))
        req = next(q for q in requirements if q.criterion_set_ref.criterion_set_id=='source-review')
        plan = bridge.review_plan(snapshot,bindings,req,'nominal',revisions=(r,))
        standard = next(s for s in snapshot.program.standard_definitions if s.standard_id=='source-review')
        key = next(k for k in plan.check_keys if k.criterion_id=='claim_support')
        yield lib,snapshot,plan,standard,key
    finally: lib.close()


@pytest.fixture
def current_nominal(tmp_path):
    lib = EngineeringLibrary.create((tmp_path/'nominal-26.sqlite').resolve(),
        library_id='nominal-26', schema_version=7)
    try:
        snapshot = current_snapshot(lib)
        r = revision(); bindings = binding((r,)); bridge = MethodBridge()
        requirements = bridge.review_requirements(snapshot, bindings, revisions=(r,))
        req = next(q for q in requirements if q.criterion_set_ref.criterion_set_id=='source-review')
        plan = bridge.review_plan(snapshot, bindings, req, 'nominal-26', revisions=(r,))
        standard = next(s for s in snapshot.program.standard_definitions if s.standard_id=='source-review')
        key = next(k for k in plan.check_keys if k.criterion_id=='claim_support')
        yield lib, snapshot, plan, standard, key
    finally:
        lib.close()


@pytest.fixture
def current_quality(tmp_path):
    lib = EngineeringLibrary.create((tmp_path/'quality-26.sqlite').resolve(),
        library_id='quality-26', schema_version=7)
    try:
        snapshot = current_snapshot(lib)
        r = revision(); bindings = binding((r,)); bridge = MethodBridge()
        requirements = bridge.review_requirements(snapshot, bindings, revisions=(r,))
        req = next(q for q in requirements if q.criterion_set_ref.criterion_set_id=='quality-review')
        plan = bridge.review_plan(snapshot, bindings, req, 'quality-26', revisions=(r,))
        standard = next(s for s in snapshot.program.standard_definitions if s.standard_id=='quality-review')
        score_key = next(k for k in plan.check_keys if k.criterion_id=='semantic_consistency')
        noul_key = next(k for k in plan.check_keys if k.criterion_id=='semantic_drift')
        yield lib, snapshot, plan, standard, score_key, noul_key
    finally:
        lib.close()


def resolve(plan,standard,key,**changes):
    args = dict(selected_option='supported',selection_status='unique',answer_complete=True,input_truncated=False)
    args.update(changes)
    return nominal_criterion_answer(plan,standard,key,**args)


def projected(plan,standard,resolution):
    answers = tuple(resolution.answer if k==resolution.answer.check_key else
        CriterionAnswer(k,'satisfied',(),'test-only admitted semantic status') for k in plan.check_keys)
    return next(o for o in review_observations(plan,standard,answers) if o.check_key==resolution.answer.check_key)


@pytest.mark.parametrize('case',[c['id'] for c in CASES])
def test_candidate_nominal_counterexamples(nominal,case):
    lib,snapshot,plan,standard,key = nominal
    if case=='three-valid-options':
        for option,status in [('supported','satisfied'),('contradicted','violated'),('insufficient','insufficient')]:
            resolved = resolve(plan,standard,key,selected_option=option)
            assert resolved.answer.status==status
            assert resolved.quality_disposition=='manual'
            assert resolved.quality_reason=='MODEL_EVALUATION_UNAVAILABLE'
            assert projected(plan,standard,resolved).result=='indeterminate'
        return
    cases = {'tie':dict(selection_status='tie',selected_option=None),
        'missing-answer':dict(selection_status='missing',selected_option=None),
        'partial-answer':dict(answer_complete=False),
        'truncated-input':dict(input_truncated=True),
        'unmapped-option':dict(selected_option='undeclared')}
    if case in cases:
        resolved = resolve(plan,standard,key,**cases[case])
        assert resolved.answer.status=='unknown' and resolved.quality_disposition=='manual'
        assert projected(plan,standard,resolved).result=='indeterminate'
        return
    if case=='wrong-ref-or-shape':
        with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
            resolve(plan,replace(standard,resource_ref=replace(standard.resource_ref,sha256='b'*64)),key)
        with pytest.raises(ApplicationError,match='REVIEW_SOURCE_INVALID'):
            resolve(plan,standard,key,answer_complete='true')
        return
    if case in ('incomplete-option-map','decision-policy-conflict'):
        criterion = next(c for c in standard.criteria if c.criterion_id=='claim_support')
        bindings = thaw_value(criterion.checks[0].bindings)
        if case=='incomplete-option-map':
            del bindings['nominal_answer_conversion']['option_statuses']['supported']
            assert nominal_declaration_error(bindings,'choice',('supported','contradicted','insufficient'))=='NOMINAL_OPTION_MAP_INVALID'
            changed = replace(criterion,checks=(replace(criterion.checks[0],bindings=freeze_value(bindings)),))
        else:
            # This captured declaration claims no qualified calibration; the
            # public runtime must refuse any competing probability policy.
            policy = DecisionPolicySpec(calibration_profile_id='explicit-unqualified-test-declaration',
                activation='matching_validated_evaluation_required',missing_evaluation='manual',truncation='unknown')
            changed = replace(criterion,decision_policy=policy)
        changed_standard = replace(standard,criteria=tuple(changed if c==criterion else c for c in standard.criteria))
        with pytest.raises(ApplicationError): resolve(plan,changed_standard,key)
        return
    if case=='old-snapshot':
        for root in (ROOT,ROOT/'candidates/2.2.0'):
            old = published(lib,root)
            old_standard = next(s for s in old.program.standard_definitions if s.standard_id=='source-review')
            # This is only the exact-standard pure projection boundary: an old
            # declaration cannot inherit a new mapping from latest files.
            old_req = replace(plan.requirement,criterion_set_ref=replace(plan.requirement.criterion_set_ref,
                digest=Digest('sha256',old_standard.resource_ref.sha256)))
            old_plan = replace(plan,requirement=old_req)
            result = resolve(old_plan,old_standard,key)
            assert result.answer.status=='unknown' and result.classification_reason=='NOMINAL_MAPPING_UNAVAILABLE'
        return
    result = resolve(plan,standard,key)
    assert result.answer.status=='satisfied'
    assert result.quality_disposition=='manual' and result.quality_reason=='MODEL_EVALUATION_UNAVAILABLE'
    assert projected(plan,standard,result).result=='indeterminate'
    if case=='no-kind-exemption':
        assert {k.claim_id for k in plan.check_keys if k.criterion_id=='claim_support'}=={'C1','C2'}
    if case=='source-provenance':
        assert not hasattr(result,'reviewer_evidence') and not hasattr(result,'grant')


def test_source_or_method_cannot_promote_nominal_status_to_pass(nominal):
    _,_,plan,standard,key = nominal
    criterion = next(c for c in standard.criteria if c.criterion_id=='claim_support')
    changed = replace(criterion,policy=replace(criterion.policy,satisfied='pass'))
    standard = replace(standard,criteria=tuple(changed if c==criterion else c for c in standard.criteria))
    result = resolve(plan,standard,key)
    assert result.quality_disposition=='manual'
    assert projected(plan,standard,result).result=='indeterminate'


@pytest.mark.parametrize('option,status',[
    ('supported','satisfied'),('contradicted','violated'),('insufficient','insufficient'),
])
def test_current_method_nominal_answer_uses_its_frozen_disposition(current_nominal, option, status):
    _, _, plan, standard, key = current_nominal
    criterion = next(c for c in standard.criteria if c.criterion_id=='claim_support')
    bindings = thaw_value(criterion.checks[0].bindings)
    assert 'quality_admission' not in bindings
    resolved = resolve(plan, standard, key, selected_option=option)
    assert resolved.answer.status == status
    expected = getattr(criterion.policy, status)
    assert resolved.quality_disposition == expected
    if option == 'supported':
        assert expected == 'pass'
    elif option == 'contradicted':
        assert expected == 'block'
    expected_result = {'pass':'pass', 'block':'fail', 'manual':'indeterminate',
                       'insufficient':'indeterminate'}[expected]
    assert projected(plan, standard, resolved).result == expected_result


def test_current_method_nominal_answer_rejects_wrong_version(current_nominal):
    _, _, plan, standard, key = current_nominal
    wrong = replace(standard, resource_ref=replace(standard.resource_ref, sha256='b' * 64))
    with pytest.raises(ApplicationError, match='METHOD_REQUIREMENTS_CHANGED'):
        resolve(plan, wrong, key)


@pytest.mark.parametrize('option,status,disposition',[
    ('conflicting','violated','block'),('partial','insufficient','block'),('complete','satisfied','pass'),
])
def test_current_quality_choice_uses_exact_method_disposition(current_quality, option, status, disposition):
    _, _, plan, standard, key, _ = current_quality
    resolved = nominal_decision_answer(plan, standard, key, answer_kind='choice', answer_value=option, selection_status='unique',
        answer_complete=True, input_truncated=False)
    assert resolved.answer.status == status
    assert resolved.quality_disposition == disposition
    expected = {'pass':'pass', 'block':'fail', 'manual':'indeterminate',
                'insufficient':'indeterminate'}[disposition]
    assert next(o for o in review_observations(plan, standard,
        tuple(resolved.answer if k == key else CriterionAnswer(k, 'satisfied', (), 'fixture')
              for k in plan.check_keys)) if o.check_key == key).result == expected


@pytest.mark.parametrize('value',[0, 1, 2, 1.0, True, -1, 3])
def test_old_score_numeric_value_cannot_select_new_choice(current_quality, value):
    _, _, plan, standard, key, _ = current_quality
    resolved = nominal_decision_answer(plan, standard, key, answer_kind='score', answer_value=value,
        answer_complete=True, input_truncated=False)
    assert resolved.answer.status == 'unknown'
    assert next(o for o in review_observations(plan, standard,
        tuple(resolved.answer if k == key else CriterionAnswer(k, 'satisfied', (), 'fixture')
              for k in plan.check_keys)) if o.check_key == key).result != 'pass'


@pytest.mark.parametrize('value,status,disposition',[('drift_detected','violated','block'),('no_drift_detected','satisfied','pass')])
def test_current_drift_choice_uses_explicit_semantic_options(current_quality, value, status, disposition):
    _, _, plan, standard, _, key = current_quality
    resolved = nominal_decision_answer(plan, standard, key, answer_kind='choice', answer_value=value, selection_status='unique',
        answer_complete=True, input_truncated=False)
    assert resolved.answer.status == status
    assert resolved.quality_disposition == disposition


@pytest.mark.parametrize('value',[True, False, 0, 1, 0.0, 'true', None])
def test_old_noul_numeric_or_boolean_value_cannot_select_new_choice(current_quality, value):
    _, _, plan, standard, _, key = current_quality
    resolved = nominal_decision_answer(plan, standard, key, answer_kind='noul', answer_value=value,
        answer_complete=True, input_truncated=False)
    assert resolved.answer.status == 'unknown'
    assert resolved.quality_disposition == 'manual'


def test_v2_choice_uses_exact_option_ids_and_common_unknowns(current_nominal):
    _, _, plan, standard, key = current_nominal
    criterion = next(c for c in standard.criteria if c.criterion_id == 'claim_support')
    bindings = thaw_value(criterion.checks[0].bindings)
    old = bindings['nominal_answer_conversion']
    bindings['nominal_answer_conversion'] = {
        'contract_version': 'ordessa.nominal-answer-status/2',
        'answer_kind': 'choice',
        'option_statuses': dict(old['option_statuses']),
        'tie': 'unknown', 'missing_answer': 'unknown',
        'incomplete_answer': 'unknown', 'truncated_input': 'unknown',
        'unmapped_answer': 'unknown',
    }
    changed = replace(criterion, checks=(replace(criterion.checks[0],
        bindings=freeze_value(bindings)),))
    changed_standard = replace(standard, criteria=tuple(
        changed if c == criterion else c for c in standard.criteria))
    resolved = nominal_decision_answer(plan, changed_standard, key,
        answer_kind='choice', answer_value='supported', selection_status='unique',
        answer_complete=True, input_truncated=False)
    assert resolved.answer.status == 'satisfied'
    assert resolved.quality_disposition == 'pass'
    tied = nominal_decision_answer(plan, changed_standard, key,
        answer_kind='choice', answer_value=None, selection_status='tie',
        answer_complete=True, input_truncated=False)
    assert tied.answer.status == 'unknown'
    assert projected(plan, changed_standard, tied).result != 'pass'


@pytest.mark.parametrize('changes',[
    {'selection_status':'tie','selected_option':None},
    {'selection_status':'missing','selected_option':None},
    {'answer_complete':False},
    {'input_truncated':True},
    {'selected_option':'unmapped'},
])
def test_current_method_unknown_nominal_inputs_never_pass(current_nominal, changes):
    _, _, plan, standard, key = current_nominal
    resolved = resolve(plan, standard, key, **changes)
    assert resolved.answer.status == 'unknown'
    assert projected(plan, standard, resolved).result != 'pass'


def test_choice_contract_does_not_accept_unverified_selected_alias(current_nominal):
    _, _, plan, standard, key = current_nominal
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_INVALID'):
        nominal_criterion_answer(plan, standard, key, selected_option='supported',
            selection_status='selected', answer_complete=True, input_truncated=False)
    generic = nominal_decision_answer(plan, standard, key, answer_kind='choice',
        answer_value='supported', selection_status='selected', answer_complete=True,
        input_truncated=False)
    assert generic.answer.status == 'unknown'


@pytest.mark.parametrize('status',['satisfied','violated','insufficient','unknown'])
def test_admission_independently_keeps_all_nominal_quality_manual(nominal,status):
    # No caller-provided model/evaluation flags are accepted. Missing the exact
    # original owners must also prevent an unqualified negative quality verdict.
    _,_,plan,standard,key = nominal
    answers = tuple(CriterionAnswer(k,status,(),'explicit unqualified semantic status') for k in plan.check_keys)
    observations = review_observations(plan,standard,answers)
    assert all(o.result=='indeterminate' for o in observations if o.check_key.criterion_id=='claim_support')


@pytest.mark.parametrize('mutation,code',[
    ('missing-option','NOMINAL_OPTION_MAP_INVALID'),
    ('extra-option','NOMINAL_OPTION_MAP_INVALID'),
    ('missing-quality',None),
    ('wrong-quality','NOMINAL_QUALITY_ADMISSION_REQUIRED'),
    ('null-quality','NOMINAL_QUALITY_ADMISSION_REQUIRED'),
    ('quality-only','NOMINAL_CONVERSION_INVALID'),
    ('unknown-pass','NOMINAL_CONVERSION_INVALID'),
    ('threshold-in-nominal','NOMINAL_CONVERSION_INVALID'),
    ('probability-conflict','NOMINAL_PROBABILITY_POLICY_CONFLICT'),
])
def test_actual_loader_validates_nominal_declarations(tmp_path,mutation,code):
    root = tmp_path/'method'
    shutil.copytree(SOURCE,root,ignore=shutil.ignore_patterns('bundle-lock.json'))
    manifest = yaml.safe_load((root/'method.yaml').read_bytes())
    declaration = next(r for r in manifest['resources'] if r['id']=='standard.source_review')
    path = root/declaration['path'];value = yaml.safe_load(path.read_bytes())
    criterion = next(c for c in value['criteria'] if c['criterion_id']=='claim_support')
    bindings = criterion['checks'][0]['bindings']; conversion = bindings['nominal_answer_conversion']
    if mutation=='missing-option': del conversion['option_statuses']['supported']
    elif mutation=='extra-option': conversion['option_statuses']['intruder']='satisfied'
    elif mutation=='missing-quality': del bindings['quality_admission']
    elif mutation=='unknown-pass': conversion['tie']='satisfied'
    elif mutation=='threshold-in-nominal': conversion['minimum_selected_probability']='0'
    elif mutation=='wrong-quality': bindings['quality_admission']['missing_evaluation']='pass'
    elif mutation=='null-quality': bindings['quality_admission']=None
    elif mutation=='quality-only': del bindings['nominal_answer_conversion']
    else:
        criterion['decision_policy']={'calibration_profile_id':'test-only-unactivated',
            'activation':'matching_validated_evaluation_required','missing_evaluation':'manual',
            'truncation':'unknown','minimum_selected_probability':'0.5','selected_option':'supported',
            'option_statuses':{'supported':'threshold_dependent','contradicted':'violated','insufficient':'insufficient'},
            'below_threshold':'manual'}  # Captured fixture declaration, never activated.
    raw = yaml.safe_dump(value,sort_keys=False).encode();path.write_bytes(raw)
    declaration['sha256']=hashlib.sha256(raw).hexdigest()
    (root/'method.yaml').write_text(yaml.safe_dump(manifest,sort_keys=False))
    loaded = load_method(MethodSource(root),FileResourceReader());assert loaded.ok,loaded.error
    rows = json.loads((root/'contracts/capability-catalog.json').read_bytes())['capabilities']
    caps = CompilationCapabilities(tuple(CapabilityDescriptor(r['capability_id'],r['kind'],r['interface_version'],r['contract_digest'],r['contract']) for r in rows),trust_class='fixture')
    report = validate_method(loaded.value,caps)
    if code is None:
        assert report.valid, report.diagnostics
    else:
        assert not report.valid and code in {d.code for d in report.diagnostics}


@pytest.mark.parametrize('mutation,code',[
    ('wrong-kind','NOMINAL_ANSWER_KIND_MISMATCH'),
    ('non-contiguous-score','ANSWER_VOCABULARY_INVALID'),
    ('incomplete-score-map','NOMINAL_LEVEL_MAP_INVALID'),
    ('null-noul-value','NOMINAL_BOOLEAN_MAP_INVALID'),
    ('unknown-noul-status','NOMINAL_BOOLEAN_MAP_INVALID'),
    ('int-noul-value','NOMINAL_BOOLEAN_MAP_INVALID'),
])
def test_actual_v2_loader_rejects_invalid_typed_maps(tmp_path, mutation, code):
    root = tmp_path/'method-26'
    shutil.copytree(CURRENT_SOURCE, root, ignore=shutil.ignore_patterns('bundle-lock.json'))
    manifest = yaml.safe_load((root/'method.yaml').read_bytes())
    declaration = next(row for row in manifest['resources']
                       if row['path']=='standards/quality-review.yaml')
    path = root/declaration['path']
    value = yaml.safe_load(path.read_bytes())
    score = next(c for c in value['criteria'] if c['criterion_id']=='semantic_consistency')
    noul = next(c for c in value['criteria'] if c['criterion_id']=='semantic_drift')
    score['answer_vocabulary'] = {'kind':'score', 'levels':[
        {'level_id':name,'index':index,'description':name} for index,name in enumerate(('conflicting','partial','complete'))]}
    noul['answer_vocabulary'] = {'kind':'noul','true_description':'has drift','false_description':'no drift'}
    common = {'contract_version':'ordessa.nominal-answer-status/2', 'tie':'unknown',
        'missing_answer':'unknown','incomplete_answer':'unknown','truncated_input':'unknown','unmapped_answer':'unknown'}
    score_mapping = dict(common, answer_kind='score', level_statuses={
        'conflicting':'violated','partial':'insufficient','complete':'satisfied'})
    noul_mapping = dict(common, answer_kind='noul', boolean_statuses=[
        {'value':True,'status':'violated'},{'value':False,'status':'satisfied'}])
    score['checks'][0]['bindings']['nominal_answer_conversion'] = score_mapping
    noul['checks'][0]['bindings']['nominal_answer_conversion'] = noul_mapping
    if mutation=='wrong-kind': score_mapping['answer_kind']='noul'
    elif mutation=='non-contiguous-score':
        value['criteria'][next(i for i,c in enumerate(value['criteria'])
            if c['criterion_id']=='semantic_consistency')]['answer_vocabulary']['levels'][1]['index']=4
    elif mutation=='incomplete-score-map': del score_mapping['level_statuses']['partial']
    elif mutation=='null-noul-value': noul_mapping['boolean_statuses'][0]['value']=None
    elif mutation=='unknown-noul-status': noul_mapping['boolean_statuses'][0]['status']='pass'
    elif mutation=='int-noul-value': noul_mapping['boolean_statuses'][0]['value']=1
    raw = yaml.safe_dump(value,sort_keys=False).encode()
    path.write_bytes(raw)
    declaration['sha256']=hashlib.sha256(raw).hexdigest()
    (root/'method.yaml').write_text(yaml.safe_dump(manifest,sort_keys=False))
    loaded = load_method(MethodSource(root),FileResourceReader())
    assert loaded.ok, loaded.error
    report = validate_method(loaded.value, current_capabilities(root))
    assert not report.valid and code in {diagnostic.code for diagnostic in report.diagnostics}


def test_source_phase_uses_exact_workflow_standard_without_fake_implementation_slot(nominal):
    lib, snapshot, plan, standard, key = nominal
    r = revision()
    bound = replace(binding((r,)), phase_key='source_review', workflow_node_id='source_review',
        input_slots=('source_captures', 'claim_bindings', 'method_content', 'proposal_ref'))
    requirements = MethodBridge().review_requirements(snapshot, bound, revisions=(r,))
    assert {q.criterion_set_ref.criterion_set_id for q in requirements} == {'source-review'}
    assert all(q.phase_key == 'source_review' for q in requirements)
    # Aggregate analysis preserves its existing full-standard assertions; it is
    # not a current-work phase attestation or a production request source.
    aggregate = MethodBridge().review_requirements(snapshot, binding((r,)), revisions=(r,))
    assert {q.criterion_set_ref.criterion_set_id for q in aggregate} == {'source-review', 'quality-review'}
    quality = replace(bound, phase_key='quality_review', workflow_node_id='quality_review')
    with pytest.raises(ApplicationError, match='METHOD_INPUT_SLOT_UNAVAILABLE'):
        MethodBridge().review_requirements(snapshot, quality, revisions=(r,))


@pytest.mark.parametrize('failure', ['node', 'digest', 'duplicate', 'missing'])
def test_exact_workflow_review_phase_rejects_substitution(nominal, failure):
    lib, snapshot, plan, standard, key = nominal
    r = revision()
    bound = replace(binding((r,)), phase_key='source_review', workflow_node_id='source_review')
    program = snapshot.program
    if failure == 'node':
        bound = replace(bound, phase_key='await_notice', workflow_node_id='await_notice')
        code = 'METHOD_REVIEW_PHASE_UNAVAILABLE'
    else:
        node = next(n for n in program.workflow.steps if n.id == 'source_review')
        config = thaw_value(node.config)
        if failure == 'digest': config['standards'][0]['sha256'] = '0' * 64
        elif failure == 'duplicate': config['standards'] += config['standards']
        else: del config['standards']
        changed = replace(node, config=freeze_value(config))
        program = replace(program, workflow=replace(program.workflow,
            steps=tuple(changed if n == node else n for n in program.workflow.steps)))
        snapshot = replace(snapshot, program=program)
        code = 'METHOD_PHASE_STANDARDS_UNAVAILABLE'
    with pytest.raises(ApplicationError, match=code):
        MethodBridge().review_requirements(snapshot, bound, revisions=(r,))


def test_aggregate_analysis_is_not_production_workflow_phase(nominal):
    lib, snapshot, plan, standard, key = nominal
    r = revision()
    with pytest.raises(ApplicationError, match='METHOD_REVIEW_PHASE_UNAVAILABLE'):
        MethodBridge().require_workflow_phase(snapshot, binding((r,)))
    bound = replace(binding((r,)), phase_key='source_review', workflow_node_id='source_review')
    MethodBridge().require_workflow_phase(snapshot, bound)
