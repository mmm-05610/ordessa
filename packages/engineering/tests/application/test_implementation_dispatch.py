"""Dispatch transaction guards with synthetic grants and a real schema13 library.

The run/package resolvers and guard port below are explicit fixtures. These
tests do not claim real method-graph, product admission, or Grant qualification.
"""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import runpy

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch
from ordessa_engineering.domain.approvals.consent import (
    ApprovalGrant, ConsentChallenge, ConversationEvidence, ConversationNotice,
)
from ordessa_engineering.domain.common.models.values import Digest


TESTS = Path(__file__).parents[1]
NOW = '2026-10-11T12:00:00.000000Z'
UNIT = {
    'environmentNamespace': 'synthetic-environment',
    'unitId': 'synthetic-unit',
    'ownerProviderRef': {'provider': 'synthetic-provider'},
    'sourceRevision': 'synthetic-revision',
}


def _digest(raw):
    return Digest('sha256', hashlib.sha256(raw).hexdigest())


def _fixture_records():
    helpers = runpy.run_path(str(TESTS / 'domain/test_implementation_package_binding.py'))
    intent, original_grant, package, *_ = helpers['_records']()
    source = original_grant.evidence.source
    notice = ConversationNotice(
        intent.scope, original_grant.intent.notice_ref.notice_id,
        package.payload.design_targets, package.payload.design_targets[0],
        'Synthetic notice text for pure application fixture.', source, intent.policy_ref,
    )
    intent = replace(intent, notice_ref=notice.ref)
    evidence = ConversationEvidence(
        original_grant.evidence.evidence_id, original_grant.evidence.question,
        original_grant.evidence.necessary_context, original_grant.evidence.user_answer,
        source, intent.policy_ref, intent.digest, notice.ref, 'confirm',
    )
    grant = ApprovalGrant(original_grant.approval_id, intent,
                          original_grant.challenge_id, evidence, NOW)
    payload = replace(
        package.payload,
        authorization_refs=(grant.ref,),
        derivation=replace(package.payload.derivation, intent_digest=intent.digest),
    )
    package = replace(package, payload=payload)
    challenge = ConsentChallenge(
        intent.scope, grant.challenge_id, intent.intent_id, intent.digest, notice.digest,
        _digest(b'synthetic-nonce'), '2026-10-11T12:05:00.000000Z',
    )
    return intent, notice, challenge, evidence, grant, package


class _CommandAccess:
    def require(self, context, operation):
        assert type(context) is CommandContext
        assert operation == 'engineering.executions.dispatch'


class _Approvals:
    def __init__(self, factory):
        self.factory = factory

    def _check_gates(self, uow, decisions):
        assert decisions == ('synthetic-gate-decision',)


class _Selection:
    """Explicit test peer; this fixture isolates original dispatch CAS cuts."""
    @contextmanager
    def guard_selection(self, context, package, unit_ref):
        assert unit_ref == UNIT
        yield None


class _Execution:
    def __init__(self, *, send_error=False):
        self.send_error = send_error
        self.send_calls = []

    def freeze_input(self, unit_ref, params):
        raw = canonical_bytes({'unit_ref': unit_ref, 'params': params})
        return raw, _digest(raw)

    def query_digest(self, unit_ref, operation_ref, prompt_digest):
        return 'synthetic-query-digest'

    @contextmanager
    def guard_effect_handoff(self, context, binding, *, access, timeout=60):
        # Explicit transaction-only peer. Actual authority/thread handoff is
        # qualified in test_dispatch_effect_handoff83, not in this fixture.
        assert binding.scope == context.scope
        assert access is not None
        yield

    def send(self, binding, *, timeout):
        self.send_calls.append(binding)
        if self.send_error:
            raise OSError('synthetic uncertain native send')


def _setup(tmp_path, monkeypatch, *, send_error=False, guard_mode='allow'):
    intent, notice, challenge, evidence, grant, package = _fixture_records()
    library = EngineeringLibrary.create((tmp_path / 'dispatch.sqlite').resolve(),
                                         library_id='synthetic-dispatch-library', schema_version=13)
    factory = SQLiteUoWFactory(library)
    blobs = SQLiteBlobStore(library)
    # The original run row and grant are durable in the same Engineering DB.
    with library.transaction() as connection:
        connection.execute(
            'INSERT INTO runs (run_id,method_ref_json,registry_ref_json,input_json,status,cursor,'
            'wait_reason,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
            ('run-1', '{}', '{}', '{}', 'running', 0, None, NOW, NOW),
        )
    with factory.begin(intent.scope) as uow:
        uow.authorization.put_notice(notice)
        uow.authorization.put_intent(intent)
        uow.authorization.put_challenge(challenge)
        uow.authorization.put_receipt(challenge, evidence)
        uow.authorization.put_grant(grant)
        uow.commit()

    execution = _Execution(send_error=send_error)
    service = ImplementationDispatch(factory, _CommandAccess(), approval_usecases=_Approvals(factory),
                                     execution=execution, blobs=blobs, selection=_Selection())
    calls = {'guards': 0}

    @contextmanager
    def guards(context, resolved_package, unit=None):
        calls['guards'] += 1
        if guard_mode == 'second_guard_fails' and calls['guards'] == 2:
            raise ApplicationError('SECOND_GUARD_REFUSED')
        if guard_mode == 'control_changes' and calls['guards'] == 2:
            with factory.begin(context.scope) as uow:
                uow.authorization.revoke(grant.ref, expected_version=0, occurred_at=NOW,
                                         reason='synthetic control change', event_id='synthetic-revoke')
                uow.commit()
        yield grant, ('synthetic-gate-decision',)

    service._guards = guards
    # Deliberate fixtures: graph-derived package and full admission aren't the
    # subject here; the original SQLite UoW, ledger, dispatch row and CAS are.
    service._work_package = lambda uow, run_id, **kwargs: package
    from ordessa_engineering.application.usecases.packages.implementation import ImplementationUseCases
    monkeypatch.setattr(ImplementationUseCases, '_resolve_package',
                        staticmethod(lambda uow, record, *, now: None))
    return library, factory, service, execution, calls, grant, package, intent


def _dispatch(service, context):
    return service.dispatch('run-1', 'source_review', 1, UNIT, {'prompt': 'synthetic prompt'},
                            ('edit_repository',), context)


def _context(scope, actor):
    return CommandContext(scope, 'synthetic-principal', actor, 'dispatch-request', NOW, 'dispatch-trace')


def _stored(library):
    return library._connection.execute(
        'SELECT dispatch_phase,dispatch_version,binding_digest,execution_operation_ref '
        'FROM step_log WHERE run_id=? AND step_id=? AND attempt=?',
        ('run-1', 'source_review', 1),
    ).fetchone()


def _debits(library, grant):
    return library._connection.execute(
        'SELECT count(*) FROM eng_action_consumptions WHERE realm_id=? AND project_id=? '
        'AND approval_id=? AND action=?',
        (grant.ref.realm_id, grant.ref.project_id, grant.ref.approval_id, 'edit_repository'),
    ).fetchone()[0]


def test_second_guard_refusal_leaves_reserved_row_and_never_sends(tmp_path, monkeypatch):
    library, _, service, execution, calls, grant, package, _ = _setup(
        tmp_path, monkeypatch, guard_mode='second_guard_fails')
    try:
        with pytest.raises(ApplicationError, match='SECOND_GUARD_REFUSED'):
            _dispatch(service, _context(package.scope, package.created_by))
        assert calls['guards'] == 2
        assert execution.send_calls == []
        assert _stored(library)[0:2] == ('reserved', 0)
        assert _debits(library, grant) == 1
    finally:
        library.close()


def test_same_attempt_retry_does_not_mint_operation_or_action_instance(tmp_path, monkeypatch):
    library, _, service, execution, calls, grant, package, _ = _setup(
        tmp_path, monkeypatch, guard_mode='second_guard_fails')
    try:
        with pytest.raises(ApplicationError, match='SECOND_GUARD_REFUSED'):
            _dispatch(service, _context(package.scope, package.created_by))
        first = _stored(library)
        first_debits = _debits(library, grant)
        result = _dispatch(service, _context(package.scope, package.created_by))
        second = _stored(library)
        assert result['phase'] == 'reserved'
        assert result['reason'] == 'RESERVED_REQUIRES_ORIGINAL_NEVER_SENT_PROOF'
        assert second == first
        assert _debits(library, grant) == first_debits == 1
        assert calls['guards'] == 2
        assert execution.send_calls == []
    finally:
        library.close()


def test_native_send_error_records_unknown_and_does_not_refund_budget(tmp_path, monkeypatch):
    library, _, service, execution, calls, grant, package, _ = _setup(
        tmp_path, monkeypatch, send_error=True)
    try:
        result = _dispatch(service, _context(package.scope, package.created_by))
        assert result['phase'] == 'unknown'
        assert result['reason'] == 'NATIVE_SEND_OUTCOME_UNCONFIRMED'
        assert len(execution.send_calls) == 1
        assert _stored(library)[0:2] == ('unknown', 2)
        assert _debits(library, grant) == 1
        assert calls['guards'] == 2
    finally:
        library.close()


def test_second_guard_observes_control_change_and_refuses_send(tmp_path, monkeypatch):
    library, _, service, execution, calls, grant, package, _ = _setup(
        tmp_path, monkeypatch, guard_mode='control_changes')
    try:
        with pytest.raises(ApplicationError, match='APPROVAL_CONTROL_CHANGED'):
            _dispatch(service, _context(package.scope, package.created_by))
        assert len(execution.send_calls) == 0
        assert _stored(library)[0:2] == ('reserved', 0)
        assert _debits(library, grant) == 1
        with library.transaction() as connection:
            assert connection.execute(
                'SELECT state,version FROM eng_approval_controls WHERE realm_id=? AND project_id=? AND approval_id=?',
                (grant.ref.realm_id, grant.ref.project_id, grant.ref.approval_id),
            ).fetchone() == ('revoked', 1)
        assert calls['guards'] == 2
    finally:
        library.close()


def test_independent_run_creation_is_retired_and_history_cannot_dispatch(tmp_path, monkeypatch):
    from ordessa_engineering.application.orchestration.dispatch_method_run import resolve_method_run_package
    from dataclasses import asdict
    library,factory,service,_,_,_,package,_=_setup(tmp_path,monkeypatch)
    try:
        assert not hasattr(ImplementationDispatch, 'start_run')
        assert not hasattr(ImplementationDispatch, '_run')
        with factory.begin(package.scope) as uow:
            uow.implementation.create_package(package)
            descriptor=uow.workflow.create_generated(kind='implementation-run',stable_id='historical-run',body={
                'contract':'ordessa.implementation-run/1','scope':asdict(package.scope),
                'package_ref':asdict(package.ref),'method_ref':asdict(package.payload.method_ref)})
            uow.workflow.insert_run(run_id='historical-run',method_ref=descriptor,registry_ref={'historical':True},
                inputs={'contract':'ordessa.implementation-run/1'},now=NOW)
            uow.commit()
        with factory.begin(package.scope,'read') as uow:
            before=uow.workflow.run_row('historical-run')
            material=uow.workflow.read(descriptor)
            with pytest.raises(ApplicationError,match='DISPATCH_WORK_BINDING_AUTHORITY_UNAVAILABLE'):
                resolve_method_run_package(uow,'historical-run',None)
            assert uow.workflow.run_row('historical-run')==before
            assert uow.workflow.read(descriptor)==material
            assert uow.workflow.next_step_ordinal('historical-run')==0
            assert uow.commands.get(_context(package.scope,package.created_by).key) is None
        # Original effect/dispatch tests explicitly substitute package admission.
        # This new production-boundary case supplies none and must never send.
        del service._work_package
        with pytest.raises(ApplicationError,match='DISPATCH_WORK_BINDING_AUTHORITY_UNAVAILABLE'):
            _dispatch(service,_context(package.scope,package.created_by))
        assert service.execution.send_calls==[]
        assert library._connection.execute('SELECT count(*) FROM step_log WHERE binding_digest IS NOT NULL').fetchone()[0]==0
    finally:
        library.close()
