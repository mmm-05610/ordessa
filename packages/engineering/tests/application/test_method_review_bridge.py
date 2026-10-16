"""Real loader/compiler/published SQLite snapshots; explicit synthetic host-admitted check catalog only.

No model/reviewer execution or production method activation is inferred.
"""
from pathlib import Path
from dataclasses import asdict, replace
import hashlib
import json
import pytest
from test_proposal_usecases import _artifact_graph, _draft, _ctx, _proposal_ref, SCOPE, SyntheticAccess
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.proposals import ProposalUseCases
from ordessa_engineering.application.usecases.proposal_closure import resolve_record
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods.definitions.models import MethodSource, CompilationCapabilities, CapabilityDescriptor
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.domain.reviews.models import CriterionSetRef
from ordessa_engineering.domain.reviews.requirements import ReviewRequirementTemplate, TemplateTarget, TemplateCheck, SubjectSelector


def publish(lib,root, *, optional=False, iteration=False, second=False):
    root.mkdir()
    workflow=dict(schema_version=1,entry='done',steps=[dict(id='done',kind='stop',outcome='finished')],stop_outcomes=['finished'],wait_kinds=[],context_slots=['proposal_ref'])
    from ordessa_engineering.methods.definitions.models.identity import method_digest
    check=CapabilityDescriptor('test.bridge.check','check','1.0.0',method_digest('capability-contract',{}),{})
    capabilities=CompilationCapabilities((check,),trust_class='host')
    standard=dict(schema_version=1,standard_id='fixture-standard',revision='2.7.3',purpose='quality',
        criteria=[dict(criterion_id='criterion-a',statement='Required statement from frozen source.',applies_to=['test-document'],required_inputs=['proposal_ref'],checks=[dict(capability_id=check.capability_id,interface_version=check.interface_version,bindings={'iteration':'each_claim'} if iteration else {})],policy=dict(satisfied='manual',violated='block',insufficient='block',unknown='manual')),
            dict(criterion_id='criterion-b',statement='Independent criterion.',applies_to=['test-document'],required=False,blocking=False,checks=[dict(capability_id=check.capability_id,interface_version=check.interface_version,bindings={})],policy=dict(satisfied='manual',violated='block',insufficient='block',unknown='manual'))],
        reduction=dict(required_criteria='all_applicable',empty_applicable_set='error',priority=['block','manual','pass']))
    if not optional:
        standard['criteria'][1].update(required=True,blocking=True)
    resources=[]
    values=[('workflow.main','workflow','workflow.yaml',workflow),('schema.test','document_schema','schema.json',{'type':'object'}),('standard.test','standard','standard.yaml',standard)]
    if second:
        other=dict(standard,standard_id='independent-standard')
        values.append(('standard.independent','standard','independent.yaml',other))
    for identifier,kind,path,value in values:
        raw=json.dumps(value).encode();(root/path).write_bytes(raw)
        resources.append(dict(id=identifier,kind=kind,path=path,media_type='application/schema+json' if kind=='document_schema' else 'application/yaml',sha256=hashlib.sha256(raw).hexdigest()))
    manifest=dict(schema_version=1,method_id='test.real-review-bridge',release_version='3.5.1',compiler_contract='ordessa.methods/v1',entry={'resource':'workflow.main'},resources=resources,documents=[{'document_type':'test-document','schema':{'resource':'schema.test'}}],requires=[{k:getattr(check,k) for k in ('capability_id','kind','interface_version','contract_digest')}])
    (root/'method.yaml').write_text(json.dumps(manifest))
    loaded=load_method(MethodSource(root),FileResourceReader());assert loaded.ok,loaded.error
    compiled=compile_method(loaded.value,capabilities,'test.real-compiler/1');assert compiled.ok,compiled.error
    class Catalog:
        # Test-only original host admission; not a production check executor.
        def read_current(self):return capabilities
    store=SQLiteSnapshotStore(lib)
    frozen=freeze_method(compiled.value,store,store,capability_catalog=Catalog());assert frozen.ok,frozen.error
    # Read through the actual stored-source integrity reconstruction.
    snapshot=store.get(frozen.value.ref)
    return snapshot,root


@pytest.fixture
def env(tmp_path,request):
    options=getattr(request,'param',{})
    lib=EngineeringLibrary.create((tmp_path/'bridge.sqlite').resolve(),library_id='review-bridge',schema_version=7)
    factory=SQLiteUoWFactory(lib)
    snapshot,source=publish(lib,tmp_path/'source',**options)
    r=snapshot.ref;method=MethodRef(r.method_id,r.release_version,r.schema_version,Digest('sha256',r.snapshot_digest))
    base,target,claim=_artifact_graph(factory)
    draft=_draft(method,base,target,claim)
    slot=TemplateTarget('primary',SubjectSelector('self_proposal'))
    standards=snapshot.program.standard_definitions
    templates=[]
    for s in standards:
        required=tuple(c.criterion_id for c in s.criteria if c.required is not False)
        templates.append(ReviewRequirementTemplate(SCOPE,'template-'+s.standard_id,1,s.purpose,(slot,),method,
            CriterionSetRef(s.standard_id,1,Digest('sha256',s.resource_ref.sha256)),tuple(TemplateCheck(slot,k) for k in required),('reviewer',),'review-phase'))
    draft['review_requirement_templates']=[asdict(t) for t in templates]
    result=ProposalUseCases(factory,SyntheticAccess()).create(dict(change_id=None,expected_version=0,draft=draft),_ctx())
    ref=_proposal_ref(result.result['proposal_ref'])
    with factory.begin(SCOPE,'read') as uow:
        p=uow.proposals.get_proposal(ref)
        reqs=resolve_record(p,uow.proposals,uow.proposals.validated_budget())
        revisions=uow.proposals.resolve_revision_graph((target,base),uow.proposals.validated_budget())
        owners=(uow.engineering.get_artifact('artifact-1'),)
    primary=Target('primary',p.ref)
    bindings=EngineeringTargetBindings(SCOPE,TargetSet((primary,)),((primary,'test-document'),),('proposal_ref',),('reviewer',),'review-phase')
    try:yield dict(snapshot=snapshot,source=source,bindings=bindings,proposal=p,artifacts=owners,revisions=revisions,requirements=reqs)
    finally:lib.close()


def rebind(e,p):
    target=Target('primary',p.ref)
    return replace(e['bindings'],targets=TargetSet((target,)),document_types=((target,'test-document'),))


def proposal_arguments(e):
    return {k:e[k] for k in ('proposal','artifacts','revisions')}


def test_actual_snapshot_produces_complete_plans_and_preserves_expanded_identity(env):
    bridge=MethodBridge()
    pure=bridge.review_requirements(env['snapshot'],env['bindings'])
    actual=bridge.review_requirements(env['snapshot'],env['bindings'],**proposal_arguments(env))
    assert actual==env['requirements'] and actual[0].requirement_id!=pure[0].requirement_id
    plan=bridge.review_plan(env['snapshot'],env['bindings'],actual[0],'review-1',**proposal_arguments(env))
    assert len(plan.check_policies)==2
    assert {p.key.criterion_id for p in plan.check_policies}=={'criterion-a','criterion-b'}
    assert plan.requirement==actual[0]
    assert env['snapshot'].program.standard_definitions[0].revision=='2.7.3'
    assert all(c.policy.satisfied=='manual' for c in env['snapshot'].program.standard_definitions[0].criteria)
    # Changing live source cannot alter the already published standard.
    (env['source']/'standard.yaml').write_text('invalid latest contents')
    assert bridge.review_requirements(env['snapshot'],env['bindings'],**proposal_arguments(env))==actual

@pytest.mark.parametrize('env',[{'optional':True}],indirect=True)
def test_optional_criterion_remains_in_plan_not_required_subset(env):
    r=MethodBridge().review_requirements(env['snapshot'],env['bindings'])[0]
    plan=MethodBridge().review_plan(env['snapshot'],env['bindings'],r,'optional')
    assert len(r.required_check_keys)==1 and len(plan.check_keys)==2
    assert next(p for p in plan.check_policies if p.key.criterion_id=='criterion-b').required is False

@pytest.mark.parametrize('env',[{'second':True}],indirect=True)
def test_omitting_whole_frozen_standard_is_refused(env):
    p=replace(env['proposal'],review_requirement_templates=env['proposal'].review_requirement_templates[:1])
    with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
        MethodBridge().review_requirements(env['snapshot'],rebind(env,p),proposal=p,artifacts=env['artifacts'],revisions=env['revisions'])


def test_missing_slots_unknown_types_and_requirement_subset_refuse(env):
    bridge=MethodBridge()
    with pytest.raises(ApplicationError,match='METHOD_INPUT_SLOT_UNAVAILABLE'):
        bridge.review_requirements(env['snapshot'],replace(env['bindings'],input_slots=()))
    target=env['bindings'].targets.targets[0]
    with pytest.raises(ApplicationError,match='METHOD_DOCUMENT_TYPE_UNAVAILABLE'):
        bridge.review_requirements(env['snapshot'],replace(env['bindings'],document_types=((target,'unknown-type'),)))
    r=bridge.review_requirements(env['snapshot'],env['bindings'])[0]
    with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
        bridge.review_plan(env['snapshot'],env['bindings'],replace(r,required_check_keys=r.required_check_keys[:1]),'bad')

@pytest.mark.parametrize('env',[{'iteration':True}],indirect=True)
def test_unimplemented_claim_iteration_refuses_without_collapsing(env):
    with pytest.raises(ApplicationError,match='METHOD_CHECK_ITERATION_UNAVAILABLE'):
        MethodBridge().review_requirements(env['snapshot'],env['bindings'])


def test_same_standard_id_with_wrong_resource_digest_refuses(env):
    p=env['proposal'];t=p.review_requirement_templates[0]
    changed=replace(t,criterion_set_ref=replace(t.criterion_set_ref,digest=Digest('sha256','b'*64)))
    p=replace(p,review_requirement_templates=(changed,))
    with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
        MethodBridge().review_requirements(env['snapshot'],rebind(env,p),proposal=p,artifacts=env['artifacts'],revisions=env['revisions'])


def test_proposal_cannot_drop_single_required_criterion(env):
    p=env['proposal'];t=p.review_requirement_templates[0]
    p=replace(p,review_requirement_templates=(replace(t,required_check_keys=t.required_check_keys[:1]),))
    with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
        MethodBridge().review_requirements(env['snapshot'],rebind(env,p),proposal=p,artifacts=env['artifacts'],revisions=env['revisions'])


def test_binding_scope_and_incomplete_type_map_are_rejected(env):
    from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
    from ordessa_engineering.domain.common.models.identity import Scope
    with pytest.raises(ReferenceError,match='REALM_MISMATCH'):
        replace(env['bindings'],scope=Scope('another-realm','another-project'))
    with pytest.raises(ReferenceError,match='INCOMPLETE_BATCH'):
        replace(env['bindings'],document_types=())


def test_binding_role_order_is_deterministic_and_still_only_captured_policy(env):
    b1=replace(env['bindings'],eligible_reviewer_roles=('reviewer','auditor'))
    b2=replace(env['bindings'],eligible_reviewer_roles=('auditor','reviewer'))
    assert b1==b2
    assert MethodBridge().review_requirements(env['snapshot'],b1)==MethodBridge().review_requirements(env['snapshot'],b2)
    # This is value conversion; original reviewer authority must authenticate
    # either role before producing admissible evidence or holding its guard.
