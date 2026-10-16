"""C: controlled owner-port tests, never an actual dsh process/task claim."""
from types import SimpleNamespace
import pytest
from ordessa_harness_dsh import (DshRuntimeProvider, DshProviderRefused,
                                 DshCapabilityUnsupported, PROTOCOL)
from ordessa_units.public import RuntimeProvider

# Test fixture digest only — NOT a real implementation digest. Production
# digests are injected by the deployment fingerprint gate (freeze §3).
DIGEST = "sha256:" + "a" * 64
DEFINITION = {"environmentNamespace": "test", "definitionId": "dsh", "revision": "1"}
PROVIDER = {"environmentNamespace": "test", "providerId": "dsh", "implementationDigest": DIGEST,
            "contractVersion": "agent-runtime/2", "generation": 1,
            "ownerActivationRef": {"environmentNamespace": "test", "pluginId": "dsh-plugin", "generation": 1}}
NODE = {"environmentNamespace": "test", "instanceId": "node", "generation": 1}
# Explicit C fixture source reference, not production journal/native proof.
UNIT = {"environmentNamespace": "test", "unitId": "unit-1", "ownerProviderRef": PROVIDER, "sourceRevision": "sha256:" + "c" * 64}

# Explicit controlled owner projection, not a copied production hash algorithm.
CONFIGURATION_TARGET = {"environmentNamespace":"test", "scopeId":"scope", "revision":"1",
                        "ownerProviderRef":PROVIDER, "sourceRevision":"sha256:"+"b"*64}

CONFIGURATION_METHODS = ("describe_configuration", "inspect_configuration",
                         "apply_configuration", "query_change")
CONFIGURATION_CALLS = (("describe_configuration", ({},)),
                       ("inspect_configuration", ({},)),
                       ("apply_configuration", ({}, None, None)),
                       ("query_change", ({}, {}, None)))


class Projection:
    def __init__(self):
        self.unit = SimpleNamespace(unit_ref="unit-1", public_ref=UNIT, configuration_target_ref=CONFIGURATION_TARGET, facts={"providerRef": PROVIDER, "nodeRef": NODE,
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
        if evidence.get("sessionId") != "ses-1": raise RuntimeError("bad session")
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
            self.projection.binding.native_facts = {"nativeRealm": PROTOCOL, "sessionId": "ses-1", "evidenceRef": evidence}
            self.projection.binding.source_revision=3
        return self.projection.binding

class Client:
    """The dsh ACP start sequence only: initialize + session/new; no generic RPC."""
    def __init__(self): self.calls=[]; self.fail=False
    def initialize(self):
        self.calls.append("initialize")
        return {"protocolVersion": 1, "agentCapabilities": {"loadSession": False},
                "agentInfo": {"name": "dsh-fake", "version": "0.1.5-rc.1-fake"}}
    def new_session(self, **params):
        self.calls.append("session/new")
        if self.fail: raise TimeoutError()
        return {"sessionId": "ses-1", "configOptions": []}
    def command(self, method, **params):
        raise AssertionError("dsh provider issues no generic RPC on this path: " + method)

class Verifier:
    def verify_and_consume(self, context, *args): return context.facts

def fixture(*, lease_port=None):
    projection=Projection(); verifier=Verifier(); records=Records(projection, verifier); client=Client()
    provider=DshRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
        unit_records=records, projection=projection, verifier=verifier,
        channel_factory=SimpleNamespace(open=lambda roots,facts: client), lease_port=lease_port)
    context=SimpleNamespace(facts={"providerRef": PROVIDER, "targetRef": NODE, "inputDigest": "digest", "action": "start", "query": False, "managementEpoch": 1})
    return provider,projection,records,client,context

def test_descriptor_digest_is_required_with_no_default():
    with pytest.raises(TypeError):
        DshRuntimeProvider(definition_ref=DEFINITION)  # digest omitted entirely
    with pytest.raises(DshProviderRefused):
        DshRuntimeProvider(definition_ref=DEFINITION, implementation_digest="")
    with pytest.raises(DshProviderRefused):
        DshRuntimeProvider(definition_ref=DEFINITION, implementation_digest=None)

def test_missing_ports_do_not_advertise_lifecycle():
    provider=DshRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST)
    assert isinstance(provider, RuntimeProvider)
    assert "start" not in provider.descriptor.supported_methods
    for name,args in CONFIGURATION_CALLS:
        assert name not in provider.descriptor.supported_methods
        with pytest.raises(DshCapabilityUnsupported): getattr(provider,name)(*args)

def test_configuration_family_is_always_absent_even_with_full_wiring():
    provider,projection,records,client,context=fixture()
    methods = provider.descriptor.supported_methods
    for name,args in CONFIGURATION_CALLS:
        assert name not in methods
        with pytest.raises(DshCapabilityUnsupported, match="dsh capability unavailable"):
            getattr(provider,name)(*args)
    assert provider.describe_definition(DEFINITION)["recovery"] == "unsupported"

def test_missing_projection_preparation_fence_is_unavailable():
    provider=DshRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
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
    with pytest.raises(DshProviderRefused): provider.prepare({"context": {"nodeRef": {}}},context)
    assert records.reserves == 0

def test_start_fixes_binding_before_real_calls_and_confirms_session_receipt():
    provider,projection,records,client,context=fixture()
    result=provider.start({"unitRef": UNIT}, context)
    assert records.begins == 1
    assert client.calls == ["initialize", "session/new"]
    assert result["nativeBinding"]["sessionId"] == "ses-1"
    assert result["nativeBinding"]["nativeRealm"] == PROTOCOL
    assert "session/prompt" not in client.calls  # zero model, zero prompt

def test_receipt_loss_retains_unknown_and_new_start_never_dispatches():
    provider,projection,records,client,context=fixture(); client.fail=True
    with pytest.raises(DshProviderRefused,match="unknown"): provider.start({"unitRef": UNIT},context)
    assert projection.binding.state == "unknown"
    with pytest.raises(RuntimeError,match="existing start"): provider.start({"unitRef": UNIT},context)
    assert client.calls.count("session/new") == 1

def test_unknown_native_binding_does_not_grant_access():
    provider,projection,records,client,context=fixture()
    with pytest.raises(DshProviderRefused): provider.describe_access(UNIT)

def test_missing_lease_cannot_expose_raw_client():
    provider,projection,records,client,context=fixture(); provider.start({"unitRef": UNIT},context)
    with pytest.raises(DshCapabilityUnsupported): provider.connect(UNIT,{"authorized":True})

def test_wrong_unit_environment_and_owner_refused():
    provider,projection,records,client,context=fixture()
    with pytest.raises(DshProviderRefused): provider.describe_access({**UNIT,"environmentNamespace":"foreign"})

def test_mutation_configuration_stop_release_recovery_are_explicitly_unsupported():
    provider,projection,records,client,context=fixture()
    for name,args in [("apply_configuration",(UNIT,None,context)),("query_change",(UNIT,{},context)),
                      ("describe_configuration",(UNIT,)),("inspect_configuration",(UNIT,)),
                      ("stop",(UNIT,context)),("release",(UNIT,context)),("recover",({},context))]:
        assert name not in provider.descriptor.supported_methods
        with pytest.raises(DshCapabilityUnsupported): getattr(provider,name)(*args)
    assert client.calls == []

def test_recover_names_the_bridge_continuation_contract():
    provider,projection,records,client,context=fixture()
    with pytest.raises(DshCapabilityUnsupported) as error:
        provider.recover({}, context)
    assert "agent-box.dsh-continuation@1" in str(error.value)
    assert "session/load" in str(error.value)

def test_revoke_after_open_fences_initialize_and_keeps_unknown():
    provider,projection,records,client,context=fixture()
    count=0
    def current(unit, ctx):
        nonlocal count
        count += 1
        if count == 2: raise RuntimeError("revoked")
        return ctx.facts
    projection.revalidate_start=current
    with pytest.raises(DshProviderRefused,match="unknown"): provider.start({"unitRef": UNIT},context)
    assert projection.binding.state == "unknown"
    assert client.calls == []

def test_epoch_change_before_session_new_fences_native_creation():
    provider,projection,records,client,context=fixture()
    count=0
    def current(unit, ctx):
        nonlocal count
        count += 1
        if count == 3: return {**ctx.facts,"managementEpoch":2}
        return ctx.facts
    projection.revalidate_start=current
    with pytest.raises(DshProviderRefused,match="unknown"): provider.start({"unitRef": UNIT},context)
    assert client.calls == ["initialize"]
    assert projection.binding.state == "unknown"

def test_session_receipt_without_identity_is_not_confirmed():
    provider,projection,records,client,context=fixture()
    client.new_session=lambda **params: {"configOptions": []}  # no sessionId
    with pytest.raises(DshProviderRefused,match="unknown"): provider.start({"unitRef": UNIT},context)
    assert projection.binding.state == "unknown" and projection.binding.native_facts is None

def test_initialize_without_capabilities_is_not_confirmed():
    provider,projection,records,client,context=fixture()
    def bad_initialize():
        client.calls.append("initialize")
        return "not-a-mapping"
    client.initialize = bad_initialize
    with pytest.raises(DshProviderRefused,match="unknown"): provider.start({"unitRef": UNIT},context)
    assert projection.binding.state == "unknown" and client.calls == ["initialize"]

def test_query_observes_only_original_binding_without_start():
    provider,projection,records,client,context=fixture()
    context.facts={**context.facts,"action":"query","query":True}
    result=provider.query_step({"operationRef":"original"},context)
    assert result["state"] == "notCreated"
    assert records.begins == 0 and client.calls == []

def test_query_effect_context_rejected():
    provider,projection,records,client,context=fixture()
    with pytest.raises(DshProviderRefused): provider.query_step({},context)
    assert client.calls == []

def test_foreign_verifier_omits_unit_lifecycle():
    projection=Projection(); records=Records(projection,Verifier())
    provider=DshRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
             unit_records=records,projection=projection,verifier=Verifier())
    assert "prepare" not in provider.descriptor.supported_methods


def forged_unit_references():
    from copy import deepcopy
    values=[]
    values.append({"environmentNamespace":UNIT["environmentNamespace"],"unitId":UNIT["unitId"]})
    for key,value in [("environmentNamespace","foreign"),("unitId","different-unit"),
                      ("sourceRevision","sha256:"+"d"*64),("extra","unpublished")]:
        ref=deepcopy(UNIT);ref[key]=value;values.append(ref)
    for key,value in [("providerId","foreign"),("generation",2),("implementationDigest","sha256:"+"e"*64)]:
        ref=deepcopy(UNIT);ref["ownerProviderRef"][key]=value;values.append(ref)
    ref=deepcopy(UNIT);ref["ownerProviderRef"]["ownerActivationRef"]["generation"]=2;values.append(ref)
    ref=deepcopy(UNIT);ref["ownerProviderRef"]["environmentNamespace"]="foreign";values.append(ref)
    ref=deepcopy(UNIT);ref["ownerProviderRef"]["generation"]=True;values.append(ref)
    ref=deepcopy(UNIT);ref["ownerProviderRef"]["ownerActivationRef"]["generation"]=True;values.append(ref)
    return values


@pytest.mark.parametrize("reference",forged_unit_references())
def test_received_full_unit_identity_rejected_before_any_native_start(reference):
    provider,projection,records,client,context=fixture()
    with pytest.raises(DshProviderRefused): provider.start({"unitRef":reference},context)
    assert records.begins == 0 and client.calls == []


@pytest.mark.parametrize("reference",forged_unit_references())
def test_received_full_unit_identity_rejected_by_every_live_read_and_access(reference):
    bound=[]
    lease=SimpleNamespace(bind=lambda *args:bound.append(args))
    provider,projection,records,client,context=fixture(lease_port=lease)
    provider.start({"unitRef":UNIT},context)
    calls=list(client.calls)
    for method,args in [("inspect_unit",(reference,)),("describe_access",(reference,)),
                        ("connect",(reference,object()))]:
        with pytest.raises(DshProviderRefused): getattr(provider,method)(*args)
    assert client.calls == calls and bound == []


def test_prepare_preserves_original_public_reference_without_rehashing():
    provider,projection,records,client,context=fixture()
    result=provider.prepare({"context":{"nodeRef":NODE}},context)
    assert result["unitRef"] is projection.unit.public_ref
    assert set(result["unitRef"]) == {"environmentNamespace","unitId","ownerProviderRef","sourceRevision"}
    assert result["unitRef"]["ownerProviderRef"] == PROVIDER
    assert result["unitRef"]["sourceRevision"] == UNIT["sourceRevision"]
    assert client.calls == []


def test_prepare_does_not_publish_owner_return_with_forged_public_identity():
    from copy import deepcopy
    provider,projection,records,client,context=fixture()
    projection.unit.public_ref=deepcopy(UNIT)
    projection.unit.public_ref["ownerProviderRef"]["generation"]=2
    with pytest.raises(DshProviderRefused): provider.prepare({"context":{"nodeRef":NODE}},context)
    assert client.calls == []


def publication_fixture(projection):
    from ordessa_units.public import DirectoryBindingRef
    return {"unitRef":projection.unit.public_ref,"providerRef":projection.unit.facts["providerRef"],
            "configurationTargetRef":projection.unit.configuration_target_ref,
            "managementEpoch":1,"sourceRevision":"native-owner-observation-3",
            "directoryBindingRef":DirectoryBindingRef("test","workspace",1,"sha256:"+"f"*64),
            "evidenceRef":{"environmentNamespace":"test","evidenceRef":"native-observation"}}


def test_inspection_preserves_current_observation_and_canonical_config_target():
    provider,projection,records,client,context=fixture()
    facts=publication_fixture(projection);projection.publication_facts=lambda ref:facts
    observed=provider.inspect_unit(UNIT)
    assert observed.unit_ref == projection.unit.public_ref
    assert observed.provider_ref == PROVIDER
    assert observed.configuration_target_ref == projection.unit.configuration_target_ref
    assert observed.source_revision == "native-owner-observation-3"
    assert observed.source_revision != UNIT["sourceRevision"]
    assert client.calls == []


@pytest.mark.parametrize("field,value",[("unitRef",{}),("providerRef",{}),("configurationTargetRef",{}),
                                         ("managementEpoch",2),("managementEpoch",True)])
def test_publication_cannot_replace_original_owner_scope_or_epoch(field,value):
    provider,projection,records,client,context=fixture()
    facts=publication_fixture(projection);facts[field]=value;projection.publication_facts=lambda ref:facts
    with pytest.raises(DshProviderRefused): provider.inspect_unit(UNIT)
    assert client.calls == []


def forged_configuration_targets():
    from copy import deepcopy
    values=[]
    values.append({"environmentNamespace":"test","scopeId":"scope","revision":"1"})
    for key,value in [("environmentNamespace","foreign"),("scopeId","different"),("revision","different"),
                      ("sourceRevision","sha256:"+"d"*64),("extra","unpublished")]:
        ref=deepcopy(CONFIGURATION_TARGET);ref[key]=value;values.append(ref)
    ref=deepcopy(CONFIGURATION_TARGET);ref["ownerProviderRef"]["generation"]=2;values.append(ref)
    ref=deepcopy(CONFIGURATION_TARGET);ref["ownerProviderRef"]["generation"]=True;values.append(ref)
    ref=deepcopy(CONFIGURATION_TARGET);ref["ownerProviderRef"]["ownerActivationRef"]["generation"]=True;values.append(ref)
    return values


@pytest.mark.parametrize("target",forged_configuration_targets())
def test_publication_cannot_replace_complete_owner_bound_configuration_target(target):
    provider,projection,records,client,context=fixture()
    facts=publication_fixture(projection);facts["configurationTargetRef"]=target
    projection.publication_facts=lambda ref:facts
    with pytest.raises(DshProviderRefused): provider.inspect_unit(UNIT)
    assert client.calls == []
