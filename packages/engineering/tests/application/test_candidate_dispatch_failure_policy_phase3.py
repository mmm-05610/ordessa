"""Candidate failed-dispatch policy projected through the original MethodRun.

This is a controlled frozen-method projection with the candidate's exact
failed -> revision_required route. It uses the original SQLite dispatch row,
result BlobRef, and public record_dispatch_step command; it is not a complete
candidate 2.6 business run or a production Unit execution.
"""
import contextlib
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import yaml

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.method_work import WORK_CONTRACT, WAIT_EVENT, WorkSeed
from ordessa_engineering.application.contracts.run_waits import run_wait_row_digest
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.definitions.models import MethodSource
from ordessa_engineering.methods.definitions.models.capabilities import CompilationCapabilities
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_infrastructure.encoding import canonical_bytes
from test_method_work import env, query
from test_native_method_step import (
    _begin_running, _blob, _dispatch_row, _record, _step_count,
    _stub_package_resolver,
)
from test_review_usecases import _context


def _candidate_failed_setup(e):
    candidate = Path(__file__).resolve().parents[4] / 'methods/incremental-engineering/candidates/2.6.0'
    declared = yaml.safe_load((candidate/'workflows/change-cycle.yaml').read_text())
    dispatch = next(node for node in declared['steps'] if node['id'] == 'dispatch')
    assert dispatch['outcomes']['failed'] == {'stop': 'revision_required'}
    assert dispatch['outcomes']['unknown'] == {'stop': 'unknown'}
    descriptor = next(item for item in owner_capabilities()
                      if item.capability_id == 'engineering.executions.dispatch')
    caps = CompilationCapabilities(
        (*command_capabilities().capabilities, descriptor), trust_class='host')
    root = e['root'].parent / 'candidate-failed-dispatch-method'
    root.mkdir()
    workflow = {
        'schema_version': 1,
        'workflow_id': 'candidate-failed-dispatch-policy',
        'entry': 'gate',
        'resume_contract': WORK_CONTRACT,
        'context_slots': ['package_ref', 'dispatch_input'],
        'wait_kinds': ['owner_reconciliation'],
        'stop_outcomes': ['accepted', 'revision_required', 'unknown'],
        'steps': [
            {'id': 'gate', 'kind': 'wait', 'event': WAIT_EVENT, 'next': 'dispatch'},
            {'id': 'dispatch', 'kind': 'operation',
             'operation': 'engineering.executions.dispatch',
             'config': {'package_slot': 'package_ref'},
             'inputs': {'dispatch': 'dispatch_input'},
             'outcomes': {
                 'completed': {'next': 'done'},
                 'failed': dispatch['outcomes']['failed'],
                 'unknown': dispatch['outcomes']['unknown'],
             }},
            {'id': 'done', 'kind': 'stop', 'outcome': 'accepted'},
        ],
    }
    raw = json.dumps(workflow).encode()
    (root / 'workflow.yaml').write_bytes(raw)
    manifest = json.loads((e['root'] / 'method.yaml').read_text())
    manifest['method_id'] = 'test.candidate-failed-dispatch-policy'
    manifest['resources'][0]['sha256'] = hashlib.sha256(raw).hexdigest()
    manifest['requires'] = [{
        'capability_id': descriptor.capability_id,
        'kind': descriptor.kind,
        'interface_version': descriptor.interface_version,
        'contract_digest': descriptor.contract_digest,
    }]
    (root / 'method.yaml').write_text(json.dumps(manifest))
    loaded = load_method(MethodSource(root), FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, caps, 'fixture/compiler')
    assert compiled.ok, compiled.error
    published = freeze_method(compiled.value, e['store'], e['store'],
        capability_catalog=SimpleNamespace(read_current=lambda: caps))
    assert published.ok, published.error
    ref = published.value.ref
    method = MethodRef(ref.method_id, ref.release_version, ref.schema_version,
                       Digest('sha256', ref.snapshot_digest))
    e['management'].adopt(method, _context(e['scope'], 'adopt-failed-policy'),
                          expected_version=1)

    package_ref = ImplementationPackageRef(e['scope'].realm_id, e['scope'].project_id,
        'candidate-failed-policy-package', Digest('sha256', 'd' * 64))
    package = SimpleNamespace(scope=e['scope'], ref=package_ref,
        payload=SimpleNamespace(method_ref=method))

    @contextlib.contextmanager
    def guard_start(context, snapshot, *, run_id, selection):
        assert run_id == 'dispatch-run' and selection is None
        slots = {
            'package_ref': asdict(package_ref),
            'dispatch_input': {
                'run_id': 'dispatch-run', 'step_id': 'dispatch', 'attempt': 1,
                'unit_ref': {'environmentNamespace': 'fixture', 'unitId': 'unit',
                    'ownerProviderRef': {'provider': 'fixture'}, 'sourceRevision': 'r1'},
                'params': {}, 'actions': ['run_checks'], 'timeout': 1,
            },
        }
        yield WorkSeed(slots, e['source'].start_reads)

    e['source'].guard_start = guard_start
    return {'env': e, 'method': method, 'package': package,
            'bindings': e['bindings']}


def _reserve_failed(setup):
    e = setup['env']
    _begin_running(setup)
    unit = {'environmentNamespace': 'fixture', 'unitId': 'unit',
            'ownerProviderRef': {'provider': 'fixture'}, 'sourceRevision': 'r1'}
    blobs = SQLiteBlobStore(e['lib'])
    prompt = _blob(blobs, {'sessionId': 'candidate-failure-session'})
    native_result = {'outcome': 'failed', 'reason': 'native checker rejected revision'}
    raw_result = canonical_bytes(native_result)
    result = _blob(blobs, native_result)
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
        uow.dispatch.reserve('dispatch-run', 'dispatch', 1, e['scope'], encoded,
            Digest('sha256', hashlib.sha256(encoded).hexdigest()),
            binding.execution_operation_ref)
        uow.dispatch.transition('dispatch-run', 'dispatch', 1, e['scope'],
            expected_version=0, fence=1, phase='possibly_written')
        uow.dispatch.transition('dispatch-run', 'dispatch', 1, e['scope'],
            expected_version=1, fence=1, phase='failed', result_blob_ref=result)
        uow.commit()
    return result, raw_result


def test_candidate_failed_dispatch_is_consumed_as_revision_required_with_original_failure_fact(
        env, monkeypatch):
    setup = _candidate_failed_setup(env)
    result_ref, raw_result = _reserve_failed(setup)
    _stub_package_resolver(monkeypatch, setup['package'], [])
    parameters = {
        'run_id': 'dispatch-run', 'attempt': 1,
        'expected_row_digest': asdict(run_wait_row_digest(
            env['lib'].run_row('dispatch-run'))),
        'expected_next_step_ordinal': 1,
    }
    first = _record(env, parameters, 'candidate-failed-dispatch-record')

    row = env['lib'].run_row('dispatch-run')
    assert row['status'] == 'SLICE_DONE'
    assert row['cursor'] == 1
    assert first.status == 'completed'
    assert _step_count(env) == 2
    dispatch_row = _dispatch_row(env)
    assert dispatch_row[3:5] == ('failed', 'failed')
    blobs = SQLiteBlobStore(env['lib'])
    assert blobs.read_verified(result_ref) == raw_result
    # The original step receipt records the frozen route outcome in the same
    # SQLite authority, alongside the exact failed phase and blob reference.
    step_rows = env['lib'].step_rows('dispatch-run')
    assert step_rows[1]['status'] == 'failed'
    with env['factory'].begin(env['scope'], 'read') as uow:
        receipt = uow.workflow.read(step_rows[1]['receipt_ref'])
    assert receipt['stop_outcome'] == 'revision_required'
    native_receipt = json.loads(receipt['result'])
    assert native_receipt['phase'] == 'failed'
    assert native_receipt['result_blob_ref'] == asdict(result_ref)
    assert _record(env, parameters, 'candidate-failed-dispatch-record') == first
    assert _step_count(env) == 2

    # The normal public read preserves the native phase and result locator.
    # Its receipt/result projection does not expose the blob body or a failure
    # reason field; the authoritative native reason remains in the original blob.
    public = query(env, 'engineering.work.get', {'run_id': 'dispatch-run'})
    dispatch = public['steps'][0]['dispatch']
    assert dispatch['phase'] == 'failed'
    assert dispatch['result_blob_ref'] == asdict(result_ref)
    assert 'reason' not in dispatch
    assert 'native checker rejected revision' not in json.dumps(public)
    assert blobs.read_verified(result_ref) == raw_result
