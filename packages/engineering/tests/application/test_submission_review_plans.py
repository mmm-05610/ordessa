"""Real stored 2.4 fixture method and original exact Submission expansion.

Catalog/Submission/output values are explicitly test-only. This proves pure
full-plan wiring, not production publication, current trust or acceptance.
"""
from dataclasses import replace
import pytest
from test_method_per_claim import ROOT, SCOPE, published, revision, binding
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.domain.reviews.requirements import (TemplateTarget, SubjectSelector,
    ReviewRequirementTemplate, TemplateCheck, expand_submission_requirement)
from ordessa_engineering.domain.reviews.refs import SubmissionRef
from ordessa_engineering.domain.common.models.values import Digest


@pytest.fixture
def review(tmp_path):
    lib=EngineeringLibrary.create((tmp_path/'submission-review.sqlite').resolve(),library_id='submission-review-fixture',schema_version=14)
    try:
        snapshot=published(lib,ROOT/'candidates/2.4.0')
        outputs=(revision('fixed-one'),revision('fixed-two'))
        original=binding(outputs)
        standard=next(s for s in snapshot.program.standard_definitions if s.purpose=='acceptance')
        inputs=tuple(sorted({name for c in standard.criteria for name in (c.required_inputs or ())}))
        phase=EngineeringTargetBindings(SCOPE,original.targets,tuple((t,'submission') for t in original.targets.targets),
            inputs,original.eligible_reviewer_roles,'acceptance',1,1,'acceptance','acceptance')
        bridge=MethodBridge();base,=bridge.review_requirements(snapshot,phase,revisions=outputs)
        slot=TemplateTarget('primary',SubjectSelector('result_of_intent',implementation_intent_id='intent-fixed'))
        checks=tuple(dict.fromkeys(TemplateCheck(slot,k.criterion_id,k.claim_id) for k in base.required_check_keys))
        template=ReviewRequirementTemplate(SCOPE,'deferred-acceptance',1,'acceptance',(slot,),base.method_ref,
            base.criterion_set_ref,checks,base.eligible_reviewer_roles,base.phase_key)
        submission=SubmissionRef(SCOPE.realm_id,SCOPE.project_id,'fixed-submission',Digest('sha256','d'*64))
        expanded=expand_submission_requirement(template,submission,'intent-fixed',tuple(o.ref for o in outputs),{o.ref:o for o in outputs})
        yield bridge,snapshot,phase,base,expanded,outputs,template,submission
    finally:lib.close()


def test_original_expanded_identity_survives_full_validation_and_plan_preparation(review):
    bridge,snapshot,phase,base,expanded,outputs,_,_=review
    assert expanded.requirement_id!=base.requirement_id
    assert bridge.submission_review_requirements(snapshot,(phase,),requirements=(expanded,),revisions=outputs)==(expanded,)
    plans=bridge.submission_review_plans(snapshot,(phase,),requirements=(expanded,),revisions=outputs,
                                       review_ids={expanded.requirement_id:'review-fixed'})
    plan,=plans
    assert plan.requirement==expanded and plan.check_keys==expanded.required_check_keys
    assert {k.target.ref for k in plan.check_keys}=={o.ref for o in outputs}


def test_new_submission_same_outputs_cannot_reuse_old_plan_digest(review):
    bridge,snapshot,phase,_,first,outputs,template,submission=review
    second=expand_submission_requirement(template,replace(submission,submission_id='new-submission'),
        'intent-fixed',tuple(o.ref for o in outputs),{o.ref:o for o in outputs})
    plans=[bridge.submission_review_plans(snapshot,(phase,),requirements=(r,),revisions=outputs,
             review_ids={r.requirement_id:'review-fixed'})[0] for r in (first,second)]
    assert plans[0].plan_digest!=plans[1].plan_digest
    assert plans[0].requirement.digest!=plans[1].requirement.digest


@pytest.mark.parametrize('kind',['missing-keys','wrong-fixed-version','empty-ids','foreign-id'])
def test_partial_keys_wrong_version_and_subset_selection_refuse(review,kind):
    bridge,snapshot,phase,_,expanded,outputs,_,_=review
    requirements=(expanded,);ids={expanded.requirement_id:'review-fixed'}
    if kind=='missing-keys':requirements=(replace(expanded,required_check_keys=expanded.required_check_keys[:-1]),)
    if kind=='wrong-fixed-version':outputs=(outputs[0],replace(outputs[1],revision_id='changed-fixed-version'))
    if kind=='empty-ids':ids={}
    if kind=='foreign-id':ids={'foreign-requirement':'review-fixed'}
    with pytest.raises(ApplicationError):
        bridge.submission_review_plans(snapshot,(phase,),requirements=requirements,revisions=outputs,review_ids=ids)
