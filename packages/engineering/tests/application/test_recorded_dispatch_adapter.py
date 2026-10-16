"""Synthetic public-port fixtures; these do not qualify an original SDK owner."""
import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.canonical_json import LIBRARY_JSON_PROFILE
from ordessa_engineering.adapters.native_records.recorded_dispatch import RecordedDispatchExecution
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef


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

    def prompt_recorded(self, unit_ref, lease, *, operation_ref, timeout=60, **params):
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


def receipt_for(records, binding, state='unknown'):
    prompt_digest='sha256:'+binding.prompt_input_digest.hex
    query_digest=records.acp_turn_query_digest(UNIT,binding.execution_operation_ref,prompt_digest)
    records.receipt={'contractVersion':'unit-acp-turn/1','unitRef':dict(UNIT),
        'operationRef':binding.execution_operation_ref,'inputDigest':prompt_digest,'state':state,
        'revision':2,'events':[],'eventsDigest':'fixture-events-digest','request':None,
        'response':None,'responseDigest':'fixture-response-digest','summary':None}
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
        port.freeze_input(UNIT,{'prompt':'x'*262144})


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
    submission=SimpleNamespace(scope=SCOPE,package_ref=binding.package_ref,authorization_refs=(binding.approval_ref,),execution_ref=execution)
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
