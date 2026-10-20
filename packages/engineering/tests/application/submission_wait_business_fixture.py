"""Actual SQLite closure with explicitly synthetic consent/native history.

No closure, repository or Work source is patched. The alternate method is
compiled/frozen by the real mechanism; it is not a published product method.
"""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from urllib.parse import urljoin

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.method_work import SQLitePersistedMethodWorkSource
from ordessa_engineering.adapters.review_sources import ConfiguredReviewPhase, SQLiteReviewBindings
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.api import EngineeringService
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.run_waits import run_wait_row_digest
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.application.orchestration.method_content import document_spec
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.application.usecases.proposal_closure import validate_create
from ordessa_engineering.application.usecases.changes.acceptance_closure import resolve_submission_acceptance
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, MethodPayload, MethodContent
from ordessa_engineering.domain.artifacts.method_binding import MethodRef, ExactMethodResourceRef
from ordessa_engineering.domain.changes.models import Proposal, Change, ChangeSet, Mutation
from ordessa_engineering.domain.changes.submission import SubmissionCoverage
from ordessa_engineering.domain.approvals.consent import ConversationNotice, ConsentChallenge, ApprovalGrant
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.models import CriterionSetRef
from ordessa_engineering.domain.reviews.requirements import (
    ReviewRequirementTemplate, TemplateTarget, TemplateCheck, SubjectSelector,
)
from ordessa_engineering.methods import load_method, compile_method
from ordessa_engineering.methods.definitions.models import MethodSource, CapabilityDescriptor, CompilationCapabilities, thaw_value
from ordessa_engineering.methods.definitions.models.identity import method_digest
from test_method_control_admission import TestManagement
from test_proposal_usecases import SyntheticAccess
from submission_wait_native_fixture import persist_historical_dispatch


def _frozen_method(tmp_path, library, *, report_phase=False, authorship_policy=None):
    root = tmp_path / 'submission-wait-method'
    root.mkdir()
    check = CapabilityDescriptor('test.bridge.check', 'check', '1.0.0', method_digest('capability-contract', {}), {})
    request = next(d for d in EngineeringService.operation_capabilities().capabilities if d.capability_id == 'engineering.reviews.request')
    report = (next(d for d in EngineeringService.operation_capabilities().capabilities
                   if d.capability_id == 'engineering.submissions.record_report')
              if report_phase else None)
    dispatch = next(d for d in owner_capabilities() if d.capability_id == 'engineering.executions.dispatch')
    caps = CompilationCapabilities((check, request, dispatch, *((report,) if report_phase else ())), trust_class='host')
    review_config = lambda purpose, standard: {'purpose': purpose, 'standards': [{'resource': standard}]}
    workflow = {'schema_version': 1, 'workflow_id': 'submission-wait-fixture', 'entry': 'await_proposal',
        'resume_contract': 'ordessa.engineering.current-work/1',
        'context_slots': ['proposal_ref','work_inputs','method_ref','package_ref','acceptance_plan'],
        'wait_kinds': [], 'stop_outcomes': ['finished'], 'steps': [
            {'id':'await_proposal','kind':'wait','event':'engineering.work.current_condition','next':'quality_review'},
            {'id':'quality_review','kind':'operation','operation':'engineering.reviews.request',
             'config':review_config('quality','standard.quality'), 'outcomes':{'completed':{'next':'dispatch'},'rejected':{'stop':'finished'}}},
            {'id':'dispatch','kind':'operation','operation':'engineering.executions.dispatch',
             'config':{'package_slot':'package_ref'}, 'outcomes':{'completed':{'next':'await_acceptance'},'failed':{'stop':'finished'},'unknown':{'stop':'finished'}}},
            {'id':'await_acceptance','kind':'wait','event':'engineering.work.current_condition','next':'acceptance_review'},
            {'id':'acceptance_review','kind':'operation','operation':'engineering.reviews.request',
             'config':{**review_config('acceptance','standard.acceptance'),
                 **({'unit_submission_review_strategy':{'roles':{'identity_constraint':authorship_policy}}}
                    if authorship_policy is not None else {})},
             'outcomes':{'completed':{'next':'record_report' if report_phase else 'done'},'rejected':{'stop':'finished'}}},
            *([{'id':'record_report','kind':'operation','operation':'engineering.submissions.record_report',
                'config':{'report_mode_boundary':{'method_content_schema':'schema.test'}},
                'outcomes':{'completed':{'next':'done'},'rejected':{'stop':'finished'}}}]
              if report_phase else []),
            {'id':'done','kind':'stop','outcome':'finished'},
        ]}
    def standard(purpose):
        return {'schema_version':1,'standard_id':'fixture-'+purpose,'revision':'1.0.0','purpose':purpose,
            'criteria':[{'criterion_id':'criterion-a','statement':'Explicit fixture judgment.',
                'applies_to':['test-document'],'required_inputs':['proposal_ref'],
                'checks':[{'capability_id':check.capability_id,'interface_version':check.interface_version,'bindings':{}}],
                'policy':{'satisfied':'manual','violated':'block','insufficient':'block','unknown':'manual'}}],
            'reduction':{'required_criteria':'all_applicable','empty_applicable_set':'error','priority':['block','manual','pass']}}
    work_schema = {'type':'object','properties':{'document_type':{'const':'test-work-inputs'},'schema_version':{'const':1},
        'run_id':{'type':'string'},'proposal_ref':{'type':'object'},'events':{'type':'object'}},
        'required':['document_type','schema_version','run_id','proposal_ref','events'],'additionalProperties':False}
    resources=[]
    for identifier,kind,path,value in (
        ('workflow.main','workflow','workflow.json',workflow),
        ('schema.test','document_schema','schema-test.json',{'type':'object'}),
        ('schema.work','document_schema','schema-work.json',work_schema),
        ('standard.quality','standard','quality.json',standard('quality')),
        ('standard.acceptance','standard','acceptance.json',standard('acceptance'))):
        raw=canonical_bytes(value);(root/path).write_bytes(raw)
        resources.append({'id':identifier,'kind':kind,'path':path,'media_type':'application/schema+json' if kind=='document_schema' else 'application/yaml','sha256':hashlib.sha256(raw).hexdigest()})
    manifest={'schema_version':1,'method_id':'test.persisted-submission-wait','release_version':'1.0.0',
        'compiler_contract':'ordessa.methods/v1','entry':{'resource':'workflow.main'},'resources':resources,
        'documents':[{'document_type':'test-document','schema':{'resource':'schema.test'}},
                     {'document_type':'test-work-inputs','schema':{'resource':'schema.work'}}],
        'metadata':{'work_source':{'contract_version':'ordessa.persisted-work-source/1',
            'input_document_slot':'work_inputs','input_document_type':'test-work-inputs','waits':{
                'await_proposal':{'family':'object_exists','refs':['proposal_ref'],'event_slots':{}},
                'await_acceptance':{'family':'review_gate','plan_slot':'acceptance_plan','phase_key':'acceptance_review','event_slots':{}}}}},
        'requires':[{k:getattr(d,k) for k in ('capability_id','kind','interface_version','contract_digest')}
                    for d in ((check,request,dispatch,report) if report_phase else (check,request,dispatch))]}
    (root/'method.yaml').write_bytes(canonical_bytes(manifest))
    loaded=load_method(MethodSource(root),FileResourceReader());assert loaded.ok,loaded.error
    compiled=compile_method(loaded.value,caps,'test.submission-wait/1');assert compiled.ok,compiled.error
    store=SQLiteSnapshotStore(library)
    frozen=freeze_method(compiled.value,store,store,capability_catalog=SimpleNamespace(read_current=lambda:caps))
    assert frozen.ok,frozen.error
    snapshot=store.get(frozen.value.ref);r=snapshot.ref
    return snapshot,MethodRef(r.method_id,r.release_version,r.schema_version,Digest('sha256',r.snapshot_digest)),store


def build_submission_wait_fixture(tmp_path, *, report_phase=False, authorship_policy=None,
                                 native_dispatch_phase='completed'):
    domain_fixture=runpy.run_path(str(Path(__file__).parents[1]/'domain/test_submission_binding.py'))
    original_submission, original_package, original_grant, before, after=domain_fixture['fixture']()
    scope=original_submission.scope;actor=original_submission.created_by;now=original_submission.created_at
    library=EngineeringLibrary.create((tmp_path/'submission-review.sqlite').resolve(),library_id='submission-review-fixture',schema_version=15)
    factory=SQLiteUoWFactory(library)
    blobs=SQLiteBlobStore(library)
    def actual_blob(ref):
        raw=ref.storage_object_id.removeprefix('synthetic-blob-').encode()
        assert Digest('sha256',hashlib.sha256(raw).hexdigest())==ref.digest
        return blobs.put_verified(raw,ref.digest,ref.media_type)
    from ordessa_engineering.domain.changes.repository_baseline import RepositoryFile, seal_repository_baseline
    def baseline(record):
        return seal_repository_baseline(scope,record.ref.repository_id,record.ref.vcs,record.ref.commit_id,
            tuple(RepositoryFile(file.path,actual_blob(file.blob_ref)) for file in record.files))
    before=tuple(baseline(record) for record in before)
    after=tuple(baseline(record) for record in after)
    snapshot,method_ref,store=_frozen_method(tmp_path,library,report_phase=report_phase,
        authorship_policy=authorship_policy)
    context=CommandContext(scope,'synthetic-fixture-principal',actor,'submission-wait-test',now,'submission-wait-test')
    MethodUseCases(factory,SyntheticAccess(),store,TestManagement()).adopt(method_ref,context,expected_version=0)
    controls=SQLiteMethodControl(factory,store)

    def material(artifact_id,document_type,value,revision_id=None):
        revision_id=revision_id or artifact_id+'-r1'
        spec=document_spec(snapshot,document_type)
        resource=next(r for r in snapshot.resources if r.resource_id==spec.schema_ref.resource_id)
        exact=ExactMethodResourceRef(method_ref,resource.logical_path,Digest('sha256',resource.digest),resource.resource_id)
        schema=thaw_value(spec.value_schema)
        location='https://ordessa.invalid/method/'+exact.logical_path
        payload=MethodPayload('application/json',urljoin(location,schema.get('$id',location)),MethodContent.from_value(exact,value))
        revision=ArtifactRevision(scope,artifact_id,revision_id,now,actor,payload,schema_version=2,method_refs=(method_ref,))
        with factory.begin(scope) as uow:
            uow.engineering.create(Artifact(scope,artifact_id,'plan',now))
            verify_material(revision,uow.engineering.validated_budget())
            uow.engineering.append_revision(revision,expected_version=0);uow.commit()
        return revision

    design=material('design','test-document',{'statement':'Declared design fixture.'})
    output=material('output','test-document',{'statement':'Execution output fixture.'})
    other_output=material('other-output','test-document',{'statement':'Other actual persisted output.'})
    standard_by_purpose={s.purpose:s for s in snapshot.program.standard_definitions}
    def template(purpose,phase,selector,role):
        standard=standard_by_purpose[purpose];target=TemplateTarget(role,selector)
        return ReviewRequirementTemplate(scope,'template-'+purpose,1,purpose,(target,),method_ref,
            CriterionSetRef(standard.standard_id,1,Digest('sha256',standard.resource_ref.sha256)),
            (TemplateCheck(target,'criterion-a'),),('reviewer',),phase)
    quality=template('quality','quality_review',SubjectSelector('proposed_mutation',0),'proposed')
    acceptance=template('acceptance','acceptance_review',SubjectSelector('result_of_intent',implementation_intent_id='intent-a'),'output')
    spec=replace(original_grant.intent.implementation_spec,expected_baselines=tuple(r.ref for r in before),
        acceptance_requirement_refs=(acceptance.ref,))
    proposal=Proposal(scope,'proposal-a',now,actor,'change-a','Synthetic declared change','Fixture scope only.',
        (Mutation(design.artifact_id,'create',None,design.ref),),(),(),(),method_ref,(quality,acceptance),spec)
    with factory.begin(scope) as uow:
        for record in (*before,*after):uow.implementation.create_repository_baseline(record)
        uow.proposals.create_change(Change(scope,proposal.change_id,now))
        budget=uow.proposals.validated_budget();requirements=validate_create(proposal,uow.proposals,budget)
        uow.proposals.create_proposal(proposal,expected_version=0,budget=budget,requirements=requirements);uow.commit()
    change_set=ChangeSet((proposal.ref,))
    original_intent=original_grant.intent
    notice=ConversationNotice(scope,'notice-a',(design.ref,),design.ref,'Synthetic fixture notice.',original_grant.evidence.source,original_intent.policy_ref)
    intent=replace(original_intent,change_set=change_set,targets=(design.ref,),method_ref=method_ref,
        notice_ref=notice.ref,implementation_spec=spec,required_review_requirements=requirements)
    evidence=replace(original_grant.evidence,intent_digest=intent.digest,notice_ref=notice.ref)
    grant=ApprovalGrant(original_grant.approval_id,intent,original_grant.challenge_id,evidence,now)
    challenge=ConsentChallenge(scope,grant.challenge_id,intent.intent_id,intent.digest,notice.digest,
        Digest('sha256',hashlib.sha256(b'synthetic-nonce').hexdigest()),intent.expires_at)
    files=tuple(replace(f,proposal_refs=(proposal.ref,)) for f in original_package.payload.resolved_file_manifest)
    coverage=tuple(replace(c,proposal_ref=proposal.ref,acceptance_requirements=(acceptance.ref,),basis_refs=(design.ref,),
        instructions=tuple(actual_blob(ref) for ref in c.instructions)) for c in original_package.payload.proposal_coverage)
    from ordessa_engineering.domain.packages.models import package_manifest_digest
    payload=replace(original_package.payload,change_set=change_set,design_targets=(design.ref,),authorization_refs=(grant.ref,),
        method_ref=method_ref,resolved_file_manifest=files,acceptance_requirements=(acceptance.ref,),proposal_coverage=coverage,
        baseline_snapshots=tuple(r.ref for r in before),instructions_ref=actual_blob(original_package.payload.instructions_ref),
        derivation=replace(original_package.payload.derivation,intent_digest=intent.digest,
            input_refs=tuple(actual_blob(ref) for ref in original_package.payload.derivation.input_refs),output_manifest_digest=package_manifest_digest(files)))
    package=replace(original_package,payload=payload)
    raw=b'Explicitly synthetic completed native observation.'
    blob=blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/octet-stream')
    execution=replace(original_submission.execution_ref,captured_observation_ref=blob)
    report_content = None
    if report_phase:
        report_spec=document_spec(snapshot,'test-document')
        report_resource=next(r for r in snapshot.resources if r.resource_id==report_spec.schema_ref.resource_id)
        report_exact=ExactMethodResourceRef(method_ref,report_resource.logical_path,
            Digest('sha256',report_resource.digest),report_resource.resource_id)
        report_content=MethodContent.from_value(report_exact,{'statement':'Explicit method report fixture.'})
    submission=replace(original_submission,change_set=change_set,authorization_refs=(grant.ref,),package_ref=package.ref,
        execution_ref=execution,file_changes=tuple(replace(f,proposal_refs=(proposal.ref,)) for f in original_submission.file_changes),
        baseline_snapshots=tuple(r.ref for r in before),resulting_snapshots=tuple(r.ref for r in after),
        output_refs=(output.ref,),coverage=(SubmissionCoverage(proposal.ref,(output.ref,),tuple(f.change_id for f in original_submission.file_changes),(),'implemented'),),
        method_content=report_content)
    with factory.begin(scope) as uow:
        uow.authorization.put_notice(notice);uow.authorization.put_intent(intent);uow.authorization.put_challenge(challenge)
        uow.authorization.put_receipt(challenge,evidence);uow.authorization.put_grant(grant)
        uow.authorization.transition_challenge(challenge.challenge_id,0,'granted')
        uow.implementation.create_package(package);uow.submissions.create(submission);uow.commit()
    unit={'environmentNamespace':execution.environment_namespace,'unitId':execution.unit_id,
          'ownerProviderRef':json.loads(execution.owner_provider_ref_bytes),'sourceRevision':execution.source_revision}
    native=persist_historical_dispatch({'factory':factory,'run_id':'work-source-run','created_at':now},snapshot=snapshot,
        package=package,grant=grant,submission_execution_ref=execution,unit_ref=unit,prompt_ref=blob,
        prompt_digest=execution.prompt_input_digest,query_digest='sha256:'+'b'*64,
        dispatch_phase=native_dispatch_phase)
    phases=(ConfiguredReviewPhase('quality_review',('reviewer',),workflow_node_id='quality_review'),
        ConfiguredReviewPhase('acceptance_review',('reviewer',),workflow_node_id='acceptance_review',
                             submission_ref=submission.ref,review_purpose='acceptance'))
    bindings=SQLiteReviewBindings(factory,controls,scope=scope,proposal_ref=proposal.ref,phases=phases)
    with factory.begin(scope,'read') as uow:closure=resolve_submission_acceptance(uow,submission.ref)
    phase_bindings=bindings.resolve_submission_bindings(context,method_ref,submission.ref)
    plans=MethodBridge().submission_review_plans(snapshot,phase_bindings,requirements=closure.requirements,
        revisions=closure.artifact_revisions,review_ids={r.requirement_id:'acceptance-'+str(i) for i,r in enumerate(closure.requirements)})
    assert len(plans)==1
    plan=plans[0]
    with factory.begin(scope) as uow:uow.reviews.create_plan(plan);uow.commit()
    inputs=material('work-source-inputs','test-work-inputs',{'document_type':'test-work-inputs','schema_version':1,
        'run_id':'work-source-run','proposal_ref':asdict(proposal.ref),'events':{}})
    node=next(n for n in snapshot.program.workflow.steps if n.id=='await_acceptance')
    with factory.begin(scope) as uow:
        row=uow.workflow.run_row('work-source-run')
        new_inputs={**row['inputs'],'slots':{**row['inputs']['slots'],'proposal_ref':asdict(proposal.ref),
            'work_inputs':asdict(inputs.ref),'method_ref':asdict(method_ref),'acceptance_plan':asdict(plan)}}
        uow.workflow.replace_run_inputs(run_id='work-source-run',expected_inputs=row['inputs'],inputs=new_inputs)
        cursor=next(i for i,n in enumerate(snapshot.program.workflow.steps) if n.id==node.id)
        uow.workflow.update_run(run_id='work-source-run',status='WAITING_FOR_CONDITION',cursor=cursor,wait_reason=node.id,now=now);uow.commit()
    with factory.begin(scope,'read') as uow:row=uow.workflow.run_row('work-source-run')
    view={'run_id':'work-source-run','row':{**row,'method_ref':asdict(row['method_ref'])},
          'row_digest':run_wait_row_digest(row),'next_step_ordinal':0}
    source=SQLitePersistedMethodWorkSource(factory,controls,blobs=blobs,review_bindings=bindings)
    return locals()
