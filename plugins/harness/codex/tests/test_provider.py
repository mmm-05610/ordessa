"""C: controlled owner-port tests, never an actual Codex process/task claim."""
from types import SimpleNamespace
import pytest
from ordessa_harness_codex import CodexRuntimeProvider, CodexProviderRefused, CodexCapabilityUnsupported
from pacthold.agents.public import RuntimeProvider

DIGEST = "sha256:" + "a" * 64
DEFINITION = {"environmentNamespace": "test", "definitionId": "codex", "revision": "1"}
PROVIDER = {"environmentNamespace": "test", "providerId": "codex", "implementationDigest": DIGEST,
            "contractVersion": "agent-runtime/2"}
NODE = {"environmentNamespace": "test", "instanceId": "node", "generation": 1}
UNIT = {"environmentNamespace": "test", "unitId": "unit-1"}

class Projection:
    def __init__(self):
        self.unit = SimpleNamespace(unit_ref="unit-1", facts={"providerRef": PROVIDER, "nodeRef": NODE,
                  "privateRootFacts": {"cwd": "/isolated"}, "managementEpoch": 1},
                  scope_ref=SimpleNamespace(to_dict=lambda: {"environmentNamespace": "test", "scopeId": "scope", "revision": "1"}))
        self.binding = SimpleNamespace(state="notCreated", native_facts=None, source_revision=1)
    def verify_preparation(self, plan, facts):
        assert plan["context"]["nodeRef"] == facts["targetRef"]
        return self.unit.facts["privateRootFacts"]
    def revalidate_start(self, unit, context): return context.facts
    def read_unit(self, ref): return self.unit
    def read_session(self, ref): return self.binding
    def publication_facts(self, ref): raise RuntimeError("missing proof")
    def publish_channel(self, unit, client, evidence):
        if evidence.get("thread", {}).get("id") != "thread-1": raise RuntimeError("bad thread")
        return "native-proof"
    def query_creation(self, correlation, facts):
        return {"correlation": correlation, "state": self.binding.state}

class Records:
    def __init__(self, projection, verifier): self.projection=projection; self.verifier=verifier; self.begins=0; self.reserves=0
    def read_unit(self, *args, **kwargs): return self.projection.unit
    def read_session(self, *args, **kwargs): return self.projection.binding
    def reserve_unit(self, context, **kwargs):
        self.reserves += 1
        assert kwargs["private_root_facts"] == {"cwd": "/isolated"}
        return self.projection.unit, True
    def begin_session(self, unit_id, context, *, input_digest):
        if self.projection.binding.state != "notCreated": raise RuntimeError("existing start")
        self.begins += 1
        self.projection.binding.state = "opening"
        return object()
    def record_session(self, ticket, *, expected_source_revision, state, evidence=None):
        assert expected_source_revision == 2
        self.projection.binding.state=state
        if state == "confirmed":
            assert evidence == "native-proof"
            self.projection.binding.native_facts = {"nativeRealm": "codex", "sessionId": "thread-1", "evidenceRef": evidence}
            self.projection.binding.source_revision=3
        return self.projection.binding

class Client:
    def __init__(self): self.calls=[]; self.fail=False
    def initialize(self): self.calls.append("initialize")
    def create_thread(self, **params):
        self.calls.append("thread/start")
        if self.fail: raise TimeoutError()
        return {"thread": {"id": "thread-1"}}
    def command(self, method, **params):
        self.calls.append(method)
        if method == "thread/read": return {"thread": {"id": "thread-1"}}
        if method == "config/read": return {"config": {"model": "model-a", "secret": "secret-value", "model_providers": {"token":"private"}}}
        raise AssertionError(method)

class Verifier:
    def verify_and_consume(self, context, *args): return context.facts

def fixture(*, lease_port=None):
    projection=Projection(); verifier=Verifier(); records=Records(projection, verifier); client=Client()
    provider=CodexRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
        unit_records=records, projection=projection, verifier=verifier,
        channel_factory=SimpleNamespace(open=lambda roots,facts: client), lease_port=lease_port)
    context=SimpleNamespace(facts={"providerRef": PROVIDER, "targetRef": NODE, "inputDigest": "digest", "action": "start", "query": False, "managementEpoch": 1})
    return provider,projection,records,client,context

def test_missing_ports_do_not_advertise_lifecycle():
    provider=CodexRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST)
    assert isinstance(provider, RuntimeProvider)
    assert "start" not in provider.descriptor.supported_methods
    assert "apply_configuration" not in provider.descriptor.supported_methods
    with pytest.raises(CodexCapabilityUnsupported): provider.start({}, None)

def test_missing_projection_preparation_fence_is_unavailable():
    provider=CodexRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
       unit_records=object(), projection=object(), verifier=object())
    assert "prepare" not in provider.descriptor.supported_methods

def test_prepare_uses_verified_original_plan_roots():
    provider,projection,records,client,context=fixture()
    plan={"context": {"nodeRef": NODE, "privateRootFacts": {"cwd": "/attacker"}}}
    result=provider.prepare(plan,context)
    assert result["unitRef"] == UNIT
    assert records.reserves == 1 and client.calls == []

def test_wrong_node_plan_refused_without_reservation():
    provider,projection,records,client,context=fixture()
    with pytest.raises(CodexProviderRefused): provider.prepare({"context": {"nodeRef": {}}},context)
    assert records.reserves == 0

def test_start_fixes_binding_before_real_calls_and_confirms_readback():
    provider,projection,records,client,context=fixture()
    result=provider.start({"unitRef": UNIT}, context)
    assert records.begins == 1
    assert client.calls == ["initialize", "thread/start", "thread/read"]
    assert result["nativeBinding"]["sessionId"] == "thread-1"
    assert "turn/start" not in client.calls

def test_receipt_loss_retains_unknown_and_new_start_never_dispatches():
    provider,projection,records,client,context=fixture(); client.fail=True
    with pytest.raises(CodexProviderRefused,match="unknown"): provider.start({"unitRef": UNIT},context)
    assert projection.binding.state == "unknown"
    with pytest.raises(RuntimeError,match="existing start"): provider.start({"unitRef": UNIT},context)
    assert client.calls.count("thread/start") == 1

def test_config_inspection_is_fresh_secret_free_and_not_native_cas():
    provider,projection,records,client,context=fixture(); provider.start({"unitRef": UNIT},context)
    snapshot=provider.inspect_configuration(UNIT)
    assert dict(snapshot.configuration) == {"model": "model-a"}
    assert snapshot.comparison_guarantee == "unavailable"
    assert "private" not in str(snapshot.to_dict())
    assert "providerCredentials" in snapshot.unknown_items
    provider.inspect_configuration(UNIT)
    assert client.calls.count("config/read") == 2

def test_unknown_native_binding_does_not_grant_access():
    provider,projection,records,client,context=fixture()
    with pytest.raises(CodexProviderRefused): provider.describe_access(UNIT)

def test_missing_lease_cannot_expose_raw_client():
    provider,projection,records,client,context=fixture(); provider.start({"unitRef": UNIT},context)
    with pytest.raises(CodexCapabilityUnsupported): provider.connect(UNIT,{"authorized":True})

def test_wrong_unit_environment_and_owner_refused():
    provider,projection,records,client,context=fixture()
    with pytest.raises(CodexProviderRefused): provider.describe_access({**UNIT,"environmentNamespace":"foreign"})

def test_mutation_stop_release_recovery_are_explicitly_unsupported():
    provider,projection,records,client,context=fixture()
    for name,args in [("apply_configuration",(UNIT,None,context)),("query_change",(UNIT,{},context)),
                      ("stop",(UNIT,context)),("release",(UNIT,context)),("recover",({},context))]:
        assert name not in provider.descriptor.supported_methods
        with pytest.raises(CodexCapabilityUnsupported): getattr(provider,name)(*args)
    assert client.calls == []

def test_revoke_after_open_fences_initialize_and_keeps_unknown():
    provider,projection,records,client,context=fixture()
    count=0
    def current(unit, ctx):
        nonlocal count
        count += 1
        if count == 2: raise RuntimeError("revoked")
        return ctx.facts
    projection.revalidate_start=current
    with pytest.raises(CodexProviderRefused,match="unknown"): provider.start({"unitRef": UNIT},context)
    assert projection.binding.state == "unknown"
    assert client.calls == []

def test_epoch_change_before_thread_start_fences_native_creation():
    provider,projection,records,client,context=fixture()
    count=0
    def current(unit, ctx):
        nonlocal count
        count += 1
        if count == 3: return {**ctx.facts,"managementEpoch":2}
        return ctx.facts
    projection.revalidate_start=current
    with pytest.raises(CodexProviderRefused,match="unknown"): provider.start({"unitRef": UNIT},context)
    assert client.calls == ["initialize"]
    assert projection.binding.state == "unknown"

def test_thread_ack_without_matching_readback_is_not_confirmed():
    provider,projection,records,client,context=fixture()
    client.command=lambda *args,**kwargs: {"thread":{"id":"different"}}
    with pytest.raises(CodexProviderRefused,match="unknown"): provider.start({"unitRef": UNIT},context)
    assert projection.binding.state == "unknown" and projection.binding.native_facts is None

def test_query_observes_only_original_binding_without_start():
    provider,projection,records,client,context=fixture()
    context.facts={**context.facts,"action":"query","query":True}
    result=provider.query_step({"operationRef":"original"},context)
    assert result["state"] == "notCreated"
    assert records.begins == 0 and client.calls == []

def test_query_effect_context_rejected():
    provider,projection,records,client,context=fixture()
    with pytest.raises(CodexProviderRefused): provider.query_step({},context)
    assert client.calls == []

def test_foreign_verifier_omits_unit_lifecycle():
    projection=Projection(); records=Records(projection,Verifier())
    provider=CodexRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
             unit_records=records,projection=projection,verifier=Verifier())
    assert "prepare" not in provider.descriptor.supported_methods

def test_config_unknown_structure_never_returns_profile_desired():
    provider,projection,records,client,context=fixture(); provider.start({"unitRef":UNIT},context)
    client.command=lambda *args,**kwargs: {"ack":True}
    with pytest.raises(CodexProviderRefused): provider.inspect_configuration(UNIT)
