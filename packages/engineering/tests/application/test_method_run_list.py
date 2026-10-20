"""Read-only MethodRun listing over the existing SQLite authority."""
from dataclasses import asdict

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_runs import MethodRunOrchestrator
from ordessa_infrastructure.encoding import canonical_bytes
from test_method_work import call, env, query, seed_historical_run
from test_review_usecases import _context


def _list(e, params=None, request='list'):
    return MethodRunOrchestrator(
        e['factory'], e['access'], e['bindings']).list(
            {} if params is None else params,
            _context(e['scope'], request))


def test_list_is_bounded_and_paginates_stable_run_ids(env):
    e=env
    for run_id in ('run-a','run-b','run-c'):
        seed_historical_run(e,run_id)
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
    seed_historical_run(e,'visible')
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
    seed_historical_run(e,'revision-run')
    before=_list(e,{},'before-revision')
    assert before['runs'][0]['status']=='WAITING_FOR_CONDITION'
    # The persisted row changes through the original storage primitive (a
    # historical state seed), never through the withdrawn advance route.
    with e['factory'].begin(e['scope']) as uow:
        uow.workflow.update_run(run_id='revision-run',status='RUNNING',cursor=0,
            wait_reason=None,now='2026-10-14T12:05:00.000000Z')
        uow.commit()
    after=_list(e,{},'after-revision')
    assert before['revision'] != after['revision']
    assert after['runs'][0]['status']=='RUNNING'


def test_list_refuses_to_fabricate_empty_result_without_snapshot_reader(env):
    e=env
    seed_historical_run(e,'reader-run')
    original=e['bindings'].methods
    e['bindings'].methods=object()
    try:
        with pytest.raises(ApplicationError,match='METHOD_RUN_READER_UNAVAILABLE'):
            _list(e,{},'missing-reader')
    finally:
        e['bindings'].methods=original
