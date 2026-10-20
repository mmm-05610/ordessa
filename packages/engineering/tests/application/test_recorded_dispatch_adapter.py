"""Synthetic public-port fixtures; these do not qualify an original SDK owner."""
import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.canonical_json import LIBRARY_JSON_PROFILE
from ordessa_engineering.adapters.native_records.recorded_dispatch import RecordedDispatchExecution
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.execution_observations import MAX_EXECUTION_RECEIPT_BYTES
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.usecases.material_closure import guard_method_resources
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.reviews.refs import ReviewRef


SCOPE = Scope('synthetic-dispatch-realm','synthetic-dispatch-project')
UNIT = {'environmentNamespace':'synthetic-env','unitId':'synthetic-unit',
        'ownerProviderRef':{'provider':'fixture','ref':'unit-a'},'sourceRevision':'sha256:'+'a'*64}
UNIT_BYTES = canonical_bytes(UNIT, profile=LIBRARY_JSON_PROFILE)
OPERATION = 'synthetic-operation-a'
SESSION = 'fixture-fixed-session'


def digest(raw):
    return Digest('sha256',hashlib.sha256(raw).hexdigest())


def native_digest(value):
    return 'sha256:' + hashlib.sha256(canonical_bytes({'value':value}, profile=LIBRARY_JSON_PROFILE)).hexdigest()


def blob_ref(raw, media='application/json'):
    return BlobRef(digest(raw),len(raw),media,'synthetic-blob-' + digest(raw).hex)


class ExplicitRecordsFixture:
    """Duck-shaped public Records API, not its original issuer, verifier, or journal."""
    def __init__(self):
        self.prompt_calls=[]
        self.query_calls=[]
        self.reserved=set()
        self.receipt=None
        self.acp_turn_evidence_max_bytes=MAX_EXECUTION_RECEIPT_BYTES
        self.prompt_capacity_calls=[]
        self.reject_prompt_capacity=False

    def validate_acp_prompt_capacity(self, unit_ref, params):
        self.prompt_capacity_calls.append((dict(unit_ref), params))
        if self.reject_prompt_capacity:
            raise _AcpEvidenceCapacityRefused()
        return None

    @staticmethod
    def acp_prompt_input_digest(unit_ref, params):
        return native_digest({'unitRef':dict(unit_ref),'params':params})

    @staticmethod
    def acp_turn_query_digest(unit_ref, operation_ref, prompt_digest):
        return native_digest({'action':'query-acp-turn','unitRef':dict(unit_ref),
                              'operationRef':operation_ref,'expectedPromptInputDigest':prompt_digest})

    def query_acp_turn(self, unit_ref, operation_ref, context, *, input_digest, expected_prompt_input_digest):
        self.query_calls.append((dict(unit_ref),operation_ref,input_digest,expected_prompt_input_digest))
        assert context.facts['inputDigest'] == input_digest
        assert input_digest == self.acp_turn_query_digest(unit_ref,operation_ref,expected_prompt_input_digest)
        return self.receipt


class _AcpEvidenceCapacityRefused(Exception):
    code='ACP_EVIDENCE_CAPACITY_EXCEEDED'


class ExplicitBlobFixture:
    """Synthetic same-authority verified-byte API for this adapter test only."""
    def __init__(self, authority_id='synthetic-engineering-library'):
        self.authority_id=authority_id
        self.values={}

    def put_verified(self, raw, expected_digest, media_type):
        assert digest(raw) == expected_digest
        ref=BlobRef(expected_digest,len(raw),media_type,'synthetic-blob-' + expected_digest.hex)
        self.values[ref.storage_object_id]=raw
        return ref

    def read_verified(self, ref):
        raw=self.values[ref.storage_object_id]
        assert digest(raw)==ref.digest and len(raw)==ref.byte_length
        return raw


class ExplicitUnitFixture:
    """Test double for original UnitInstance public surface; not the SDK owner."""
    def __init__(self, records):
        self.records=records
        self.projection=SimpleNamespace(read_session=lambda unit_ref:
            SimpleNamespace(native_facts={'sessionId':SESSION}))
        self.calls=[]
        self.seen_operations=set()
        self.effect_factory=None

    def require_effect_write_guard(self, factory):
        if factory is None or factory is not self.effect_factory:
            raise ApplicationError("RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED")

    def prompt(self, unit_ref, lease, *, operation_ref, timeout=60, **params):
        if operation_ref in self.seen_operations:
            raise ApplicationError('ORIGINAL_RECORDS_DUPLICATE_OPERATION')
        self.seen_operations.add(operation_ref)
        self.calls.append((dict(unit_ref),lease,operation_ref,timeout,params))
        return {'nativeReceipt':'fixture-only','state':'completed'}


def adapter(*, query_factory=None):
    records=ExplicitRecordsFixture()
    unit=ExplicitUnitFixture(records)
    blobs=ExplicitBlobFixture()
    lease=object()
    effect_factory=lambda *_:None  # Explicit configuration-identity fixture, not a real authority.
    unit.effect_factory=effect_factory
    return RecordedDispatchExecution(records,unit,lease,blobs,query_factory,
        effect_write_guard_factory=effect_factory),records,unit,blobs,lease


def binding_for(adapter_value, records, blobs, *, params=None, operation=OPERATION,
                expected_query_digest=None, required_results=('reserved','possibly-written','completed','failed','unknown')):
    params = {'prompt':[], 'sessionId':SESSION} if params is None else params
    prompt_raw=canonical_bytes(params,profile=LIBRARY_JSON_PROFILE)
    prompt_ref=blobs.put_verified(prompt_raw,digest(prompt_raw),'application/json')
    prompt_digest=Digest('sha256',records.acp_prompt_input_digest(UNIT,params)[7:])
    query_digest=records.acp_turn_query_digest(UNIT,operation,'sha256:'+prompt_digest.hex)
    return DispatchBinding(
        scope=SCOPE,run_id='run-a',step_id='step-a',attempt=1,fence=1,
        package_ref=ImplementationPackageRef(SCOPE.realm_id,SCOPE.project_id,'fixture-package',digest(b'package')),
        approval_ref=ApprovalRef(SCOPE.realm_id,SCOPE.project_id,'fixture-approval',digest(b'approval')),
        intent_digest=digest(b'intent'),control_version=0,
        action_instances=(('edit_repository','00000000-0000-0000-0000-000000000001'),),
        unit_ref_bytes=UNIT_BYTES,execution_operation_ref=operation,prompt_ref=prompt_ref,
        prompt_input_digest=prompt_digest,
        expected_query_digest=query_digest if expected_query_digest is None else expected_query_digest,
        required_results=required_results)


def reviewed_change_v2_binding(records, blobs):
    params = {'prompt': [], 'sessionId': SESSION}
    prompt_raw = canonical_bytes(params, profile=LIBRARY_JSON_PROFILE)
    prompt_ref = blobs.put_verified(prompt_raw, digest(prompt_raw), 'application/json')
    prompt_digest = Digest('sha256', records.acp_prompt_input_digest(UNIT, params)[7:])
    operation = 'work-generation-operation'
    query_digest = records.acp_turn_query_digest(
        UNIT, operation, 'sha256:' + prompt_digest.hex)
    review_ref = ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'review-v2', digest(b'review-v2'))
    change_ref = ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-v2', 'proposal-v2',
                             digest(b'proposal-v2'))
    method_ref = MethodRef('incremental-engineering', '2.7.2', 2, digest(b'method-v2'))
    identity = 'w1:work-v2:incremental.prepare-packages:draft'
    return DispatchBinding(
        scope=SCOPE, run_id=identity, step_id='draft', attempt=1, fence=1,
        package_ref=None, approval_ref=None, intent_digest=None, control_version=None,
        action_instances=(('generate_package', 'generation-instance-v2'),),
        unit_ref_bytes=UNIT_BYTES, execution_operation_ref=operation, prompt_ref=prompt_ref,
        prompt_input_digest=prompt_digest, expected_query_digest=query_digest,
        required_results=('submission',), binding_version=2,
        work={'work_id': 'work-v2', 'action_id': 'incremental.prepare-packages',
              'step_id': 'draft', 'dispatch_key': identity},
        subject={'subject_kind': 'reviewed_change', 'subject_ref': {
            'review_ref': asdict(review_ref), 'change_ref': asdict(change_ref),
            'method_ref': asdict(method_ref),
            'inputs_digest': asdict(digest(b'inputs-v2'))}})


def receipt_for(records, binding, state='unknown'):
    prompt_digest='sha256:'+binding.prompt_input_digest.hex
    query_digest=records.acp_turn_query_digest(UNIT,binding.execution_operation_ref,prompt_digest)
    records.receipt={'contractVersion':'unit-acp-turn/1','unitRef':dict(UNIT),
        'operationRef':binding.execution_operation_ref,'inputDigest':prompt_digest,'state':state,
        'revision':2,'events':[],'eventsDigest':'fixture-events-digest','request':None,
        'response':None,'responseDigest':'fixture-response-digest','summary':None}
    return SimpleNamespace(facts={'inputDigest':query_digest})


def large_receipt_for(records, blobs, binding, *, text_bytes):
    params=decode_json(blobs.read_verified(binding.prompt_ref))
    input_value={'unitRef':dict(UNIT),'params':params}
    prompt_text='x'*text_bytes
    raw={'jsonrpc':'2.0','id':1,'method':'session/prompt','params':params}
    frame=(json.dumps(raw,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    events=[{'sequence':1,'sessionMatched':True,'raw':{
        'jsonrpc':'2.0','method':'session/update','params':{
            'sessionId':SESSION,'update':{'sessionUpdate':'agent_message_chunk',
                'content':{'type':'text','text':prompt_text}}}}}]
    response=None
    records.receipt={
        'contractVersion':'unit-acp-turn/1','operationRef':binding.execution_operation_ref,
        'unitRef':dict(UNIT),'unitIntentDigest':'a'*64,'nativeBinding':{'sessionId':SESSION},
        'input':input_value,'inputDigest':native_digest(input_value),
        'state':'unknown','revision':3,
        'request':{'raw':raw,'frameUtf8':frame.decode(),
                   'frameDigest':'sha256:'+hashlib.sha256(frame).hexdigest()},
        'events':events,'eventsDigest':native_digest(events),'response':response,
        'responseDigest':native_digest(response),
        'observationAssociation':'session-request-window',
        'summary':{'text':prompt_text,'textDigest':native_digest(prompt_text),
                   'stopReason':None,'eventCount':1,'knownRemoteFailure':False,
                   'successfulRpcResponse':False,'modelQualityVerified':False}}
    query_digest=records.acp_turn_query_digest(
        UNIT,binding.execution_operation_ref,'sha256:'+binding.prompt_input_digest.hex)
    return SimpleNamespace(facts={'inputDigest':query_digest})


def test_freeze_input_pins_fixed_session_and_uses_records_native_digest():
    port,records,_,_,_=adapter()
    raw,input_digest=port.freeze_input(UNIT,{'prompt':[{'text':'fixture'}]})
    params=decode_json(raw)
    assert params['sessionId']==SESSION
    assert input_digest.hex == records.acp_prompt_input_digest(UNIT,params)[7:]
    assert raw == canonical_bytes(params,profile=LIBRARY_JSON_PROFILE)
    binding=binding_for(port,records,port.blobs,params=params)
    assert port.query_digest(UNIT,OPERATION,input_digest)==binding.expected_query_digest


@pytest.mark.parametrize('params',[
    {'prompt':[],'sessionId':'other-session'},
    {'prompt':[],'on_request':'callback'},
    {'prompt':[],'nested':{'before_write':'callback'}},
])
def test_freeze_input_rejects_session_override_and_callbacks(params):
    port,_,_,_,_=adapter()
    with pytest.raises(ApplicationError):
        port.freeze_input(UNIT,params)


def test_freeze_input_enforces_original_prompt_byte_limit():
    port,_,_,_,_=adapter()
    with pytest.raises(ApplicationError,match='RECORDED_DISPATCH_INPUT_TOO_LARGE'):
        port.freeze_input(UNIT,{'prompt':'x'*(576*1024)})


def test_freeze_input_accepts_a_prompt_at_the_576kib_byte_limit():
    port,records,_,_,_=adapter()
    raw,input_digest=port.freeze_input(UNIT,{'prompt':'x'*(576*1024-49)})
    params=decode_json(raw)
    assert len(raw)==576*1024
    assert params['sessionId']==SESSION
    assert input_digest.hex==records.acp_prompt_input_digest(UNIT,params)[7:]


def test_send_maps_original_records_prompt_capacity_refusal_before_native_write():
    port,records,unit,blobs,_=adapter()
    binding=binding_for(port,records,blobs)
    records.reject_prompt_capacity=True
    with pytest.raises(ApplicationError,match='EXECUTION_EVIDENCE_CAPACITY_EXCEEDED'):
        port.send(binding)
    assert len(records.prompt_capacity_calls)==1
    assert unit.calls==[]


def test_capacity_refusal_survives_real_method_resource_guard():
    port, records, unit, _, _ = adapter()
    method_ref = MethodRef('capacity-method', '1', 2, digest(b'method-snapshot'))
    resource_bytes = b'# Exact capacity fixture resource\n'
    exact = ExactMethodResourceRef(method_ref, 'resources/capacity.md',
                                   digest(resource_bytes), 'capacity-resource')
    context = CommandContext(SCOPE, 'fixture-principal',
        ActorRef('fixture-actor', 'human', 'fixture-issuer'), 'capacity-request',
        '2026-10-15T10:00:00.000000Z', 'capacity-trace')

    class MethodGuardFixture:
        @contextmanager
        def guard(self, same_context, same_method_ref):
            assert same_context is context and same_method_ref == method_ref
            yield SimpleNamespace(method_ref=method_ref, resources=(SimpleNamespace(
                resource_id=exact.resource_id, sha256=exact.resource_digest.hex),))

        def read_resource(self, same_context, same_exact_ref):
            assert same_context is context and same_exact_ref == exact
            return resource_bytes

    records.reject_prompt_capacity = True
    with pytest.raises(ApplicationError, match='EXECUTION_EVIDENCE_CAPACITY_EXCEEDED') as caught:
        with guard_method_resources(context, method_ref, (exact,), MethodGuardFixture()):
            port.freeze_input(UNIT, {'prompt': []})
    assert caught.value.code == 'EXECUTION_EVIDENCE_CAPACITY_EXCEEDED'
    assert len(records.prompt_capacity_calls) == 1
    assert unit.calls == []


@pytest.mark.parametrize('wrapper_depth', [1, 2])
def test_send_maps_capacity_refusal_through_original_unit_prompt_cause_chain(wrapper_depth):
    port, records, unit, blobs, _ = adapter()
    binding = binding_for(port, records, blobs)

    def refused_prompt(*args, **kwargs):
        refusal = _AcpEvidenceCapacityRefused()
        error = RuntimeError('original Unit prompt failed')
        error.__cause__ = refusal
        for _ in range(wrapper_depth - 1):
            outer = RuntimeError('Unit prompt wrapper failed')
            outer.__cause__ = error
            error = outer
        raise error

    unit.prompt = refused_prompt
    with pytest.raises(ApplicationError, match='EXECUTION_EVIDENCE_CAPACITY_EXCEEDED') as caught:
        port.send(binding)
    assert caught.value.code == 'EXECUTION_EVIDENCE_CAPACITY_EXCEEDED'
    cause = caught.value.__cause__
    cause_codes = []
    while cause is not None:
        cause_codes.append(getattr(cause, 'code', None))
        cause = cause.__cause__ or cause.__context__
    assert 'ACP_EVIDENCE_CAPACITY_EXCEEDED' in cause_codes
    assert records.prompt_capacity_calls  # Preflight passed; mapping came from prompt's cause chain.
    assert unit.calls == []


def test_send_uses_the_original_unit_instance_lease_and_same_frozen_operation_once():
    port,records,unit,blobs,lease=adapter()
    raw,input_digest=port.freeze_input(UNIT,{'prompt':[]})
    binding=binding_for(port,records,blobs,params=decode_json(raw))
    assert binding.prompt_input_digest==input_digest
    result=port.send(binding)
    assert result=={'nativeReceipt':'fixture-only','state':'completed'}
    assert unit.calls[0][0]==UNIT and unit.calls[0][1] is lease
    assert unit.calls[0][2]==OPERATION and unit.calls[0][4]['sessionId']==SESSION
    with pytest.raises(ApplicationError,match='ORIGINAL_RECORDS_DUPLICATE_OPERATION'):
        port.send(binding)
    assert len(unit.calls)==1


def test_send_reads_canonical_finite_float_params_using_library_profile():
    port,records,unit,blobs,_=adapter()
    binding=binding_for(port,records,blobs,params={'prompt':{'temperature':0.25},'sessionId':SESSION})
    port.send(binding)
    assert unit.calls[0][4]['prompt']['temperature']==0.25


def test_send_refuses_prompt_bytes_that_do_not_match_the_original_records_digest():
    port,records,unit,blobs,_=adapter()
    binding=binding_for(port,records,blobs,params={'prompt':['tampered'],'sessionId':SESSION})
    changed=canonical_bytes({'prompt':['other'],'sessionId':SESSION},profile=LIBRARY_JSON_PROFILE)
    changed_ref=blobs.put_verified(changed,digest(changed),'application/json')
    tampered=replace(binding,prompt_ref=changed_ref)
    with pytest.raises(ApplicationError,match='RECORDED_DISPATCH_INPUT_DIGEST_MISMATCH'):
        port.send(tampered)
    assert unit.calls==[]


def test_send_recomputes_dispatch_binding_digest_before_native_call():
    port,records,unit,blobs,_=adapter()
    binding=binding_for(port,records,blobs)
    object.__setattr__(binding,'execution_operation_ref','forged-operation')
    with pytest.raises(ApplicationError,match='RECORDED_DISPATCH_BINDING_TAMPERED'):
        port.send(binding)
    assert unit.calls==[]


def test_send_and_capture_accept_exact_reviewed_change_v2_binding():
    port, records, unit, blobs, lease = adapter()
    binding = reviewed_change_v2_binding(records, blobs)
    result = port.send(binding)
    assert result == {'nativeReceipt': 'fixture-only', 'state': 'completed'}
    assert len(unit.calls) == 1 and unit.calls[0][1] is lease

    invocation = receipt_for(records, binding, 'completed')
    port.query_factory = lambda same_binding: invocation
    captured = port.capture(binding)
    assert captured.state == 'completed'
    assert records.query_calls[-1][1] == binding.execution_operation_ref


def test_send_rejects_reviewed_change_v2_subject_work_or_digest_tampering_before_write():
    for mutation in ('subject', 'work', 'digest'):
        port, records, unit, blobs, _ = adapter()
        binding = reviewed_change_v2_binding(records, blobs)
        if mutation == 'subject':
            binding.subject['subject_ref']['inputs_digest']['hex'] = 'f' * 64
        elif mutation == 'work':
            binding.work['dispatch_key'] = 'w1:other-work:incremental.prepare-packages:draft'
        else:
            object.__setattr__(binding, 'digest', digest(b'forged-v2-digest'))
        with pytest.raises(ApplicationError, match='RECORDED_DISPATCH_BINDING_TAMPERED'):
            port.send(binding)
        assert unit.calls == []


def test_capture_requires_original_query_authority_and_keeps_unknown_receipt_whole():
    port,records,_,blobs,_=adapter()
    binding=binding_for(port,records,blobs,required_results=('completed',))
    with pytest.raises(ApplicationError,match='EXECUTION_QUERY_AUTHORITY_REQUIRED'):
        port.capture(binding)
    invocation=receipt_for(records,binding,'unknown')
    port.query_factory=lambda same_binding: invocation
    result=port.capture(binding)
    assert result.state=='unknown'
    assert result.operation_ref==OPERATION
    assert result.blob_ref.media_type=='application/json'
    captured=decode_json(blobs.read_verified(result.blob_ref))
    assert captured['state']=='unknown'
    assert records.query_calls==[(UNIT,OPERATION,binding.expected_query_digest,
                                  'sha256:'+binding.prompt_input_digest.hex)]


def test_capture_preserves_complete_receipt_above_default_bound_with_unit_capacity():
    port,records,_,blobs,_=adapter()
    # This case deliberately selects a smaller original-owner cap than the
    # current 8MiB Engineering maximum. Keep proving that capture preserves
    # the complete receipt while honoring that selected Unit capacity.
    records.acp_turn_evidence_max_bytes=2621440
    binding=binding_for(port,records,blobs)
    invocation=large_receipt_for(records,blobs,binding,text_bytes=1080000)
    expected=canonical_bytes(records.receipt,profile=LIBRARY_JSON_PROFILE)
    assert 2*1024*1024 < len(expected) <= records.acp_turn_evidence_max_bytes == 2621440
    port.query_factory=lambda same_binding: invocation
    captured=port.capture(binding)
    assert captured.blob_ref.byte_length==len(expected)
    assert blobs.read_verified(captured.blob_ref)==expected
    assert decode_json(blobs.read_verified(captured.blob_ref))==records.receipt


def test_capture_refuses_receipt_above_unit_capacity_before_blob_write():
    port,records,_,blobs,_=adapter()
    binding=binding_for(port,records,blobs)
    invocation=large_receipt_for(records,blobs,binding,text_bytes=MAX_EXECUTION_RECEIPT_BYTES+1)
    before=set(blobs.values)
    port.query_factory=lambda same_binding: invocation
    with pytest.raises(ApplicationError,match='EXECUTION_RECEIPT_BOUND_EXCEEDED'):
        port.capture(binding)
    assert set(blobs.values)==before


def test_capture_preserves_reserved_failed_and_completed_without_relabeling():
    for state in ('reserved','possibly-written','failed','completed'):
        port,records,_,blobs,_=adapter()
        binding=binding_for(port,records,blobs)
        port.query_factory=lambda same_binding, current=state: receipt_for(records,same_binding,current)
        result=port.capture(binding)
        assert result.state==state


def test_cold_capture_needs_no_live_unit_and_cannot_send():
    port,records,_,blobs,_=adapter()
    binding=binding_for(port,records,blobs)
    invocation=receipt_for(records,binding,'completed')
    cold=RecordedDispatchExecution(records,None,None,blobs,query_factory=lambda _: invocation)
    result=cold.capture(binding)
    assert result.state=='completed'
    with pytest.raises(ApplicationError):
        cold.send(binding)


def test_dispatch_codec_requires_closed_identity_and_digest():
    from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch,decode_dispatch
    from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
    port,records,_,blobs,_=adapter()
    binding=binding_for(port,records,blobs)
    assert decode_dispatch(encode_dispatch(binding))==binding
    value=decode_json(encode_dispatch(binding));value['execution_operation_ref']='changed'
    with pytest.raises(ReferenceError):
        decode_dispatch(canonical_bytes(value))
    value=decode_json(encode_dispatch(binding));value['extra']='unbound'
    with pytest.raises(ReferenceError):
        decode_dispatch(canonical_bytes(value))


def test_submission_requires_the_exact_original_dispatch_receipt(monkeypatch):
    from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch,resolve_dispatch_submission_binding
    from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
    port,records,_,blobs,_=adapter();binding=binding_for(port,records,blobs)
    observation=blobs.put_verified(b'observation',digest(b'observation'),'application/json')
    execution=SimpleNamespace(operation_ref=OPERATION,environment_namespace=UNIT['environmentNamespace'],
        unit_id=UNIT['unitId'],owner_provider_ref_bytes=canonical_bytes(UNIT['ownerProviderRef']),
        source_revision=UNIT['sourceRevision'],prompt_input_digest=binding.prompt_input_digest,
        captured_observation_ref=observation)
    # Normal dispatch-bound Submission (schema13): the product reads
    # schema_version to route; 2 is the separate schema12 declared-report
    # variant (implementation_dispatch.py:378). Submission defaults to 1
    # (domain/changes/submission.py:196).
    submission=SimpleNamespace(schema_version=1,scope=SCOPE,package_ref=binding.package_ref,authorization_refs=(binding.approval_ref,),execution_ref=execution)
    from dataclasses import asdict
    row={'binding_bytes':encode_dispatch(binding),'dispatch_fence':1,'dispatch_phase':'completed',
        'result_blob_json':canonical_bytes(asdict(observation)).decode()}
    uow=SimpleNamespace(scope=SCOPE,dispatch=SimpleNamespace(by_operation=lambda op,scope: row))
    monkeypatch.setattr('ordessa_engineering.application.orchestration.dispatch_method_run.resolve_historical_method_run_package',lambda uow,run,**kwargs:SimpleNamespace(ref=binding.package_ref))
    assert resolve_dispatch_submission_binding(uow,submission)==binding
    row['dispatch_phase']='reserved'
    with pytest.raises(ApplicationError,match='SUBMISSION_DISPATCH_BINDING_MISMATCH'):
        resolve_dispatch_submission_binding(uow,submission)
    row['dispatch_phase']='completed';execution.source_revision='other-source'
    with pytest.raises(ApplicationError,match='SUBMISSION_DISPATCH_BINDING_MISMATCH'):
        resolve_dispatch_submission_binding(uow,submission)


def test_missing_or_changed_effect_owner_configuration_refuses_before_native_call():
    port,records,unit,blobs,_=adapter()
    binding=binding_for(port,records,blobs)
    port.effect_write_guard_factory=None
    with pytest.raises(ApplicationError,match='RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED'):
        port.send(binding)
    port.effect_write_guard_factory=lambda *_:None
    with pytest.raises(ApplicationError,match='RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED'):
        port.send(binding)
    assert unit.calls==[] and unit.seen_operations==set()
