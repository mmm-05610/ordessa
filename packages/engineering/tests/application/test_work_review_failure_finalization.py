"""Forward fail finalization on real SQLite; no model/network or old-data repair."""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace

import pytest

from ordessa_engineering.application.assembly import EngineeringPorts, build_engineering_service
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import work_binding_projection
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
from test_declarative_work import WORK_ID, _with_review_ports, open_work, start_params
from test_itemized_source_chain import ItemizedControlledProvider, build_itemized_chain
from test_real_source_chain import PRINCIPAL, SCOPE, close_chain, context, create_proposal
from work_step_access_fixture import enable_controlled_work_steps


@pytest.fixture(autouse=True)
def controlled_steps(monkeypatch):
    enable_controlled_work_steps(monkeypatch)


def case(tmp_path, *, provider=None, answers=None):
    env = build_itemized_chain(tmp_path, provider=provider,
        answers=answers or {'unique-record-authority': 'not_passed'})
    _with_review_ports(env)
    proposal = create_proposal(env)
    open_work(env, params=start_params(env, associations=(('proposal', proposal),)))
    return env, proposal


def parameters(env):
    return {'work_id': WORK_ID, 'action_id': 'incremental.review-change', 'inputs': {
        'baseline': asdict(env.baseline), 'candidate': asdict(env.candidate),
        'scope': asdict(SCOPE), 'method': asdict(env.method), 'caller_review_input': {}}}


def invoke(env, request='fail-review-parent'):
    return asyncio.run(env.service.execute('engineering.work.invoke', parameters(env), context(request)))


def operation(env, request='fail-review-parent'):
    return asyncio.run(env.service.query('engineering.operations.get',
        {'request_id': request}, context('read-'+request)))


def assert_pending(env):
    view = operation(env)
    assert view['state'] == 'unknown' and view['journal_state'] == 'pending'
    assert view['retry_allowed'] is False and view['unknown_requires_reconciliation'] is True


def test_complete_fail_finishes_parent_rejected_replays_and_cold_reads(tmp_path):
    env, proposal = case(tmp_path)
    try:
        answer = invoke(env)
        assert answer.status == 'rejected'
        result = answer.result
        assert result['state'] == 'failed' and result['failed_step'] == 'register'
        assert result['completed_steps'] == ['compare', 'record']
        compare, recorded, refused = result['steps']
        assert recorded['business']['verdict'] == 'fail'
        assert refused['state'] == 'failed' and refused['operation_id'] is None
        assert refused['business']['code'] == 'WORK_ACTION_REVIEW_NOT_PASSED'
        assert refused['business']['review_ref'] == recorded['business']['review_ref']
        assert refused['business']['successor_created'] is False
        with env.factory.begin(SCOPE, 'read') as uow:
            stored = uow.reviews.get_review(decode_review_ref(recorded['business']['review_ref']))
            assert stored.record.complete and stored.record.verdict == 'fail'
            assert uow.proposals.get_proposal(proposal).source_change.review_refs == ()
        assert env.library._connection.execute('SELECT count(*) FROM eng_proposals').fetchone()[0] == 1
        assert env.library._connection.execute('SELECT count(*) FROM eng_packages').fetchone()[0] == 0
        assert not env.library._connection.execute(
            "SELECT 1 FROM eng_commands WHERE operation='engineering.proposals.associate_review'").fetchall()
        calls = len(env.services.decision_provider.questions)
        assert calls == 8
        replay = invoke(env)
        assert replay == answer and len(env.services.decision_provider.questions) == calls
        view = operation(env)
        assert view['state'] == 'failed' and view['journal_state'] == 'rejected'
        assert view['unknown_requires_reconciliation'] is False and view['retry_allowed'] is False
        path = env.library.path
        env.library.close()
        reopened = EngineeringLibrary.open(path, library_id='local-source-chain')
        try:
            from test_real_source_chain import ControlledLocalAccess
            cold = build_engineering_service(SQLiteUoWFactory(reopened),
                EngineeringPorts(ControlledLocalAccess()))
            restored = asyncio.run(cold.query('engineering.operations.get',
                {'request_id': 'fail-review-parent'}, context('cold-fail-review-parent')))
            assert restored == view
        finally:
            reopened.close()
    finally:
        close_chain(env)


def test_provider_failure_stays_pending_and_is_never_resent(tmp_path):
    class FailedProvider(ItemizedControlledProvider):
        async def decide(self, question, ctx):
            self.questions.append(question)
            ctx.claim(question, self.settings_digest)
            raise RuntimeError('controlled provider failure')
    env, _ = case(tmp_path, provider=FailedProvider())
    try:
        with pytest.raises(ApplicationError, match='DECISION_REVIEW_NOT_COMPLETED'):
            invoke(env)
        assert_pending(env)
        assert env.library._connection.execute('SELECT count(*) FROM eng_reviews').fetchone()[0] == 0
        assert len(env.services.decision_provider.questions) == 1
        assert invoke(env).status == 'pending'
        assert len(env.services.decision_provider.questions) == 1
    finally:
        close_chain(env)


def test_indeterminate_record_is_not_misclassified_as_explicit_fail(tmp_path):
    env, _ = case(tmp_path, answers={'unique-record-authority': 'unknown'})
    try:
        with pytest.raises(ApplicationError, match='PROPOSAL_REVIEW_ASSOCIATION_INVALID'):
            invoke(env)
        assert_pending(env)
        assert env.library._connection.execute('SELECT count(*) FROM eng_reviews').fetchone()[0] == 1
    finally:
        close_chain(env)


@pytest.mark.parametrize('mutation', ['foreign_ref', 'trust_closed', 'request_drift', 'work_drift'])
def test_unconfirmed_or_changed_fail_cannot_finalize_parent(tmp_path, monkeypatch, mutation):
    env, _ = case(tmp_path)
    steps = env.service._review_change_steps
    original_record = steps.record
    try:
        async def record(ctx, contract):
            result = await original_record(ctx, contract)
            if mutation == 'foreign_ref':
                result['review_ref'] = {**result['review_ref'], 'review_id': 'not-this-review'}
            elif mutation == 'trust_closed':
                env.reviewer.close()
            return result
        monkeypatch.setattr(steps, 'record', record)
        if mutation in {'request_drift', 'work_drift'}:
            binding = env.service._work_queries.read_binding(context('read-binding'), WORK_ID)
            original_finish = env.service._works.finish_invoke
            def finish(ctx, operation_id, result, *, state='completed', validate=None):
                # After the source/trust guard was acquired, before completion TX.
                if mutation == 'request_drift':
                    env.library._connection.execute('UPDATE eng_review_requests SET fence=fence+1')
                else:
                    with env.factory.begin(SCOPE) as uow:
                        newer = replace(binding, revision=binding.revision + 1)
                        uow.workflow.write_work_context(stable_id=newer.stable_id,
                            revision=newer.revision, body=work_binding_projection(newer))
                        uow.commit()
                return original_finish(ctx, operation_id, result, state=state, validate=validate)
            monkeypatch.setattr(env.service._works, 'finish_invoke', finish)
        with pytest.raises(ApplicationError):
            invoke(env)
        assert_pending(env)
        assert env.library._connection.execute('SELECT count(*) FROM eng_proposals').fetchone()[0] == 1
    finally:
        close_chain(env)


@pytest.mark.parametrize('rotate_after_child', [False, True])
def test_real_instance_lease_restores_parent_before_fail_completion(tmp_path, monkeypatch, rotate_after_child):
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
    from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
    from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
    env, proposal = case(tmp_path)
    token = ['local-controlled-token']
    wire_scope = WireScope(SCOPE.realm_id, SCOPE.project_id)
    capabilities = ('engineering.work.start', 'engineering.work.invoke', 'engineering.work.get',
        'engineering.operations.get', 'engineering.reviews.request', 'engineering.reviews.record',
        'engineering.proposals.associate_review', 'engineering.references.resolve')
    authority = InstanceAccessAuthority(lambda: token[0], principal_id=PRINCIPAL,
        legacy_principal=None, grants=(AccessGrant(wire_scope, capabilities),))
    caller = authority.authenticate('Bearer '+token[0])
    access = EngineeringCommandAccess(authority)
    def plan_factory(ctx, binding, *, review_id, baseline, candidate):
        assert baseline == env.baseline and candidate == env.candidate
        return env.bindings.plan(ctx, review_id)
    env.service = build_engineering_service(env.factory, EngineeringPorts(access,
        review_admission=env.admission, source_materials=env.materials, method_guard=env.controls,
        source_review_bindings=env.bindings, blobs=env.blobs,
        review_run=env.reviewer.run_review, review_plan_factory=plan_factory))
    original_admit = access.admit_work_step
    @contextmanager
    def admit(parent, capability, *, request_id):
        with original_admit(parent, capability, request_id=request_id) as child:
            yield child
        if rotate_after_child and capability == 'engineering.proposals.associate_review':
            token[0] = 'rotated-controlled-token'
    monkeypatch.setattr(access, 'admit_work_step', admit)
    try:
        with access.admit(caller, wire_scope, 'engineering.work.invoke',
                          request_id='real-fail-parent', trace_id='real-fail-lease') as ctx:
            if rotate_after_child:
                with pytest.raises(ApplicationError):
                    asyncio.run(env.service.execute('engineering.work.invoke', parameters(env), ctx))
            else:
                answer = asyncio.run(env.service.execute('engineering.work.invoke', parameters(env), ctx))
                assert answer.status == 'rejected' and answer.result['state'] == 'failed'
        row = env.library._connection.execute(
            "SELECT state FROM eng_commands WHERE operation='engineering.work.invoke'").fetchone()
        assert row[0] == ('pending' if rotate_after_child else 'rejected')
    finally:
        close_chain(env)
