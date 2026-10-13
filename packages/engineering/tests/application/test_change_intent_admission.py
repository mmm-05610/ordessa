"""Original SQLite closure; business and management sources explicitly fixtures."""
from dataclasses import asdict, replace
import pytest
from test_method_control_admission import env, context
from test_proposal_usecases import _artifact_graph, _draft, _proposal_ref, SCOPE, SyntheticAccess
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.usecases.changes.apply import ChangeIntentAdmission, resolve_change_intent
from ordessa_engineering.application.usecases.changes.proposals import ProposalUseCases
from ordessa_engineering.application.usecases.proposal_closure import resolve_record
from ordessa_engineering.domain.approvals.consent import ChangeAuthorizationIntent, ConsentPolicyRef, NoticeRef
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.application_plan import HeadExpectation
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.models import CriterionSetRef
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.domain.reviews.requirements import ReviewRequirementTemplate, TemplateTarget, TemplateCheck, SubjectSelector


def ready(env, *, omitted=False, phases=('phase',), artifact_target=False):
    lib, method, factory, service, controls = env
    service.adopt(method, context('adopt'), expected_version=0)
    base, target, claim = _artifact_graph(factory)
    with controls.guard_method(context('snapshot'), method) as snapshot:
        standard = snapshot.program.standard_definitions[0]
    slot = (TemplateTarget('proposed', SubjectSelector('proposed_mutation',0)) if artifact_target
            else TemplateTarget('primary', SubjectSelector('self_proposal')))
    templates = tuple(ReviewRequirementTemplate(SCOPE, 'template-'+phase, 1, standard.purpose,
        (slot,), method, CriterionSetRef(standard.standard_id, 1, Digest('sha256', standard.resource_ref.sha256)),
        tuple(TemplateCheck(slot,c.criterion_id) for c in standard.criteria if not omitted or c==standard.criteria[0]),
        ('reviewer',), phase) for phase in phases)
    draft = _draft(method, base, target, claim)
    draft['mutations'][0].update(operation='create',base_ref=None)
    draft['review_requirement_templates'] = [asdict(t) for t in templates]
    result = ProposalUseCases(factory,SyntheticAccess()).create(
        dict(change_id=None,expected_version=0,draft=draft),context('proposal'))
    ref = _proposal_ref(result.result['proposal_ref'])
    with factory.begin(SCOPE,'read') as uow:
        p = uow.proposals.get_proposal(ref)
        requirements = resolve_record(p,uow.proposals,uow.proposals.validated_budget())
        owner = uow.engineering.get_artifact('artifact-1')
    primary = Target('proposed',target) if artifact_target else Target('primary',p.ref)
    bindings = tuple(EngineeringTargetBindings(SCOPE,TargetSet((primary,)),((primary,'test-document'),),
        ('proposal_ref',),('reviewer',),phase) for phase in phases)
    class Bindings:
        def resolve_review_proposal(self,ctx,exact_method,phase):return p.ref
        def resolve_bindings(self,ctx,exact_method,phase):
            return next(b for b in bindings if b.phase_key==phase)
        def resolve_intent_bindings(self,ctx,exact_method,exact_proposal):
            assert ctx.scope==SCOPE and exact_method==method and exact_proposal==p.ref
            return bindings
    intent = ChangeAuthorizationIntent(SCOPE,'intent',ChangeSet((p.ref,)),(target,),
        (HeadExpectation('artifact-1',owner.version,None),),method,
        NoticeRef(SCOPE,'notice',Digest('sha256','a'*64)),
        ConsentPolicyRef('policy',1,Digest('sha256','b'*64)),requirements,'Exact test change.',
        '2026-10-09T00:00:00.000000Z','2026-10-12T00:00:00.000000Z')
    return intent, Bindings()


def test_complete_intent_uses_original_bridge_and_commits_under_control_guard(env):
    intent, bindings = ready(env)
    _,_,factory,_,controls = env
    with ChangeIntentAdmission(factory,controls,bindings).guard_intent(context('confirm'),intent):
        with factory.begin(SCOPE) as uow:
            assert resolve_change_intent(uow,intent).change_set==intent.change_set
            uow.commit()


def test_internally_consistent_omitted_criterion_cannot_authorize(env):
    intent,bindings = ready(env,omitted=True)
    _,_,factory,_,controls = env
    # Demonstrate the actual gap: the original self-consistency resolver passes.
    with factory.begin(SCOPE,'read') as uow:resolve_change_intent(uow,intent)
    with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
        with ChangeIntentAdmission(factory,controls,bindings).guard_intent(context('confirm'),intent):pass


def test_full_phase_set_and_omission_are_checked_without_template_filtering(env):
    intent,bindings = ready(env,phases=('source','quality'))
    _,_,factory,_,controls = env
    admission = ChangeIntentAdmission(factory,controls,bindings)
    with admission.guard_intent(context('confirm'),intent):pass
    original = bindings.resolve_intent_bindings
    bindings.resolve_intent_bindings = lambda *a: original(*a)[:1]
    with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
        with admission.guard_intent(context('missing-phase'),intent):pass


def test_intent_missing_requirement_and_control_change_refuse(env):
    intent,bindings = ready(env,phases=('source','quality'))
    _,method,factory,service,controls = env
    admission = ChangeIntentAdmission(factory,controls,bindings)
    changed=replace(intent,required_review_requirements=intent.required_review_requirements[:1])
    with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
        with admission.guard_intent(context('subset'),changed):pass
    with admission.guard_intent(context('confirm'),intent):
        service.control(method,context('stop'),expected_version=0,enabled=False,reason='test stop')
        with pytest.raises(ApplicationError,match='METHOD_CONTROL_CHANGED'):
            with factory.begin(SCOPE) as uow:uow.commit()


def test_missing_owner_and_other_intent_are_explicitly_unavailable(env):
    intent,bindings = ready(env)
    _,_,factory,_,controls = env
    with pytest.raises(ApplicationError,match='METHOD_TARGET_BINDINGS_UNAVAILABLE'):
        with ChangeIntentAdmission(factory,controls,None).guard_intent(context('confirm'),intent):pass
    with pytest.raises(ApplicationError,match='INTENT_OWNER_UNAVAILABLE'):
        with ChangeIntentAdmission(factory,controls,bindings).guard_intent(context('other'),object()):pass


def test_actual_document_target_review_keeps_original_proposal_expanded_identity(env):
    from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
    from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
    intent,bindings=ready(env,phases=('source','quality'),artifact_target=True)
    _,method,factory,_,controls=env
    admission=ChangeIntentAdmission(factory,controls,bindings)
    with admission.guard_intent(context('intent'),intent):pass
    ref=intent.change_set.proposal_refs[0]
    phases=bindings.resolve_intent_bindings(context('read'),method,ref)
    with factory.begin(SCOPE,'read') as uow:
        proposal=uow.proposals.get_proposal(ref)
        revisions=uow.proposals.resolve_revision_graph(
            (intent.targets[0],)+tuple(c.owner_revision_ref for c in proposal.claim_refs),uow.proposals.validated_budget())
        owners=(replace(uow.engineering.get_artifact('artifact-1'),head_revision_id=None),)
    with controls.guard_method(context('read'),method) as snapshot:
        requirement=intent.required_review_requirements[0]
        binding=next(b for b in phases if b.phase_key==requirement.phase_key)
        plan=MethodBridge().review_plan(snapshot,binding,requirement,'document-review',
            proposal=proposal,artifacts=owners,revisions=revisions,phase_bindings=phases)
    guard=EngineeringReviewAdmission(factory,controls,bindings)
    with guard.guard_plan(context('review'),plan):
        with factory.begin(SCOPE) as uow:uow.commit()
    assert plan.requirement.requirement_id.startswith('requirement:')
    assert all(type(t.ref).__name__=='ArtifactRevisionRef' for t in plan.requirement.expected_targets.targets)
    bindings.resolve_review_proposal=lambda *a:None
    with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
        with guard.guard_plan(context('missing-original-proposal'),plan):pass
