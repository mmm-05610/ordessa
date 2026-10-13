"""Schema9 real SQLite atomic apply; authority/model ports are synthetic fixtures."""
from dataclasses import asdict, replace
from contextlib import contextmanager
import hashlib
import sqlite3
import pytest
from test_conversation_approvals import call, read, ready, evidence, reply, POLICY_PATH
from test_proposal_usecases import _publish_method, _artifact_graph, _draft, _ctx, _proposal_ref, SCOPE
from test_review_usecases import SyntheticAccess, SyntheticAdmission
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.application.usecases.proposal_closure import resolve_record
from ordessa_engineering.domain.approvals.consent import ConsentPolicyRef, ConversationSource, ConversationNotice, ChangeAuthorizationIntent
from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.application_plan import HeadExpectation
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.models import ReviewPlan, CheckPolicy, AggregationPolicy, CriterionSetRef
from ordessa_engineering.domain.reviews.requirements import ReviewRequirementTemplate, TemplateTarget, TemplateCheck, SubjectSelector
from ordessa_engineering.application.contracts.errors import ApplicationError

@pytest.fixture
def env(tmp_path, request):
    lib = EngineeringLibrary.create((tmp_path/'apply.sqlite').resolve(), library_id='apply-test', schema_version=9)
    factory = SQLiteUoWFactory(lib)
    method = _publish_method(lib, tmp_path/'method')
    base, target, claim = _artifact_graph(factory)
    targets = (target,)
    if getattr(request, 'param', 1) == 2:
        from ordessa_engineering.domain.artifacts.models import Artifact
        from ordessa_engineering.application.usecases.material_closure import verify_material
        with factory.begin(SCOPE) as uow:
            original_base = uow.engineering.resolve_revision(base)
            original_target = uow.engineering.resolve_revision(target)
            uow.engineering.create(Artifact(SCOPE,'artifact-2','plan',_ctx().received_at))
            second_base = replace(original_base,artifact_id='artifact-2',revision_id='second-base')
            verify_material(second_base,uow.engineering.validated_budget())
            second_ref = uow.engineering.append_revision(second_base,expected_version=0)
            second_target = replace(original_target,artifact_id='artifact-2',revision_id='second-proposed',parent_revision_refs=(second_ref,))
            verify_material(second_target,uow.engineering.validated_budget())
            targets += (uow.engineering.append_revision(second_target,expected_version=1),)
            uow.commit()
    blobs = SQLiteBlobStore(lib)
    reviewer = SyntheticAdmission(lib, blobs)
    raw = POLICY_PATH.read_bytes()
    policy = ConsentPolicyRef('ordessa.product.v1.chat-attested-confirmation', 1, Digest('sha256', hashlib.sha256(raw).hexdigest()))
    @contextmanager
    def guard(context, value):
        assert not lib._connection.in_transaction
        yield
        assert not lib._connection.in_transaction
    admission = ConversationAdmission(raw, policy, attestor_guard=guard, intent_guard=guard)
    access = SyntheticAccess()
    facade = EngineeringService(factory, access, review_admission=reviewer, blobs=blobs, conversation_admission=admission)
    e = dict(lib=lib, factory=factory, facade=facade, scope=SCOPE, review_admission=reviewer,
             reviews=ReviewUseCases(factory, access, reviewer, blobs=blobs), policy=policy)
    draft = _draft(method, base, target, claim)
    draft['mutations'][0].update(operation='create', base_ref=None)
    if len(targets) == 2:
        draft['mutations'].append(dict(artifact_id='artifact-2',operation='create',base_ref=None,proposed_ref=asdict(targets[1])))
    slot = TemplateTarget('proposed', SubjectSelector('proposed_mutation', 0))
    template = ReviewRequirementTemplate(SCOPE, 'apply-template', 1, 'quality', (slot,), method,
        CriterionSetRef('apply-criteria',1,Digest('sha256','a'*64)), (TemplateCheck(slot,'apply-criterion'),), ('reviewer',), 'apply-phase')
    draft['review_requirement_templates'] = [asdict(template)]
    created = call(e, 'engineering.proposals.create', dict(change_id=None,expected_version=0,draft=draft), 'proposal')
    ref = _proposal_ref(created.result['proposal_ref'])
    with factory.begin(SCOPE, 'read') as uow:
        p = uow.proposals.get_proposal(ref)
        reqs = resolve_record(p, uow.proposals, uow.proposals.validated_budget())
        owner = uow.engineering.get_artifact('artifact-1')
    requirement = reqs[0]
    plan = ReviewPlan('apply-review', requirement, tuple(CheckPolicy(k,True,True) for k in requirement.required_check_keys), AggregationPolicy(), ('reviewer',))
    source = ConversationSource('synthetic-original-qa', (), 'Synthetic authority only; no live model or authenticated human claim.', 'principal-1', _ctx().received_at)
    notice = ConversationNotice(SCOPE, 'apply-notice', targets, target, 'Apply exact artifact batch.', source, policy)
    intent = ChangeAuthorizationIntent(SCOPE,'apply-intent',ChangeSet((ref,)),targets,
        tuple(HeadExpectation(t.artifact_id,owner.version,None) for t in targets),method,notice.ref,policy,reqs,
        'Apply this exact DID artifact batch.', '2026-10-09T00:00:00.000000Z','2026-10-10T00:00:00.000000Z')
    e.update(plan=plan, source=source, notice=notice, intent=intent, target=target)
    try:
        challenge = ready(e)
        grant = reply(e, challenge, evidence(e))
        e['approval'] = decode_approval_ref(grant.result['approval_ref'])
        yield e
    finally:
        lib.close()


def state(e):
    with e['factory'].begin(SCOPE,'read') as uow:
        a = uow.engineering.get_artifact('artifact-1')
        budget = uow.authorization.action_budget(e['approval'])
    counts = tuple(e['lib']._connection.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]
                   for t in ('eng_action_consumptions','eng_apply_records','eng_commands'))
    return a, budget, counts


def test_apply_persists_exact_receipt_and_replay_consumes_once(env):
    result = call(env,'engineering.changes.apply', {'approval_ref':asdict(env['approval'])},'apply')
    assert result.status == 'completed' and result.result['state'] == 'APPLIED'
    owner, budget, counts = state(env)
    assert owner.head_revision_id == env['target'].revision_id
    assert owner.version == env['intent'].expected_heads[0].version + 1
    assert counts[:2] == (1,1)
    before = state(env)
    assert call(env,'engineering.changes.apply', {'approval_ref':asdict(env['approval'])},'apply') == result
    assert state(env) == before
    receipt = read(env,'engineering.changes.get_apply', {'apply_id':result.result['apply_receipt']['apply_id']})
    from ordessa_infrastructure.encoding import canonical_bytes
    assert canonical_bytes(asdict(receipt)) == canonical_bytes(result.result['apply_receipt'])

@pytest.mark.parametrize('fault', ['head','receipt'])
def test_failure_after_effect_rolls_back_head_budget_receipt_and_journal(env, monkeypatch, fault):
    if fault == 'head':
        from ordessa_engineering.adapters.persistence.sqlite.artifact_repository import SQLiteArtifactRepository as Repo
        method = 'apply_head_plan'
    else:
        from ordessa_engineering.adapters.persistence.sqlite.authorization_repository import SQLiteAuthorizationRepository as Repo
        method = 'put_apply'
    original = getattr(Repo,method)
    def fail(self,*args,**kwargs):
        original(self,*args,**kwargs)
        raise ApplicationError('INJECTED_ATOMIC_FAILURE')
    before = state(env)
    with monkeypatch.context() as m:
        m.setattr(Repo,method,fail)
        with pytest.raises(ApplicationError,match='INJECTED_ATOMIC_FAILURE'):
            call(env,'engineering.changes.apply', {'approval_ref':asdict(env['approval'])},'apply')
    assert state(env) == before
    assert call(env,'engineering.changes.apply', {'approval_ref':asdict(env['approval'])},'apply').result['state'] == 'APPLIED'


def test_new_action_identity_cannot_exceed_budget_and_ledgers_are_immutable(env):
    call(env,'engineering.changes.apply', {'approval_ref':asdict(env['approval'])},'apply')
    before = state(env)
    with pytest.raises(ApplicationError):
        with env['factory'].begin(SCOPE) as uow:
            uow.authorization.consume_action(env['approval'],action='apply_change',action_instance_id='new-identity',target_digest=env['intent'].change_set.digest,now=_ctx().received_at)
            uow.commit()
    assert state(env) == before
    for table in ('eng_action_consumptions','eng_apply_records'):
        with pytest.raises(sqlite3.IntegrityError):
            env['lib']._connection.execute('DELETE FROM '+table)
    assert state(env) == before


def test_revoked_reviewer_trust_prevents_any_effect(env):
    before = state(env)
    env['review_admission'].revoke_trust = True
    with pytest.raises(ApplicationError):
        call(env,'engineering.changes.apply', {'approval_ref':asdict(env['approval'])},'apply')
    assert state(env) == before


def test_expired_grant_refuses_without_effect(env):
    before = state(env)
    with pytest.raises(ApplicationError):
        call(env,'engineering.changes.apply', {'approval_ref':asdict(env['approval'])},'apply',received_at='2026-10-11T12:00:00.000000Z')
    assert state(env) == before


def test_complete_requirements_cannot_be_substituted_with_same_identity(env):
    from ordessa_engineering.application.usecases.changes.apply import resolve_change_intent
    req = env['intent'].required_review_requirements[0]
    altered = replace(req, purpose='provenance_support')
    candidate = replace(env['intent'],required_review_requirements=(altered,))
    with env['factory'].begin(SCOPE,'read') as uow:
        with pytest.raises(ApplicationError,match='METHOD_REQUIREMENTS_CHANGED'):
            resolve_change_intent(uow,candidate)
    assert state(env)[2][:2] == (0,0)


def test_changed_artifact_version_refuses_frozen_intent(env):
    from ordessa_engineering.application.usecases.changes.apply import resolve_change_intent
    candidate = replace(env['intent'],expected_heads=(replace(env['intent'].expected_heads[0],version=1),))
    with env['factory'].begin(SCOPE,'read') as uow:
        with pytest.raises(ApplicationError):
            resolve_change_intent(uow,candidate)
    assert state(env)[2][:2] == (0,0)


@pytest.mark.parametrize('env',[2],indirect=True)
def test_whole_batch_second_head_failure_rolls_back_first_head(env,monkeypatch):
    from ordessa_engineering.adapters.persistence.sqlite.artifact_repository import SQLiteArtifactRepository
    original = SQLiteArtifactRepository.apply_head_plan
    def fail_after_batch(self,plan):
        original(self,plan)
        # Both actual CAS effects are visible in the original transaction.
        assert all(self.get_artifact(m.expected.artifact_id).head_revision_id == m.proposed_ref.revision_id for m in plan.mutations)
        raise ApplicationError('INJECTED_BATCH_FAILURE')
    before = state(env)
    with monkeypatch.context() as m:
        m.setattr(SQLiteArtifactRepository,'apply_head_plan',fail_after_batch)
        with pytest.raises(ApplicationError,match='INJECTED_BATCH_FAILURE'):
            call(env,'engineering.changes.apply', {'approval_ref':asdict(env['approval'])},'apply')
    assert state(env) == before
    with env['factory'].begin(SCOPE,'read') as uow:
        assert uow.engineering.get_artifact('artifact-2').head_revision_id is None
        assert uow.engineering.get_artifact('artifact-2').version == 2
    result = call(env,'engineering.changes.apply', {'approval_ref':asdict(env['approval'])},'apply')
    assert len(result.result['apply_receipt']['mutations']) == 2
