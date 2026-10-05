"""C-only scripted owner ports; original journal integration is tested separately.

No Codex binary/model/user configuration is used by this test module.
"""
from types import SimpleNamespace
import json
import pytest
from test_provider import fixture, UNIT, Projection, Records, Verifier, DEFINITION, DIGEST
from ordessa_harness_codex import CodexRuntimeProvider, CodexProviderRefused, CodexCapabilityUnsupported
from pacthold.agents.public import (
    ConfigurationChangeRequest, ConfigurationChangeResult, ConfigurationItemResult,
    ConfigurationSnapshot, ConfigurationRevisionConflict,
)

class Evidence:
    def __init__(self): self.captured={}; self.next=0
    def verify_configuration(self,*args): raise AssertionError("controlled journal verifies independently")
    def capture_configuration(self, unit, facts, request, receipt, before, after, summary):
        assert request["method"] == "config/batchWrite"
        assert request["params"]["expectedVersion"] == before["nativeUserVersion"]
        assert receipt["version"] == after["nativeUserVersion"]
        assert all(edit["keyPath"] in {"model","model_reasoning_effort"} for edit in request["params"]["edits"])
        assert "secret-token" not in json.dumps([request,receipt,before,after,summary])
        self.next += 1
        ref="config-proof-"+str(self.next)
        self.captured[ref]=summary
        return ref
    def read_configuration_result(self,unit,attempt):
        summary=self.captured[attempt.evidence]
        env=summary["unitRef"]["environmentNamespace"]
        proof={"operationRef":summary["operationRef"],"unitRef":summary["unitRef"],"scopeRef":summary["scopeRef"],
              "requestDigest":summary["requestDigest"],"evidenceRef":{"environmentNamespace":env,"evidenceRef":attempt.evidence}}
        snapshot=summary["confirmedSnapshot"]
        snapshot=ConfigurationSnapshot(snapshot["unitRef"],snapshot["scopeRef"],snapshot["sourceRevision"],snapshot["observedAt"],
                      snapshot["configuration"],tuple(snapshot["unknownItems"]),proof["evidenceRef"],snapshot["comparisonGuarantee"])
        return ConfigurationChangeResult(summary["operationRef"],tuple(ConfigurationItemResult(item["declarationId"],item["outcome"],
                        proof if item["outcome"] == "applied" else None) for item in summary["itemOutcomes"]),snapshot)

class ConfigurationRecords(Records):
    def __init__(self,projection,verifier,evidence):
        super().__init__(projection,verifier);self.configuration_evidence=evidence; self.attempt=None;self.claims=0; self.contexts=[]
    def begin_configuration_change(self,unit_id,context,**params):
        if self.attempt is not None: raise RuntimeError("original attempt retains identity")
        self.claims+=1; self.contexts.append(context)
        self.attempt=SimpleNamespace(state="opening",source_revision=1,native_request_id=None,evidence=None)
        return object()
    def bind_configuration_dispatch(self,ticket,*,native_request_id,native_request_digest):
        assert self.attempt.native_request_id is None
        self.attempt.native_request_id=native_request_id; self.attempt.source_revision=2
        return self.attempt
    def record_configuration_change(self,ticket,*,expected_source_revision,state,evidence=None):
        assert self.attempt.source_revision == expected_source_revision
        self.attempt.state=state;self.attempt.evidence=evidence;self.attempt.source_revision+=1
        return self.attempt
    def query_configuration_change(self,unit_id,operation_ref,context,*,input_digest):
        assert operation_ref == context.facts["operationRef"]
        self.contexts.append(context)
        return self.attempt

class ConfigurationClient:
    def __init__(self):
        self.calls=[];self.defaults={"model":"default-a","model_reasoning_effort":"low"};self.version="native-v1"
        self.thread_model="thread-a";self.seq=0;self.timeout=False;self.pending={};self.receipt_status="ok";self.malformed=False
    def initialize(self): pass
    def create_thread(self,**kwargs): return {"thread":{"id":"thread-1"}}
    def command(self,method,**kwargs):
        self.calls.append(method)
        if method == "thread/read": return {"thread":{"id":"thread-1","model":self.thread_model,"reasoningEffort":"low"}}
        if method == "config/read":
            return {"config":{**self.defaults,"api_key":"secret-token"},"layers":[{"name":{"type":"user","file":"/isolated/codex/config.toml"},
                     "version":self.version,"disabledReason":None,"config":{**self.defaults,"api_key":"secret-token"}}]}
        raise AssertionError(method)
    def command_once(self,method,params,*,before_send):
        self.seq+=1
        request={"id":"actual-"+str(self.seq),"method":method,"params":params}
        before_send(request)
        self.calls.append(method)
        assert params["expectedVersion"] == self.version
        for edit in params["edits"]:
            if edit["value"] is None: self.defaults.pop(edit["keyPath"],None)
            else: self.defaults[edit["keyPath"]]=edit["value"]
        self.version="native-v2"
        receipt={"status":self.receipt_status,"version":self.version,"filePath":params["filePath"],"overriddenMetadata":None}
        if self.malformed: receipt={"ack":True}
        if self.timeout:
            self.pending[request["id"]]=receipt
            raise TimeoutError()
        return receipt
    def recover_request(self,request_id,*,timeout): return self.pending.pop(request_id)

def setup():
    projection=Projection();projection.unit.facts["privateRootFacts"]["codexHome"]="/isolated/codex"
    projection.revalidate_configuration=lambda unit,context:context.facts
    evidence=Evidence();verifier=Verifier();records=ConfigurationRecords(projection,verifier,evidence);client=ConfigurationClient()
    provider=CodexRuntimeProvider(definition_ref=DEFINITION,implementation_digest=DIGEST,unit_records=records,
                    projection=projection,verifier=verifier,channel_factory=SimpleNamespace(open=lambda *args:client),configuration_evidence=evidence)
    from test_provider import PROVIDER,NODE
    start=SimpleNamespace(facts={"providerRef":PROVIDER,"targetRef":NODE,"inputDigest":"start-digest","action":"start","query":False,"managementEpoch":1})
    provider.start({"unitRef":UNIT},start)
    return provider,projection,records,client,evidence

def change(provider,*,action="value",payload=None,extra=()):
    declaration={"declarationId":"defaults","configurationKind":"codex.defaults","schemaVersion":"0.157.1","action":action,"requirement":"required"}
    if action == "value": declaration["payload"]={"model":"default-b"} if payload is None else payload
    request=ConfigurationChangeRequest("request-1",provider.inspect_configuration(UNIT).source_revision,(declaration,)+extra)
    unit=provider._unit(UNIT)
    context=SimpleNamespace(facts={"providerRef":unit.facts["providerRef"],"targetRef":unit.configuration_target_ref,"inputDigest":"fixed-digest",
                "action":"applyConfiguration","query":False,"managementEpoch":1,"operationRef":"operation-1", "contextRef":{"effectiveDeclarations":request.declarations}})
    return request,context

def test_defaults_write_is_confirmed_but_thread_model_remains_native_actual():
    provider,projection,records,client,evidence=setup();request,context=change(provider)
    result=provider.apply_configuration(UNIT,request,context)
    assert result.overall_outcome == "applied"
    assert result.confirmed_snapshot.configuration["defaults"]["model"] == "default-b"
    assert result.confirmed_snapshot.configuration["thread"]["model"] == "thread-a"
    assert result.confirmed_snapshot.comparison_guarantee == "ownerSerialized"
    assert records.attempt.native_request_id == "actual-1"
    assert records.claims == 1 and client.calls.count("config/batchWrite") == 1
    assert records.contexts == [context]

def test_missing_same_evidence_owner_does_not_advertise_writes():
    provider,projection,records,client,evidence=setup()
    other=CodexRuntimeProvider(definition_ref=DEFINITION,implementation_digest=DIGEST,unit_records=records,
            projection=projection,verifier=records.verifier,channel_factory=SimpleNamespace(open=lambda *args:client),configuration_evidence=Evidence())
    assert "apply_configuration" not in other.descriptor.supported_methods

def test_stale_native_version_refused_before_journal_claim_and_write():
    provider,projection,records,client,evidence=setup();request,context=change(provider);client.version="external-v2"
    with pytest.raises(ConfigurationRevisionConflict): provider.apply_configuration(UNIT,request,context)
    assert records.claims == 0 and "config/batchWrite" not in client.calls

def test_unknown_required_or_payload_keys_refused_before_claim():
    provider,projection,records,client,evidence=setup();request,context=change(provider,payload={"unexpected":"unused"})
    with pytest.raises(CodexCapabilityUnsupported): provider.apply_configuration(UNIT,request,context)
    assert records.claims == 0 and "config/batchWrite" not in client.calls

def test_reset_uses_native_null_and_does_not_reset_thread():
    provider,projection,records,client,evidence=setup();request,context=change(provider,action="reset")
    result=provider.apply_configuration(UNIT,request,context)
    assert result.overall_outcome == "applied"
    assert dict(result.confirmed_snapshot.configuration["defaults"]) == {}
    assert result.confirmed_snapshot.configuration["thread"]["model"] == "thread-a"

def test_unknown_optional_explicitly_partial_and_not_dispatched():
    provider,projection,records,client,evidence=setup()
    extra=({"declarationId":"optional","configurationKind":"foreign","schemaVersion":"1","action":"value","requirement":"optional","payload":{}},)
    request,context=change(provider,extra=extra)
    result=provider.apply_configuration(UNIT,request,context)
    assert [(item.declaration_id,item.outcome) for item in result.item_results] == [("defaults","applied"),("optional","rejected")]
    assert result.overall_outcome == "partial"

def test_receipt_timeout_unknown_then_query_recovers_original_id_without_write():
    provider,projection,records,client,evidence=setup();request,context=change(provider);client.timeout=True
    result=provider.apply_configuration(UNIT,request,context)
    assert result.overall_outcome == "unknown" and records.attempt.source_revision == 3
    query=SimpleNamespace(facts={**context.facts,"action":"query","query":True})
    result=provider.query_change(UNIT,"operation-1",query)
    assert result.overall_outcome == "applied" and records.attempt.state == "confirmed"
    assert records.attempt.source_revision == 4
    assert client.calls.count("config/batchWrite") == 1

def test_matching_values_without_original_receipt_remain_unknown_after_restart():
    provider,projection,records,client,evidence=setup();request,context=change(provider);client.timeout=True
    provider.apply_configuration(UNIT,request,context); provider._configuration_waiters.clear()
    query=SimpleNamespace(facts={**context.facts,"action":"query","query":True})
    result=provider.query_change(UNIT,"operation-1",query)
    assert result.overall_outcome == "unknown" and records.attempt.state == "unknown"
    assert client.calls.count("config/batchWrite") == 1

def test_ack_without_version_readback_never_applied():
    provider,projection,records,client,evidence=setup();request,context=change(provider);client.malformed=True
    result=provider.apply_configuration(UNIT,request,context)
    assert result.overall_outcome == "unknown" and records.attempt.state == "unknown" and evidence.captured == {}

def test_overridden_receipt_does_not_claim_applied():
    provider,projection,records,client,evidence=setup();request,context=change(provider);client.receipt_status="okOverridden"
    result=provider.apply_configuration(UNIT,request,context)
    assert result.overall_outcome == "unknown"
    assert records.attempt.state == 'unknown'
    assert 'operation-1' in provider._configuration_waiters
    query = SimpleNamespace(facts={**context.facts, 'action':'query', 'query':True})
    assert provider.query_change(UNIT, 'operation-1', query).overall_outcome == 'unknown'
    assert records.attempt.state == 'unknown'
    assert client.calls.count('config/batchWrite') == 1

def test_revoke_in_presend_hook_binds_nothing_and_never_writes():
    provider,projection,records,client,evidence=setup();request,context=change(provider)
    count=0
    def revalidate(unit,ctx):
        nonlocal count
        count+=1
        if count == 3: raise RuntimeError("revoked")
        return ctx.facts
    projection.revalidate_configuration=revalidate
    result=provider.apply_configuration(UNIT,request,context)
    assert result.overall_outcome == "unknown"
    assert records.attempt.native_request_id is None and "config/batchWrite" not in client.calls

def test_external_change_after_original_receipt_keeps_unknown_not_latest_receipt():
    provider,projection,records,client,evidence=setup();request,context=change(provider);client.timeout=True
    provider.apply_configuration(UNIT,request,context);client.version="external-later"
    query=SimpleNamespace(facts={**context.facts,"action":"query","query":True})
    result=provider.query_change(UNIT,"operation-1",query)
    assert result.overall_outcome == "unknown" and evidence.captured == {}


@pytest.mark.parametrize("reference",__import__("test_provider").forged_unit_references())
def test_forged_full_unit_reference_cannot_read_write_or_query_configuration(reference):
    provider,projection,records,client,evidence=setup();request,context=change(provider)
    calls=list(client.calls)
    with pytest.raises(CodexProviderRefused): provider.apply_configuration(reference,request,context)
    query=SimpleNamespace(facts={**context.facts,"action":"query","query":True})
    with pytest.raises(CodexProviderRefused): provider.query_change(reference,"operation-1",query)
    assert client.calls == calls and records.claims == 0 and records.contexts == [] and evidence.captured == {}


def test_configuration_receipt_snapshot_and_context_use_original_complete_target():
    provider,projection,records,client,evidence=setup();request,context=change(provider)
    result=provider.apply_configuration(UNIT,request,context)
    target=projection.unit.configuration_target_ref
    assert provider.describe_configuration(UNIT)[0].scope == "instance"
    assert context.facts["targetRef"] == target
    assert result.confirmed_snapshot.scope_ref == target
    assert result.item_results[0].confirmation["scopeRef"] == target
    assert set(target) == {"environmentNamespace","scopeId","revision","ownerProviderRef","sourceRevision"}
    assert target["ownerProviderRef"] == projection.unit.public_ref["ownerProviderRef"]
    assert result.confirmed_snapshot.source_revision != target["sourceRevision"]
    query=SimpleNamespace(facts={**context.facts,"action":"query","query":True})
    queried=provider.query_change(UNIT,"operation-1",query)
    assert queried.confirmed_snapshot.scope_ref == target
    assert client.calls.count("config/batchWrite") == 1
