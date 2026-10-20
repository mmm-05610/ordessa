"""Safe diagnostics for uncertain declared-Work native dispatch failures.

These cases use the real schema-17 SQLite Work/Grant/dispatch owners and a
controlled transport. They do not claim SDK byte-boundary evidence: this
transport deliberately reports ``native_write=None``.
"""
import asyncio
from contextlib import contextmanager
import json

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.failure_diagnostic import FailureDiagnostic
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import SQLiteWorkDispatchRepository
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_engineering.domain.common.mechanisms.codec import decode_blob_ref
from ordessa_infrastructure.encoding import decode_json
from ordessa_system_access_bindings.engineering_wire import _failure

from test_work_package_dispatch_v2 import UNIT, call, dispatch_fixture, row


def _budget(fixture):
    binding = decode_dispatch(row(fixture)['binding_bytes'])
    with fixture['factory'].begin(fixture['authorization'].scope, 'read') as uow:
        return uow.authorization.action_budget(binding.approval_ref)


def _assert_budget_consumed_once(fixture):
    assert _budget(fixture)['actions'] == [
        {'action': 'edit_repository', 'limit': 1, 'consumed': 1},
        {'action': 'run_checks', 'limit': 1, 'consumed': 1}]


def _diagnostic_from_row(fixture):
    record = row(fixture)
    assert record['result_blob_json'] is not None
    ref = decode_blob_ref(decode_json(record['result_blob_json']))
    assert ref.media_type == 'application/vnd.ordessa.dispatch-failure+json'
    raw = fixture['env'].blobs.read_verified(ref)
    value = decode_json(raw)
    diagnostic = FailureDiagnostic.from_record(value)
    return record, ref, value, diagnostic


def _value_diagnostic(answer):
    assert answer.outcome == 'unknown'
    value = answer.value
    assert isinstance(value, dict)
    assert isinstance(value.get('failure_diagnostic'), FailureDiagnostic)
    return value['failure_diagnostic']


def _assert_no_sensitive_exception_text(record):
    encoded = json.dumps(record, sort_keys=True, ensure_ascii=False)
    assert 'private-test-exception-text' not in encoded
    assert 'secret-test-cause-text' not in encoded


def test_handoff_enter_failure_records_safe_diagnostic_and_unknown_once(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        @contextmanager
        def reject_handoff(*_args, **_kwargs):
            raise PermissionError('private-test-exception-text')
            yield  # pragma: no cover - unreachable

        monkeypatch.setattr(f['transport'], 'guard_effect_handoff', reject_handoff)
        answer = call(f)

        diagnostic = _value_diagnostic(answer)
        record, ref, stored, persisted = _diagnostic_from_row(f)
        assert diagnostic == persisted
        assert answer.value['observation_ref'] == ref
        assert record['dispatch_phase'] == 'unknown'
        assert persisted.to_dict()['contract'] == 'engineering-dispatch-failure/1'
        assert persisted.to_dict()['stage'] == 'handoff_enter'
        assert persisted.to_dict()['native_write'] is None
        assert persisted.to_dict()['recording_failure'] is None
        assert persisted.to_dict()['exception_chain'][0]['type'] == 'builtins.PermissionError'
        _assert_no_sensitive_exception_text(stored)
        _assert_budget_consumed_once(f)

        replay = call(f)
        replay_diagnostic = _value_diagnostic(replay)
        assert replay_diagnostic == diagnostic
        assert f['transport'].sends == 0
        assert f['transport'].freezes == 1
        _assert_budget_consumed_once(f)
        assert row(f)['binding_bytes'] == record['binding_bytes']


def test_nested_native_exception_is_safely_chained_without_claiming_write_evidence(
        tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        transport = f['transport']

        def fail_with_cause(binding, *, timeout):
            transport.binding = binding

            async def write():
                write_identity = {'unitRef': UNIT,
                    'operationRef': binding.execution_operation_ref,
                    'inputDigest': 'sha256:' + binding.prompt_input_digest.hex,
                    'requestId': 'controlled-native-frame',
                    'frameDigest': 'sha256:' + 'e' * 64}
                loop = asyncio.get_running_loop()
                async with transport.dispatch.acquire_effect_write(transport.ctx, binding,
                        write_identity, loop.time() + 2, handoff=transport.handoff):
                    transport.sends += 1
                    try:
                        raise ConnectionError('secret-test-cause-text')
                    except ConnectionError as cause:
                        raise OSError('private-test-exception-text') from cause

            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as sdk_thread:
                sdk_thread.submit(lambda: asyncio.run(write())).result()

        monkeypatch.setattr(transport, 'send', fail_with_cause)
        answer = call(f)
        diagnostic = _value_diagnostic(answer)
        record, ref, stored, persisted = _diagnostic_from_row(f)
        data = persisted.to_dict()
        assert diagnostic == persisted
        assert answer.value['observation_ref'] == ref
        assert record['dispatch_phase'] == 'unknown'
        assert data['stage'] == 'native_send'
        assert data['native_write'] is None
        chain = data['exception_chain']
        assert [(item['type'], item['code']) for item in chain[:3]] == [
            ('ordessa_engineering.application.contracts.errors.ApplicationError',
             'METHOD_AUTHORITY_UNAVAILABLE'),
            ('builtins.OSError', None), ('builtins.ConnectionError', None)]
        assert [item['relation'] for item in chain[:3]] == ['raised', 'cause', 'cause']
        _assert_no_sensitive_exception_text(stored)
        _assert_budget_consumed_once(f)

        replay = call(f)
        assert _value_diagnostic(replay) == diagnostic
        assert transport.sends == 1
        assert transport.freezes == 1
        _assert_budget_consumed_once(f)
        assert row(f)['binding_bytes'] == record['binding_bytes']


@pytest.mark.parametrize('recording_failure', ['diagnostic_blob', 'unknown_cas'])
def test_diagnostic_recording_failure_preserves_primary_and_recording_causes(
        tmp_path, monkeypatch, recording_failure):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        transport = f['transport']
        transport.fail_send = True
        original_put = f['env'].blobs.put_verified
        if recording_failure == 'diagnostic_blob':
            def fail_diagnostic_blob(raw, digest, media_type):
                if media_type == 'application/vnd.ordessa.dispatch-failure+json':
                    raise OSError('private-test-exception-text')
                return original_put(raw, digest, media_type)
            monkeypatch.setattr(f['env'].blobs, 'put_verified', fail_diagnostic_blob)
        else:
            original_transition = SQLiteWorkDispatchRepository.transition
            failed = {'once': False}

            def fail_unknown_cas(repository, *args, phase, **kwargs):
                if phase == 'unknown' and not failed['once']:
                    failed['once'] = True
                    raise ApplicationError('DISPATCH_CHANGED')
                return original_transition(repository, *args, phase=phase, **kwargs)

            monkeypatch.setattr(SQLiteWorkDispatchRepository, 'transition', fail_unknown_cas)

        with pytest.raises(ApplicationError) as raised:
            call(f)
        error = raised.value
        assert error.code == 'DISPATCH_FAILURE_DIAGNOSTIC_UNCONFIRMED'
        assert isinstance(error.failure_diagnostic, FailureDiagnostic)
        data = error.failure_diagnostic.to_dict()
        assert data['stage'] == 'native_send'
        assert data['native_write'] is None
        assert data['recording_failure'] is not None
        assert (data['exception_chain'][0]['type'], data['exception_chain'][0]['code']) == (
            'ordessa_engineering.application.contracts.errors.ApplicationError',
            'METHOD_AUTHORITY_UNAVAILABLE')
        if recording_failure == 'diagnostic_blob':
            assert error.failure_evidence_ref is None
            assert error.failure_evidence_linked is False
        else:
            assert error.failure_evidence_ref is not None
            assert error.failure_evidence_linked is False
            linked_candidate = error.failure_evidence_ref
            assert linked_candidate.media_type == 'application/vnd.ordessa.dispatch-failure+json'
            persisted_before_row_failure = FailureDiagnostic.from_record(
                decode_json(f['env'].blobs.read_verified(linked_candidate)))
            assert persisted_before_row_failure.to_dict()['recording_failure'] is None
            assert data['recording_failure'] is not None
        _assert_no_sensitive_exception_text(data)

        preserved = row(f)
        assert preserved['dispatch_phase'] == 'possibly_written'
        assert preserved['result_blob_json'] is None
        _assert_budget_consumed_once(f)
        sends, freezes = transport.sends, transport.freezes

        replay = call(f)
        assert replay.outcome == 'unknown'
        assert transport.sends == sends == 1
        assert transport.freezes == freezes == 1
        _assert_budget_consumed_once(f)
        assert row(f)['binding_bytes'] == preserved['binding_bytes']


def test_revoked_access_code_survives_diagnostic_recording_refusal(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        transport = f['transport']
        transport.fail_send = True

        original_access = f['dispatch']._access

        def revoked_after_native_send(context, operation):
            if transport.sends >= 1:
                raise ApplicationError('ACCESS_GRANT_REVOKED')
            return original_access(context, operation)

        # The implementation owner calls this only when recording UNKNOWN,
        # after the controlled native writer has crossed its send boundary.
        monkeypatch.setattr(f['dispatch'], '_access', revoked_after_native_send)
        with pytest.raises(ApplicationError) as raised:
            call(f)
        error = raised.value
        assert error.code == 'ACCESS_GRANT_REVOKED'
        assert isinstance(error.failure_diagnostic, FailureDiagnostic)
        data = error.failure_diagnostic.to_dict()
        assert data['stage'] == 'native_send'
        assert data['recording_failure'] is not None
        assert data['recording_failure']['exception_chain'][0]['code'] == 'ACCESS_GRANT_REVOKED'
        assert error.failure_evidence_linked is False
        saved = row(f)
        assert saved['dispatch_phase'] == 'possibly_written'
        assert saved['result_blob_json'] is None
        assert transport.sends == 1
        _assert_budget_consumed_once(f)

        with pytest.raises(ApplicationError) as replay:
            call(f)
        assert replay.value.code == 'ACCESS_GRANT_REVOKED'
        assert transport.sends == 1
        assert transport.freezes == 1
        _assert_budget_consumed_once(f)


def test_failure_diagnostic_bounds_deep_and_cyclic_causes_without_text():
    cycle_outer = OSError('private-test-exception-text')
    cycle_inner = ConnectionError('secret-test-cause-text')
    cycle_outer.__cause__ = cycle_inner
    cycle_inner.__cause__ = cycle_outer
    cyclic = FailureDiagnostic.capture(cycle_outer, 'native_send').to_dict()
    assert [node['type'] for node in cyclic['exception_chain']] == [
        'builtins.OSError', 'builtins.ConnectionError']
    assert [node['relation'] for node in cyclic['exception_chain']] == ['raised', 'cause']
    assert cyclic['chain_truncated'] is True

    errors = [OSError(f'private-test-exception-text-{index}') for index in range(8)]
    for current, cause in zip(errors, errors[1:]):
        current.__cause__ = cause
    deep = FailureDiagnostic.capture(errors[0], 'native_send').to_dict()
    assert len(deep['exception_chain']) == 6
    assert deep['exception_chain'][0]['type'] == 'builtins.OSError'
    assert deep['chain_truncated'] is True
    _assert_no_sensitive_exception_text({'cyclic': cyclic, 'deep': deep})


def test_wire_failure_projection_preserves_safe_diagnostic_and_link_state():
    primary = OSError('private-test-exception-text')
    diagnostic = FailureDiagnostic.capture(primary, 'native_send')
    ref = BlobRef(Digest('sha256', 'a' * 64), 123,
        'application/vnd.ordessa.dispatch-failure+json', 'test-failure-diagnostic')
    error = ApplicationError('DISPATCH_FAILURE_DIAGNOSTIC_UNCONFIRMED', retry='reconcile',
        failure_diagnostic=diagnostic, failure_evidence_ref=ref, failure_evidence_linked=False)

    projected = _failure(error)
    body = projected.to_body()
    assert body['code'] == 'UNAVAILABLE'
    assert body['details']['internalCode'] == 'DISPATCH_FAILURE_DIAGNOSTIC_UNCONFIRMED'
    assert body['details']['recoveryAction'] == 'queryOriginalRequest'
    assert body['details']['failureDiagnostic'] == diagnostic.to_dict()
    assert body['details']['failureEvidenceRef'] == {
        'digest': {'algorithm': 'sha256', 'hex': 'a' * 64},
        'byte_length': 123, 'media_type': 'application/vnd.ordessa.dispatch-failure+json',
        'storage_object_id': 'test-failure-diagnostic'}
    assert body['details']['failureEvidenceLinked'] is False
    _assert_no_sensitive_exception_text(body)


def test_double_recording_failure_keeps_primary_and_both_recording_causes(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        transport = f['transport']
        transport.fail_send = True

        def diagnostic_capture_failure(_binding, _error, _stage):
            try:
                raise OSError('private-test-exception-text')
            except OSError as cause:
                raise ApplicationError('DIAGNOSTIC_CAPTURE_REFUSED') from cause

        monkeypatch.setattr(transport, 'failure_diagnostic', diagnostic_capture_failure,
                            raising=False)
        original_put = f['env'].blobs.put_verified

        def fail_diagnostic_blob(raw, digest, media_type):
            if media_type == 'application/vnd.ordessa.dispatch-failure+json':
                raise ConnectionError('secret-test-cause-text')
            return original_put(raw, digest, media_type)

        monkeypatch.setattr(f['env'].blobs, 'put_verified', fail_diagnostic_blob)
        with pytest.raises(ApplicationError) as raised:
            call(f)
        error = raised.value
        assert error.code == 'DISPATCH_FAILURE_DIAGNOSTIC_UNCONFIRMED'
        data = error.failure_diagnostic.to_dict()
        assert data['stage'] == 'native_send'
        assert data['exception_chain'][0]['code'] == 'METHOD_AUTHORITY_UNAVAILABLE'
        assert data['recording_failure'] is not None
        nodes = data['recording_failure']['exception_chain']
        assert [node['code'] for node in nodes[:2]] == ['DIAGNOSTIC_CAPTURE_REFUSED', None]
        assert [node['type'] for node in nodes[:2]] == [
            'ordessa_engineering.application.contracts.errors.ApplicationError',
            'builtins.OSError']
        # Sol's recording path preserves the second failure as a secondary
        # cause instead of replacing the first failure that prevented capture.
        encoded = json.dumps(data, sort_keys=True)
        assert 'DIAGNOSTIC_CAPTURE_REFUSED' in encoded
        assert 'builtins.OSError' in encoded
        assert 'builtins.ConnectionError' in encoded
        _assert_no_sensitive_exception_text(data)
        assert row(f)['dispatch_phase'] == 'possibly_written'
        assert row(f)['result_blob_json'] is None
        assert transport.sends == 1
        _assert_budget_consumed_once(f)



def test_pre_send_transition_failure_keeps_standalone_diagnostic(tmp_path, monkeypatch):
    """A refusal after the debit COMMIT must still carry bounded facts.

    Nothing was sent in this window, so the row keeps its own ``reserved``
    state and no UNKNOWN/blob is invented; the diagnostic travels on the
    error instead of being dropped with it.
    """
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        original_transition = SQLiteWorkDispatchRepository.transition

        def fail_possibly_written(repository, *args, phase, **kwargs):
            if phase == 'possibly_written':
                raise ApplicationError('DISPATCH_CHANGED')
            return original_transition(repository, *args, phase=phase, **kwargs)

        monkeypatch.setattr(SQLiteWorkDispatchRepository, 'transition', fail_possibly_written)
        with pytest.raises(ApplicationError) as raised:
            call(f)
        error = raised.value
        assert error.code == 'DISPATCH_CHANGED'
        assert isinstance(error.failure_diagnostic, FailureDiagnostic)
        data = error.failure_diagnostic.to_dict()
        assert data['stage'] == 'pre_send'
        assert data['native_write'] is None
        assert data['recording_failure'] is None
        assert data['exception_chain'][0]['code'] == 'DISPATCH_CHANGED'
        assert error.failure_evidence_ref is None
        assert error.failure_evidence_linked is False
        _assert_no_sensitive_exception_text(data)

        saved = row(f)
        assert saved['dispatch_phase'] == 'reserved'
        assert saved['result_blob_json'] is None
        assert f['transport'].sends == 0
        _assert_budget_consumed_once(f)


def test_reconcile_capture_failure_keeps_standalone_diagnostic(tmp_path, monkeypatch):
    """A cold read failure after a native send keeps its own bounded facts.

    The dispatch row stays ``possibly_written`` exactly as before: this test
    does not introduce an UNKNOWN transition, a refund or a second send.
    """
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        transport = f['transport']

        def refuse_capture(_binding):
            raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')

        monkeypatch.setattr(transport, 'capture', refuse_capture)
        with pytest.raises(ApplicationError) as raised:
            call(f)
        error = raised.value
        assert error.code == 'EXECUTION_QUERY_AUTHORITY_REQUIRED'
        assert isinstance(error.failure_diagnostic, FailureDiagnostic)
        data = error.failure_diagnostic.to_dict()
        assert data['stage'] == 'reconcile'
        assert data['native_write'] is None
        assert data['recording_failure'] is None
        assert data['exception_chain'][0]['code'] == 'EXECUTION_QUERY_AUTHORITY_REQUIRED'
        _assert_no_sensitive_exception_text(data)

        saved = row(f)
        assert saved['dispatch_phase'] == 'possibly_written'
        assert saved['result_blob_json'] is None
        assert transport.sends == 1
        _assert_budget_consumed_once(f)


@pytest.mark.parametrize('released_refusal', ['application_error', 'foreign_error'])
def test_first_guard_release_failure_after_debit_commit_keeps_standalone_diagnostic(
        tmp_path, monkeypatch, released_refusal):
    """The first guard's release runs after the debit COMMIT, outside any frame.

    Reported shape to reproduce: budget [1, 1], row reserved/version 0, zero
    sends. That state is preserved exactly; only the bounded facts on the
    refusal are added (no UNKNOWN, no blob, no refund, no second send).
    """
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        selection = f['selection']
        original = selection.guard_work_scope

        @contextmanager
        def refuse_release(ctx, package, unit_ref, authorization, actions):
            with original(ctx, package, unit_ref, authorization, actions):
                yield
            if released_refusal == 'application_error':
                raise ApplicationError('ACCESS_GRANT_REVOKED')
            raise OSError('controlled first guard release failure')

        monkeypatch.setattr(selection, 'guard_work_scope', refuse_release)
        with pytest.raises(ApplicationError) as raised:
            call(f)
        error = raised.value
        if released_refusal == 'application_error':
            # The original refusal keeps its own code and retry.
            assert error.code == 'ACCESS_GRANT_REVOKED'
        else:
            # The original method-resource guard converts a foreign release
            # failure before this dispatch sees it; that wrapper code is the
            # refusal's own code and stays untouched. The cause is preserved.
            assert error.code == 'METHOD_AUTHORITY_UNAVAILABLE'
        assert isinstance(error.failure_diagnostic, FailureDiagnostic)
        data = error.failure_diagnostic.to_dict()
        assert data['stage'] == 'pre_send'
        assert data['native_write'] is None
        assert data['recording_failure'] is None
        if released_refusal == 'application_error':
            assert data['exception_chain'][0]['code'] == 'ACCESS_GRANT_REVOKED'
        else:
            assert data['exception_chain'][0]['code'] == 'METHOD_AUTHORITY_UNAVAILABLE'
            assert data['exception_chain'][1]['relation'] == 'cause'
            assert data['exception_chain'][1]['type'] == 'builtins.OSError'
        _assert_no_sensitive_exception_text(data)

        saved = row(f)
        assert saved['dispatch_phase'] == 'reserved'
        assert saved['dispatch_version'] == 0
        assert saved['result_blob_json'] is None
        assert f['transport'].sends == 0
        _assert_budget_consumed_once(f)
