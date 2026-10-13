"""Read-only MethodRun listing over the existing SQLite authority."""
from dataclasses import asdict

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_runs import MethodRunOrchestrator
from ordessa_infrastructure.encoding import canonical_bytes
from test_method_work import call, env, query
from test_review_usecases import _context


def _list(e, params=None, request='list'):
    return MethodRunOrchestrator(
        e['factory'], e['access'], e['bindings']).list(
            {} if params is None else params,
            _context(e['scope'], request))


def test_list_is_bounded_and_paginates_stable_run_ids(env):
    e=env
    for run_id in ('run-a','run-b','run-c'):
        call(e,'engineering.work.start',{'run_id':run_id},'start-'+run_id)
    first=_list(e,{'limit':2},'page-one')
    second=_list(e,{'after':first['next_after'],'limit':2},'page-two')
    assert [r['run_id'] for r in first['runs']]==['run-a','run-b']
    assert first['next_after']=='run-b'
    assert [r['run_id'] for r in second['runs']]==['run-c']
    assert second['next_after'] is None
    assert first['scope']==asdict(e['scope'])
    assert first['revision'] != second['revision']
    assert first['runs'][0]['method_binding']==first['runs'][0]['inputs']['method_ref']
    assert first['runs'][0]['outputs']==({'name':'primary_artifact','context_slot':'artifact_ref',
        'available':False,'reference':None},)
    assert first['runs'][0]['execution']=={'availability':'unavailable'}
    assert first['runs'][0]['review']=={'availability':'unavailable'}
    assert first['runs'][0]['acceptance']=={'availability':'unavailable'}


def test_list_excludes_rows_from_another_persisted_scope(env):
    e=env
    call(e,'engineering.work.start',{'run_id':'visible'},'start-visible')
    row=e['lib'].run_row('visible')
    foreign_inputs={**row['inputs'],'scope':{'realm_id':'foreign-realm','project_id':'foreign-project'}}
    # Insert a structurally valid historical row in the original SQLite table;
    # this isolates the adapter's scoped query predicate without another store.
    e['lib']._connection.execute(
        'INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        ('foreign-run',canonical_bytes(asdict(row['method_ref'])),
         canonical_bytes(row['registry_ref']),canonical_bytes(foreign_inputs),
         row['status'],row['cursor'],row['wait_reason'],row['created_at'],row['updated_at']))
    result=_list(e,{},'scope-filter')
    assert [run['run_id'] for run in result['runs']]==['visible']


def test_list_revision_tracks_original_run_state_change(env):
    e=env
    call(e,'engineering.work.start',{'run_id':'revision-run'},'start-revision')
    before=_list(e,{},'before-revision')
    ready=query(e,'engineering.work.current_condition',{'run_id':'revision-run'})
    call(e,'engineering.runs.resume',{
        'run_id':'revision-run','expected_row_digest':ready['row_digest'],
        'expected_condition_digest':ready['condition_digest'],
        'expected_next_step_ordinal':ready['next_step_ordinal']},'resume-revision')
    after=_list(e,{},'after-revision')
    assert before['revision'] != after['revision']
    assert before['runs'][0]['status']=='WAITING_FOR_CONDITION'
    assert after['runs'][0]['status']=='RUNNING'


def test_list_refuses_to_fabricate_empty_result_without_snapshot_reader(env):
    e=env
    call(e,'engineering.work.start',{'run_id':'reader-run'},'start-reader')
    original=e['bindings'].methods
    e['bindings'].methods=object()
    try:
        with pytest.raises(ApplicationError,match='METHOD_RUN_READER_UNAVAILABLE'):
            _list(e,{},'missing-reader')
    finally:
        e['bindings'].methods=original
