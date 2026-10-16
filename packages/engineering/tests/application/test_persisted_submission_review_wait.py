"""Original SQLite Submission review-wait subject admission, no native send.

Consent and native completion are explicit fixture history. A valid wait binding
is not a passing review or Engineering acceptance.
"""
from dataclasses import asdict, replace
from copy import deepcopy
import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import ReviewWaitRequirements
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from submission_wait_business_fixture import build_submission_wait_fixture


@pytest.fixture
def subject(tmp_path):
    e=build_submission_wait_fixture(tmp_path)
    try:yield e
    finally:e['library'].close()


def test_exact_submission_plan_selects_full_original_acceptance_requirements(subject):
    e=subject
    assert e['native']['synthetic_native_facts'] is True
    with e['source'].guard_condition(e['context'],e['snapshot'],e['node'],e['view']) as selection:
        assert type(selection.condition.intent) is ReviewWaitRequirements
        assert selection.condition.intent.required_review_requirements==e['closure'].requirements
        assert selection.condition.family=='review_gate'
        assert selection.event_values=={}
        assert e['plan'].requirement in selection.condition.intent.required_review_requirements
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.reviews.get_request(e['plan'].review_id).state=='requested'
        assert uow.engineering.get_artifact(e['output'].artifact_id).head_revision_id is None
        assert uow.workflow.run_row('work-source-run')['status']=='WAITING_FOR_CONDITION'


def _store_altered_plan(e,kind):
    plan=e['plan'];requirement=plan.requirement
    policies=plan.check_policies
    if kind=='wrong_version':
        requirement=replace(requirement,requirement_version=requirement.requirement_version+1)
    elif kind in ('wrong_target','old_proposal_plan'):
        target=Target('output' if kind=='wrong_target' else 'proposed',
                     e['other_output'].ref if kind=='wrong_target' else e['design'].ref)
        keys=tuple(replace(key,target=target) for key in requirement.required_check_keys)
        requirement=replace(requirement,requirement_id='obsolete-'+kind,
            expected_targets=TargetSet((target,)),required_check_keys=keys)
        policies=tuple(replace(policy,key=replace(policy.key,target=target)) for policy in policies)
    else:raise AssertionError(kind)
    altered=replace(plan,review_id='negative-'+kind,requirement=requirement,check_policies=policies)
    with e['factory'].begin(e['scope']) as uow:
        uow.reviews.create_plan(altered);uow.commit()
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.reviews.get_plan(altered.review_id)==altered
        assert uow.reviews.get_request(altered.review_id).state=='requested'
    view=deepcopy(e['view']);view['row']['inputs']['slots']['acceptance_plan']=asdict(altered)
    return altered,view


@pytest.mark.parametrize('kind',['wrong_target','wrong_version','old_proposal_plan'])
def test_stored_same_scope_phase_plan_cannot_substitute_submission_identity(subject,kind):
    e=subject;altered,view=_store_altered_plan(e,kind)
    assert altered.scope==e['plan'].scope
    assert altered.requirement.phase_key==e['plan'].requirement.phase_key
    assert altered.requirement.method_ref==e['method_ref']
    with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
        with e['source'].guard_condition(e['context'],e['snapshot'],e['node'],view):
            pytest.fail('an obsolete or substituted plan must never become the exact wait subject')


def test_withdrawn_original_submission_request_refuses_before_wait_binding(subject):
    e=subject
    with e['factory'].begin(e['scope']) as uow:
        request=uow.reviews.get_request(e['plan'].review_id)
        uow.reviews.withdraw_request(e['plan'].review_id,expected_version=request.version,fence=request.fence)
        uow.commit()
    with pytest.raises(ApplicationError,match='WORK_REVIEW_BINDING_MISMATCH'):
        with e['source'].guard_condition(e['context'],e['snapshot'],e['node'],e['view']):
            pytest.fail('withdrawn review request must not bind the wait')
