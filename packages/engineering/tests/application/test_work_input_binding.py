"""Original run/journal CAS; synthetic source is explicit, no production auth."""
from contextlib import contextmanager
from dataclasses import asdict
import asyncio
import pytest

from test_method_work import env, call, _context
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import WorkSeed
from ordessa_engineering.application.contracts.commands import ReadSet
from ordessa_engineering.application.contracts.run_waits import run_wait_row_digest


def _parameters(e):
    with e['factory'].begin(e['scope'],'read') as uow:
        row=uow.workflow.run_row('work')
        ordinal=uow.workflow.next_step_ordinal('work')
    return {'run_id':'work','input_ref':asdict(e['ref']),
            'expected_row_digest':asdict(run_wait_row_digest(row)),
            'expected_next_step_ordinal':ordinal}


def test_input_binding_refuses_without_actual_source(env):
    e=env;call(e,'engineering.work.start',{'run_id':'work'},'start')
    parameters=_parameters(e)
    with pytest.raises(ApplicationError,match='WORK_INPUT_SOURCE_UNAVAILABLE'):
        call(e,'engineering.work.bind_inputs',parameters,'missing-source')
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.commands.get(_context(e['scope'],'missing-source').key) is None


def test_input_binding_uses_original_row_cas_and_replay_without_advancing_cursor(env):
    e=env;call(e,'engineering.work.start',{'run_id':'work'},'start')
    parameters=_parameters(e)
    @contextmanager
    def selected(context,snapshot,view,input_ref):
        assert input_ref==e['ref'] and view['run_id']=='work'
        with e['factory'].begin(e['scope'],'read') as uow:
            assert uow.engineering.resolve_revision(input_ref).ref==input_ref
        yield WorkSeed({'initial':{'selected_ref':asdict(input_ref)}},ReadSet(e['scope'],()))
    e['source'].guard_inputs=selected
    result=call(e,'engineering.work.bind_inputs',parameters,'bind')
    assert result.result['status']=='WAITING_FOR_CONDITION'
    assert result.result['cursor']==0 and result.result['dispatched'] is False
    assert call(e,'engineering.work.bind_inputs',parameters,'bind')==result
    with e['factory'].begin(e['scope'],'read') as uow:
        row=uow.workflow.run_row('work')
        assert row['inputs']['slots']['initial']=={'selected_ref':asdict(e['ref'])}
        assert uow.workflow.next_step_ordinal('work')==0
    with pytest.raises(ApplicationError,match='RUN_WAIT_CHANGED'):
        call(e,'engineering.work.bind_inputs',parameters,'stale-bind')


def test_input_binding_rechecks_original_cas_after_source_read(env):
    e=env;call(e,'engineering.work.start',{'run_id':'work'},'start')
    parameters=_parameters(e)
    @contextmanager
    def selected(context,snapshot,view,input_ref):
        with e['factory'].begin(e['scope']) as uow:
            row=uow.workflow.run_row('work')
            changed={**row['inputs'],'slots':{**row['inputs']['slots'],'initial':{'race':True}}}
            uow.workflow.replace_run_inputs(run_id='work',expected_inputs=row['inputs'],inputs=changed)
            uow.commit()
        yield WorkSeed({'initial':{'selected_ref':asdict(input_ref)}},ReadSet(e['scope'],()))
    e['source'].guard_inputs=selected
    with pytest.raises(ApplicationError,match='RUN_WAIT_CHANGED'):
        call(e,'engineering.work.bind_inputs',parameters,'race-bind')
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.commands.get(_context(e['scope'],'race-bind').key) is None
