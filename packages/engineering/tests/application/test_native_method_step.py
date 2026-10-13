"""MethodRun joins exact outcomes from the original SQLite dispatch journal.

Dispatch reservation, prompt/result blobs, command journal, run and step rows
use the real original EngineeringLibrary/UoW. The method package repository is
the explicit resolver stub inherited from test_dispatch_method_run; this does
not claim production Grant admission or native execution.
"""
import asyncio
import hashlib
from dataclasses import asdict

import pytest

from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.run_waits import run_wait_row_digest
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_infrastructure.encoding import canonical_bytes
from test_dispatch_method_run import (
    _begin_running, _stub_package_resolver, dispatch_setup,
)
from test_method_work import env,query
from test_review_usecases import _context


def _blob(store, payload):
    raw = canonical_bytes(payload)
    return store.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()),
                              'application/json')


def _reserve(setup, phase='completed', *, wrong_unit=False):
    e = setup['env']
    _begin_running(setup)
    unit = {'environmentNamespace': 'fixture', 'unitId': 'unit',
            'ownerProviderRef': {'provider': 'fixture'}, 'sourceRevision': 'r1'}
    if wrong_unit:
        unit = {**unit, 'unitId': 'different-unit'}
    blobs = SQLiteBlobStore(e['lib'])
    prompt = _blob(blobs, {'sessionId': 'fixture-session'})
    result = _blob(blobs, {'outcome': phase})
    binding = DispatchBinding(
        scope=e['scope'], run_id='dispatch-run', step_id='dispatch', attempt=1,
        fence=1, package_ref=setup['package'].ref,
        approval_ref=ApprovalRef(e['scope'].realm_id, e['scope'].project_id,
                                 'fixture-approval', Digest('sha256', 'a' * 64)),
        intent_digest=Digest('sha256', 'b' * 64), control_version=0,
        action_instances=(('run_checks', 'fixture-action'),),
        unit_ref_bytes=canonical_bytes(unit), execution_operation_ref='fixture-execution',
        prompt_ref=prompt, prompt_input_digest=Digest('sha256', 'c' * 64),
        expected_query_digest='fixture-query', required_results=('submission',))
    encoded = encode_dispatch(binding)
    with e['factory'].begin(e['scope']) as uow:
        dispatch = uow.dispatch.reserve('dispatch-run', 'dispatch', 1, e['scope'],
            encoded, Digest('sha256',hashlib.sha256(encoded).hexdigest()), binding.execution_operation_ref)
        dispatch = uow.dispatch.transition('dispatch-run', 'dispatch', 1, e['scope'],
            expected_version=0, fence=1, phase='possibly_written')
        dispatch = uow.dispatch.transition('dispatch-run', 'dispatch', 1, e['scope'],
            expected_version=1, fence=1, phase=phase, result_blob_ref=result)
        uow.commit()
    return {'setup': setup, 'binding': binding, 'dispatch': dispatch, 'result_ref': result}


def _params(e, *, attempt=1):
    row = e['lib'].run_row('dispatch-run')
    return {'run_id': 'dispatch-run', 'attempt': attempt,
            'expected_row_digest': asdict(run_wait_row_digest(row)),
            'expected_next_step_ordinal': 1}


def _record(e, params, request_id):
    return asyncio.run(e['facade'].execute(
        'engineering.work.record_dispatch_step', params,
        _context(e['scope'], request_id)))


def _dispatch_row(e):
    with e['lib']._read_connection() as connection:
        return connection.execute(
            "SELECT ordinal,step_id,attempt,status,dispatch_phase,dispatch_version,result_blob_json "
            "FROM step_log WHERE run_id='dispatch-run' AND binding_digest IS NOT NULL").fetchone()


def _step_count(e):
    with e['lib']._read_connection() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM step_log WHERE run_id='dispatch-run'").fetchone()[0]


@pytest.mark.parametrize(('phase', 'expected_stop'), [('completed', 'accepted'), ('failed', 'rejected')])
def test_native_dispatch_completed_and_failed_select_declared_method_outcome(
        dispatch_setup, monkeypatch, phase, expected_stop):
    prepared = _reserve(dispatch_setup, phase)
    e = dispatch_setup['env']
    resolver_calls = []
    _stub_package_resolver(monkeypatch, dispatch_setup['package'], resolver_calls)
    params = _params(e)

    first = _record(e, params, 'record-dispatch-' + phase)
    assert first.status == 'completed'
    run = e['lib'].run_row('dispatch-run')
    assert run['status'] == 'SLICE_DONE'
    assert run['cursor'] == (2 if phase=='completed' else 1)
    assert resolver_calls == [dispatch_setup['package'].ref]
    assert _step_count(e) == 2  # original dispatch reservation plus MethodRun receipt
    dispatch_row = _dispatch_row(e)
    assert dispatch_row[3:5] == (phase, phase)
    board=query(e,'engineering.runs.list',{})['runs'][0]
    assert board['execution']['availability']=='available'
    assert board['execution']['dispatches'][0]['phase']==phase
    assert board['review']=={'availability':'unavailable'}
    assert board['acceptance']=={'availability':'unavailable'}

    replay = _record(e, params, 'record-dispatch-' + phase)
    assert replay == first
    assert _step_count(e) == 2
    with pytest.raises(ApplicationError, match='WORK_OPERATION_UNAVAILABLE'):
        _record(e, params, 'second-consumer-' + phase)
    assert _step_count(e) == 2

    # Reopening the original file recovers the terminal cursor and both rows.
    path, library_id = e['lib'].path, e['lib'].library_id
    e['lib'].close()
    reopened = EngineeringLibrary.open(path, library_id=library_id)
    try:
        assert reopened.run_row('dispatch-run')['status'] == 'SLICE_DONE'
        assert reopened.run_row('dispatch-run')['cursor'] == (2 if phase=='completed' else 1)
        assert len(reopened.step_rows('dispatch-run')) == 2
    finally:
        reopened.close()


def test_unknown_native_dispatch_outcome_preserves_cursor_and_writes_no_receipt(
        dispatch_setup, monkeypatch):
    _reserve(dispatch_setup, 'unknown')
    e = dispatch_setup['env']
    _stub_package_resolver(monkeypatch, dispatch_setup['package'], [])
    before = e['lib'].run_row('dispatch-run')
    with pytest.raises(ApplicationError, match='WORK_OPERATION_OUTCOME_UNKNOWN'):
        _record(e, _params(e), 'unknown-dispatch-result')
    assert e['lib'].run_row('dispatch-run') == before
    assert _step_count(e) == 1
    assert _dispatch_row(e)[3:5] == ('unknown', 'unknown')


@pytest.mark.parametrize(('attempt', 'wrong_unit', 'error'), [
    (2, False, 'WORK_DISPATCH_RESULT_MISMATCH'),
    (1, True, 'WORK_DISPATCH_RESULT_MISMATCH'),
])
def test_native_dispatch_rejects_wrong_attempt_or_method_mapped_unit_without_consuming(
        dispatch_setup, monkeypatch, attempt, wrong_unit, error):
    _reserve(dispatch_setup, 'completed', wrong_unit=wrong_unit)
    e = dispatch_setup['env']
    _stub_package_resolver(monkeypatch, dispatch_setup['package'], [])
    before = e['lib'].run_row('dispatch-run')
    params = _params(e, attempt=attempt)
    with pytest.raises(ApplicationError, match=error):
        _record(e, params, f'reject-attempt-{attempt}-unit-{wrong_unit}')
    assert e['lib'].run_row('dispatch-run') == before
    assert _step_count(e) == 1


def test_method_receipt_write_failure_rolls_back_command_and_run_atomically(
        dispatch_setup, monkeypatch):
    _reserve(dispatch_setup, 'completed')
    e = dispatch_setup['env']
    _stub_package_resolver(monkeypatch, dispatch_setup['package'], [])
    before = e['lib'].run_row('dispatch-run')
    before_dispatch = _dispatch_row(e)
    from ordessa_engineering.adapters.persistence.sqlite import workflow_transactions

    def fail_receipt(*args, **kwargs):
        raise RuntimeError('injected step receipt write failure')

    monkeypatch.setattr(workflow_transactions._TransactionScope, 'insert_step_log', fail_receipt)
    with pytest.raises(RuntimeError, match='injected step receipt write failure'):
        _record(e, _params(e), 'receipt-write-failure')
    assert e['lib'].run_row('dispatch-run') == before
    assert _dispatch_row(e) == before_dispatch
    assert _step_count(e) == 1
    with e['lib']._read_connection() as connection:
        assert connection.execute(
            "SELECT 1 FROM eng_commands WHERE operation='engineering.work.record_dispatch_step' "
            "AND request_id='receipt-write-failure'").fetchone() is None
