"""Actual original run/journal CAS, explicit synthetic trusted Work binding.

No CompiledProgram executor, real host adoption, model or product Grant fixture.
"""
from contextlib import contextmanager
from dataclasses import asdict
import pytest
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.run_waits import BoundRunWait, run_wait_row_digest
from ordessa_engineering.application.usecases.queries.run_waits import CurrentRunWaitUseCases
from test_review_usecases import SyntheticAccess, _scope, _context, _create_source


@pytest.fixture
def env(tmp_path):
    library = EngineeringLibrary.create((tmp_path/'run.sqlite').resolve(), library_id='wait-test', schema_version=14)
    factory = SQLiteUoWFactory(library)
    scope = _scope()
    ref = _create_source(factory,scope)
    with factory.begin(scope) as uow:
        method = uow.workflow.write_material(kind='method',stable_id='test-only-run',revision=1,body={'fixture':True},generated=False)
        uow.workflow.insert_run(run_id='run',method_ref=method,registry_ref={'fixture':True},inputs={},now=_context(scope,'setup').received_at)
        uow.workflow.update_run(run_id='run',status='WAITING_FOR_OBJECT',cursor=2,wait_reason='WAITING_FOR_OBJECT',now=_context(scope,'setup').received_at)
        uow.commit()
    class Bindings:
        family = 'object_exists'
        selected = ref
        revoke = False
        @contextmanager
        def guard_wait(self,context,run_id,row):
            assert not library._connection.in_transaction
            if self.revoke:
                raise ApplicationError('METHOD_SELECTION_CHANGED')
            with factory.begin(scope,'read') as uow:
                ordinal = uow.workflow.next_step_ordinal(run_id)
            yield BoundRunWait(scope,run_id,run_wait_row_digest(row),ordinal,self.family,(self.selected,))
    bindings=Bindings()
    service=CurrentRunWaitUseCases(factory,SyntheticAccess(),bindings)
    try:
        yield library,factory,scope,ref,bindings,service
    finally:
        library.close()


def params(state):
    return {'run_id':'run','expected_row_digest':state['row_digest'],
        'expected_condition_digest':state['condition_digest'],
        'expected_next_step_ordinal':state['next_step_ordinal']}


def test_single_resume_preserves_cursor_does_not_dispatch_and_replay_is_fact(env):
    library,factory,scope,ref,bindings,service=env
    state=service.read({'run_id':'run'},_context(scope,'query'))
    assert state['ready'] is True and state['cursor']==2
    context=_context(scope,'resume')
    result=service.resume(params(state),context)
    with factory.begin(scope,'read') as uow:
        row=uow.workflow.run_row('run')
        assert row['status']=='RUNNING' and row['cursor']==2 and row['wait_reason'] is None
        assert uow.workflow.next_step_ordinal('run')==0
    bindings.revoke=True
    assert service.resume(params(state),context)==result
    with pytest.raises(ApplicationError,match='REQUEST_IDENTITY_CONFLICT'):
        service.resume({**params(state),'expected_next_step_ordinal':1},context)


def test_stale_row_condition_and_ordinal_are_rejected_without_journal(env):
    library,factory,scope,ref,bindings,service=env
    state=service.read({'run_id':'run'},_context(scope,'query'))
    with factory.begin(scope) as uow:
        uow.workflow.update_run(run_id='run',status='WAITING_FOR_OBJECT',cursor=3,wait_reason='WAITING_FOR_OBJECT',now=_context(scope,'changed').received_at)
        uow.commit()
    with pytest.raises(ApplicationError,match='RUN_WAIT_CHANGED'):
        service.resume(params(state),_context(scope,'resume'))
    with factory.begin(scope,'read') as uow:
        assert uow.commands.get(_context(scope,'resume').key) is None
        assert uow.workflow.run_row('run')['cursor']==3


def test_no_work_authority_and_artifact_not_normal_execution_result(env):
    library,factory,scope,ref,bindings,service=env
    with pytest.raises(ApplicationError,match='WORK_WAIT_AUTHORITY_UNAVAILABLE'):
        CurrentRunWaitUseCases(factory,SyntheticAccess()).read({'run_id':'run'},_context(scope,'query'))
    bindings.family='result_exists'
    with pytest.raises(ApplicationError,match='WAIT_RESULT_OWNER_UNAVAILABLE'):
        service.read({'run_id':'run'},_context(scope,'query'))


def test_bad_condition_digest_and_unknown_input_never_advance(env):
    library,factory,scope,ref,bindings,service=env
    state=service.read({'run_id':'run'},_context(scope,'query'))
    bad={**params(state),'expected_condition_digest':{'algorithm':'sha256','hex':'a'*64}}
    with pytest.raises(ApplicationError,match='RUN_WAIT_CHANGED'):
        service.resume(bad,_context(scope,'resume'))
    with pytest.raises(ApplicationError,match='INVALID_INPUT'):
        service.resume({**params(state),'ready':True},_context(scope,'resume'))
    with factory.begin(scope,'read') as uow:
        assert uow.workflow.run_row('run')['status']=='WAITING_FOR_OBJECT'
