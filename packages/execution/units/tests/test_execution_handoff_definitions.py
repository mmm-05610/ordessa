from dataclasses import replace
import pytest
from ordessa_agents.harness.definitions import NativeContinuationRef, NativeProfileRef, NativeCredentialRef
from ordessa_units.bindings.materials import ResourceRef
from ordessa_units.definitions.execution import (
    ExecutionStartRequest, ResolvedExecutionInput, ExecutionStartReceipt,
    RecoverySupport, InvalidStartReceipt, validate_start_receipt,
)

def request():
    ref = ResourceRef('env', 'resources', 'workspace@1', 'resource', '1')
    return ExecutionStartRequest('exec', 'dispatch', 'digest', (
        ResolvedExecutionInput('workspace@1', ref, 'first'),
        ResolvedExecutionInput('workspace@1', ref, 'second'),
        ResolvedExecutionInput('native.profile@1', NativeProfileRef('profile', 'id'), 'profile'),
    ))

def test_input_handoff_preserves_order_and_is_immutable():
    req = request()
    assert req.inputs == {'workspace@1': ('first', 'second'), 'native.profile@1': ('profile',)}
    with pytest.raises(TypeError):
        req.inputs['workspace@1'] = ()

def test_handoff_refuses_unknown_and_mismatched_resource_owners():
    with pytest.raises(TypeError):
        ResolvedExecutionInput('workspace@1', object(), 'value')
    with pytest.raises(ValueError):
        ResolvedExecutionInput('prompt@1', request().resolved_inputs[0].ref, 'value')

def test_receipt_ephemeral_handle_and_valid_identity():
    class Handle:
        native_result = 'result'
    receipt = ExecutionStartReceipt('exec', 'dispatch', 'digest', runtime_handle=Handle())
    validate_start_receipt('codex', request(), receipt)
    assert receipt.native_result == 'result'
    assert 'Handle' not in repr(receipt)
    with pytest.raises(AttributeError):
        ExecutionStartReceipt('exec', 'dispatch', 'digest').native_result

@pytest.mark.parametrize('field,value', [('execution_id', 'other'), ('dispatch_id', 'other'), ('inputs_digest', 'other')])
def test_receipt_rejects_identity_mismatch(field, value):
    with pytest.raises(InvalidStartReceipt, match='identity'):
        validate_start_receipt('codex', request(), replace(ExecutionStartReceipt('exec', 'dispatch', 'digest'), **{field: value}))

@pytest.mark.parametrize('support', [RecoverySupport.OBSERVE, RecoverySupport.CONTROL])
def test_recoverable_receipt_requires_exact_provider_continuation(support):
    receipt = ExecutionStartReceipt('exec', 'dispatch', 'digest', support)
    with pytest.raises(InvalidStartReceipt, match='requires correlation'):
        validate_start_receipt('codex', request(), receipt)
    with pytest.raises(InvalidStartReceipt, match='belong'):
        validate_start_receipt('codex', request(), replace(receipt, correlation_ref=NativeContinuationRef('other', 'session')))
    with pytest.raises(InvalidStartReceipt, match='continuation'):
        validate_start_receipt('codex', request(), replace(receipt, correlation_ref=NativeCredentialRef('codex', 'credential')))
    validate_start_receipt('codex', request(), replace(receipt, correlation_ref=NativeContinuationRef('codex', 'session')))

def test_string_recovery_is_not_negotiated_enum():
    with pytest.raises(InvalidStartReceipt, match='recovery_support'):
        validate_start_receipt('codex', request(), ExecutionStartReceipt('exec', 'dispatch', 'digest', 'observe'))
