"""Fail-closed original-source boundary while real F1.2 source is incomplete."""
from types import SimpleNamespace
import pytest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.native_records.agent_execution import AgentExecutionConsumer
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError


def ref():return {'schemaVersion':'agent-instance/1','namespace':'namespace','instanceId':'instance','bindingDigest':'sha256:'+'a'*64}


def test_missing_original_source_refuses_before_prompt_blob_or_action_consumption():
    writes=[]
    blobs=SimpleNamespace(authority_id='original-library',put_verified=lambda *a:writes.append(a),read_verified=lambda _:None)
    consumer=AgentExecutionConsumer(None,blobs)
    with pytest.raises(ApplicationError,match='AGENT_ORIGINAL_INTERACTION_AUTHORITY_UNAVAILABLE'):
        consumer.claim_and_prepare(ref(),canonical_bytes({'prompt':'offline'}),request_id='request',
            engineering_attempt_ref='attempt',send_invocation=object(),read_invocation=object())
    assert writes==[]


def test_old_or_mixed_unit_reference_never_reaches_an_injected_source():
    class UnexpectedSource:
        def __getattr__(self,name):raise AssertionError('old ref reached original source')
    consumer=AgentExecutionConsumer(UnexpectedSource(),None)
    for old in ({'environmentNamespace':'n','unitId':'u','ownerProviderRef':{},'sourceRevision':'r'},
                {**ref(),'unitId':'hidden-fallback'}):
        with pytest.raises(ReferenceError):
            consumer.claim_and_prepare(old,b'{}',request_id='request',engineering_attempt_ref='attempt',
                send_invocation=object(),read_invocation=object())


def test_source_without_original_prewrite_claim_cannot_allocate_a_caller_turn():
    def unexpected(*args,**kwargs):raise AssertionError('must stop before source calls')
    source=SimpleNamespace(**{n:unexpected for n in ('freeze_prompt','turn_query','query_turn','read_binding','prompt_recorded')})
    blobs=SimpleNamespace(authority_id='original',put_verified=unexpected,read_verified=unexpected)
    consumer=AgentExecutionConsumer(source,blobs)
    with pytest.raises(ApplicationError,match='AGENT_PREWRITE_BINDING_AUTHORITY_UNAVAILABLE'):
        consumer.claim_and_prepare(ref(),b'{}',request_id='request',engineering_attempt_ref='attempt',
            send_invocation=object(),read_invocation=object())
    assert not hasattr(consumer,'send')
