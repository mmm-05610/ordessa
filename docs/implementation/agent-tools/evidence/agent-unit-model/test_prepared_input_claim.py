"""C: original SQLite/Core claim reaches exact guarded native bytes.

Native peers, capture, Unit and authority are controlled; no family production
owner, Session association, effect proof, model or task completion is claimed.
"""
import hashlib
import json
import sys

import pytest

from test_sessionless_input import first_input, node_fixture, reserve
from ordessa_environment_api import RequestKey, UnknownResultError
from pacthold.agents.inputs import CapturedInputRef, CapturedInputEvidence, FIRST_SESSION_ATTEMPTS
from pacthold.agents.access.invocation import InvocationAuthorityRefused, InvocationIssuer
from ordessa_harness_transport import LaunchSpec, ProcessChannel, RequestTimeout, WriterLeaseRefused, LostReceipt


PEER = '''import sys,json,hashlib
for wire in sys.stdin.buffer:
    p=json.loads(wire)
    with open(sys.argv[1], 'ab') as f: f.write(wire)
    if sys.argv[2]=='lost': continue
    evidence={'wireDigest':'sha256:'+hashlib.sha256(wire).hexdigest(),'wireSize':len(wire)}
    if 'method' in p:
        result={'id':p['id'],'result':{'turn':{'id':'controlled-turn','items':[],'status':'inProgress'},**evidence}}
    else:
        result={'id':p['id'],'type':'response','command':p['type'],'success':True,'data':evidence}
    print(json.dumps(result),flush=True)
'''


@pytest.fixture(params=['codex', 'pi'])
def native_client(request, tmp_path):
    family = request.param
    script, transcript = tmp_path / 'native-C.py', tmp_path / 'received-native-C.jsonl'
    script.write_text(PEER)
    def launch(mode):
        channel = ProcessChannel.launch(LaunchSpec.build(
            [sys.executable, str(script), str(transcript), mode],
            home=str(tmp_path / 'controlled-home'), cwd=str(tmp_path)), name=f'{family}-claim-C', managed=True)
        view = channel.bind_writer(channel.acquire_writer())
        if family == 'codex':
            from ordessa_harness_codex.client import CodexAppServerClient
            client = CodexAppServerClient(view)
            def prepare(message):
                return client.prepare_request('turn/start', {'threadId': 'controlled-thread',
                    'input': [{'type': 'text', 'text': message}]})
        else:
            from ordessa_harness_pi.client import PiRpcClient
            client = PiRpcClient(view)
            def prepare(message): return client.prepare_request('prompt', {'message': message})
        handles.append((client, channel))
        return client, channel, prepare, transcript
    handles = []
    yield launch
    for client, channel in handles:
        client.close()
        channel.close(timeout=2)
        assert channel._process.poll() is not None


def admission(p, frame, *, correlation_changes=None):
    capture = CapturedInputRef('env', 'original-native-capture', 1, frame.frame_digest)
    p[3].values[capture.capture_id] = CapturedInputEvidence(capture, p[4].state.node_ref, 'draft-original', 1)
    correlation = {'environmentNamespace': 'env', 'protocol': frame.protocol, 'requestId': frame.request_id}
    correlation.update(correlation_changes or {})
    operation = p[5].reserve(RequestKey('env', 'principal', 'original-native-input'), p[2], capture, correlation)
    context = p[5].claim_dispatch(operation.request, p[8])
    return operation, context


def actual_guard(p, operation, context, protocol, seen):
    def guard(wire):
        native = json.loads(wire)
        correlation = operation.intent.context_ref['nativeCorrelation']
        capture = operation.intent.context_ref['capturedInputRef']
        if (capture['contentDigest'] != 'sha256:' + hashlib.sha256(wire).hexdigest()
                or native['id'] != correlation['requestId']
                or type(native['id']) is not type(correlation['requestId'])
                or protocol != correlation['protocol']):
            raise PermissionError('actual native frame differs from original capture/correlation')
        facts = p[8].verifier().verify_and_consume(context, 'submitInput', p[4].state.provider_ref,
                                                  p[4].state.unit_ref, operation.digest)
        seen.append((wire, facts))
    return guard


def assert_original_unknown_hold(p, operation):
    assert p[0].read_operation_step(operation.request, 'native-input').outcome == 'possibly-dispatched'
    assert p[0].list_domain('env', FIRST_SESSION_ATTEMPTS)[0]['value']['state'] == 'held'
    with pytest.raises(UnknownResultError): p[5].claim_dispatch(operation.request, p[8])
    with pytest.raises(UnknownResultError): reserve(p, key='cannot-change-key', draft='cannot-change-draft')
    assert p[4].dispatch_calls == 0


def test_original_core_claim_capture_and_native_write_are_one_identity(first_input, native_client):
    client, channel, prepare, transcript = native_client('receipt')
    frame = prepare('原始输入\nexact UTF-8')
    assert not transcript.exists()
    operation, context = admission(first_input, frame)
    seen = []
    result = client.dispatch_prepared(frame, before_write=actual_guard(first_input, operation, context, frame.protocol, seen), timeout=2)
    evidence = result.get('data', result)
    assert evidence['wireDigest'] == frame.frame_digest and evidence['wireSize'] == len(frame.frame_bytes)
    assert transcript.read_bytes() == frame.frame_bytes and seen[0][0] == frame.frame_bytes
    assert len(seen) == 1 and seen[0][1]['targetRef'] == first_input[4].state.unit_ref
    assert channel._prepared_inflight == {} and channel._unresolved is False
    # Native ACK says accepted only; it cannot publish Core or release first hold.
    assert_original_unknown_hold(first_input, operation)
    with pytest.raises(UnknownResultError):
        first_input[8].verifier().verify_and_consume(context, 'submitInput', first_input[4].state.provider_ref,
                                                     first_input[4].state.unit_ref, operation.digest)


def test_authority_revoked_after_claim_refuses_at_actual_write(first_input, native_client):
    client, channel, prepare, transcript = native_client('receipt')
    frame = prepare('cannot send after revocation')
    operation, context = admission(first_input, frame)
    first_input[6].allowed = False
    seen = []
    with pytest.raises(InvocationAuthorityRefused):
        client.dispatch_prepared(frame, before_write=actual_guard(first_input, operation, context, frame.protocol, seen), timeout=2)
    assert seen == [] and not transcript.exists() and channel.poll_message(timeout=.02) is None
    with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
    with pytest.raises(InvocationAuthorityRefused): first_input[5].claim_dispatch(operation.request, first_input[8])
    first_input[6].allowed = True  # restored grant still cannot mint a second claim
    assert_original_unknown_hold(first_input, operation)


def test_different_prepared_frame_cannot_spend_original_context(first_input, native_client):
    client, channel, prepare, transcript = native_client('receipt')
    original, other = prepare('original captured'), prepare('different unadmitted bytes')
    operation, context = admission(first_input, original)
    seen = []
    with pytest.raises(PermissionError):
        client.dispatch_prepared(other, before_write=actual_guard(first_input, operation, context, original.protocol, seen), timeout=2)
    assert seen == [] and not transcript.exists() and channel.poll_message(timeout=.02) is None
    with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
    assert_original_unknown_hold(first_input, operation)


def test_original_missing_receipt_never_resends_or_frees_core_claim(first_input, native_client):
    client, channel, prepare, transcript = native_client('lost')
    frame = prepare('one original input')
    operation, context = admission(first_input, frame)
    seen = []
    with pytest.raises(RequestTimeout):
        client.dispatch_prepared(frame, before_write=actual_guard(first_input, operation, context, frame.protocol, seen), timeout=.2)
    assert len(seen) == 1 and transcript.read_bytes() == frame.frame_bytes
    with pytest.raises(LostReceipt):
        client.dispatch_prepared(prepare('different input cannot bypass unknown'), before_write=lambda wire: None)
    with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
    assert transcript.read_bytes() == frame.frame_bytes
    assert_original_unknown_hold(first_input, operation)


@pytest.mark.parametrize('damage', ['request-id', 'id-type', 'protocol'])
def test_correct_capture_hash_cannot_hide_wrong_native_correlation(first_input, native_client, damage):
    client, channel, prepare, transcript = native_client('receipt')
    frame = prepare('correct captured bytes')
    changes = {'request-id': {'requestId': 'foreign'}, 'id-type': {'requestId': 1},
               'protocol': {'protocol': 'foreign-native/1'}}[damage]
    operation, context = admission(first_input, frame, correlation_changes=changes)
    assert operation.intent.context_ref['capturedInputRef']['contentDigest'] == frame.frame_digest
    seen = []
    with pytest.raises(PermissionError):
        client.dispatch_prepared(frame, before_write=actual_guard(first_input, operation, context, frame.protocol, seen), timeout=2)
    assert seen == [] and not transcript.exists()
    with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
    assert_original_unknown_hold(first_input, operation)


def test_boolean_native_correlation_refuses_before_original_claim(first_input, native_client):
    client, channel, prepare, transcript = native_client('receipt')
    frame = prepare('unadmitted')
    with pytest.raises(ValueError): admission(first_input, frame, correlation_changes={'requestId': True})
    assert not transcript.exists() and first_input[0].list_domain('env', FIRST_SESSION_ATTEMPTS) == ()
    assert first_input[0].read_operation(RequestKey('env', 'principal', 'original-native-input')) is None
    assert channel._prepared_inflight == {} and channel._unresolved is False


def test_correct_frame_cannot_use_foreign_issuer_context(first_input, native_client):
    client, channel, prepare, transcript = native_client('receipt')
    frame = prepare('correct original frame')
    operation, context = admission(first_input, frame)
    foreign = (*first_input[:8], InvocationIssuer(first_input[0], first_input[6], first_input[7], clock=lambda: 50))
    seen = []
    with pytest.raises(InvocationAuthorityRefused):
        client.dispatch_prepared(frame, before_write=actual_guard(foreign, operation, context, frame.protocol, seen), timeout=2)
    assert seen == [] and not transcript.exists()
    with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
    assert_original_unknown_hold(first_input, operation)


def test_post_verification_owner_fence_stops_actual_write(first_input, native_client):
    client, channel, prepare, transcript = native_client('receipt')
    frame = prepare('one admitted original')
    operation, context = admission(first_input, frame)
    seen = []
    original_guard = actual_guard(first_input, operation, context, frame.protocol, seen)
    def verified_then_cut(wire):
        original_guard(wire)
        first_input[6].allowed = False
        channel.fence_all()  # explicit owner transport cut; bool change alone is no IO fence
    with pytest.raises(WriterLeaseRefused):
        client.dispatch_prepared(frame, before_write=verified_then_cut, timeout=2)
    assert len(seen) == 1 and not transcript.exists() and channel.poll_message(timeout=.02) is None
    with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
    first_input[6].allowed = True
    assert_original_unknown_hold(first_input, operation)
    with pytest.raises(UnknownResultError):
        first_input[8].verifier().verify_and_consume(context, 'submitInput', first_input[4].state.provider_ref,
                                                     first_input[4].state.unit_ref, operation.digest)
