"""Pure contribution/planning C; production Unit ports explicitly absent."""
import hashlib
from types import SimpleNamespace
import pytest

from ordessa_harness_claude_code import ClaudeCodeRuntimeProvider, ClaudeProviderUnavailable


def provider(**kwargs):
    return ClaudeCodeRuntimeProvider(definition_ref={"environmentNamespace": "test", "definitionId": "claude", "revision": "1"},
                                    implementation_digest="sha256:" + "1" * 64, **kwargs)


def test_contribution_is_same_core_registry_contract_no_author_identity():
    runtime = provider()
    assert runtime.contributions().agent_runtime_providers == (runtime,)
    assert runtime.descriptor.contract_version == "agent-runtime/2"
    assert not hasattr(runtime, "owner") and not hasattr(runtime, "generation")
    assert runtime.describe_definition(runtime.descriptor.definition_ref)["commandCatalogId"] == "claude-code"
    assert runtime.descriptor.provider_id == "claude"


@pytest.mark.parametrize("method,args", [
    ("prepare", ({}, None)), ("start", ({}, None)), ("query_step", ({}, None)),
    ("describe_access", ({},)), ("connect", ({}, None)), ("inspect_unit", ({},)),
    ("inspect_configuration", ({},)), ("describe_configuration", ({},)),
    ("query_change", ({}, "operation", None)), ("stop", ({}, None)),
    ("release", ({}, None)), ("recover", ({}, None)),
])
def test_absent_unit_authority_never_succeeds(method, args):
    runtime = provider()
    assert method not in runtime.descriptor.supported_methods
    with pytest.raises(ClaudeProviderUnavailable):
        getattr(runtime, method)(*args)


def test_explicit_installation_path_digest_no_execution(tmp_path, monkeypatch):
    runtime = provider()
    file = tmp_path / "not-a-real-claude"
    file.write_bytes(b"controlled fixture, no executable")
    file.chmod(0o700)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("no launch"))
    digest = "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest()
    result = runtime.inspect_installation({"executable": str(file), "artifactDigest": digest})
    assert result["available"] is True and result["runtimeReady"] == "unknown"
    with pytest.raises(ClaudeProviderUnavailable):
        runtime.inspect_installation({"executable": str(file), "artifactDigest": "sha256:" + "0" * 64})
    assert runtime.inspect_installation({"executable": str(file) + "-absent", "artifactDigest": digest})["available"] is False


def test_nonexecutable_artifact_is_not_available_runtime(tmp_path):
    file = tmp_path / "not-executable"
    file.write_bytes(b"controlled artifact")
    file.chmod(0o600)
    digest = "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest()
    result = provider().inspect_installation({"executable": str(file), "artifactDigest": digest})
    assert result["artifactPresent"] is True and result["executableAvailable"] is False
    assert result["available"] is False and result["runtimeReady"] == "unknown"


def test_explicit_preparation_plan_not_ready_no_directory_created(tmp_path):
    runtime = provider()
    home, work = tmp_path / "home", tmp_path / "work"
    plan = runtime.plan_preparation({"revision": 1}, {"home": str(home), "workspace": str(work),
        "materials": {"model": "controlled"}, "privateRootFacts": {"root": "owner-issued"}}, {"operationRef": "op"})
    assert plan["channel"] == "claude-agent-sdk"
    assert "--input-format" in plan["nativePlan"]["argv"]
    assert not home.exists() and not work.exists()


def test_port_must_declare_exact_real_methods_not_callable_presence():
    class Owner:
        supported_methods = ("invented",)
    with pytest.raises(ClaudeProviderUnavailable):
        provider(unit_port=Owner(), verifier=object())


class Records:
    def __init__(self, verifier):
        self.verifier = verifier
        self.calls = []

    def reserve_unit(self, context, **kwargs):
        self.calls.append(kwargs)
        # Controlled owner fixture, not a production Unit/native proof and not
        # a reimplementation of UnitReservation's source derivation.
        reference = {"environmentNamespace": kwargs["provider_ref"]["environmentNamespace"],
                     "unitId": "controlled-unit", "ownerProviderRef": kwargs["provider_ref"],
                     "sourceRevision": "sha256:" + "3" * 64}
        return SimpleNamespace(public_ref=reference), True


class PreparationAuthority:
    def __init__(self, expected):
        self.expected = expected

    def verify_preparation(self, plan, facts):
        return plan == self.expected and facts.get("inputDigest") == "fixed-input"


class Context:
    def __init__(self, facts):
        self.facts = facts


def preparation_setup():
    verifier = object()
    records = Records(verifier)
    plan = {"channel": "claude-agent-sdk", "privateRootFacts": {"root": "fixed-owner-root"}, "nativePlan": {"argv": ["fixed"]}}
    runtime = provider(verifier=verifier, unit_records=records,
                       preparation_authority=PreparationAuthority(plan))
    facts = {"providerRef": {"environmentNamespace": "test", "providerId": "claude", "contractVersion": "agent-runtime/2",
                            "implementationDigest": runtime.descriptor.implementation_digest},
             "targetRef": {"environmentNamespace": "test", "nodeId": "node"}, "inputDigest": "fixed-input"}
    return runtime, records, plan, Context(facts)


def test_prepare_requires_same_journal_verifier_and_fixed_plan_authority():
    verifier = object()
    records = Records(verifier)
    assert "prepare" not in provider(unit_records=records).descriptor.supported_methods
    assert "prepare" not in provider(verifier=object(), unit_records=records,
        preparation_authority=PreparationAuthority({})).descriptor.supported_methods
    assert "prepare" not in provider(verifier=verifier, unit_records=records).descriptor.supported_methods
    assert records.calls == []


@pytest.mark.parametrize("changed", ["privateRootFacts", "nativePlan"])
def test_valid_claim_digest_does_not_authorize_changed_plan(changed):
    runtime, records, plan, context = preparation_setup()
    changed_plan = dict(plan, **{changed: {"forged": "different"}})
    with pytest.raises(ClaudeProviderUnavailable, match="fixed authorized"):
        runtime.prepare(changed_plan, context)
    assert records.calls == []


@pytest.mark.parametrize("field,value", [
    ("providerId", "pi"), ("contractVersion", "agent-runtime/1"),
    ("implementationDigest", "sha256:" + "2" * 64), ("environmentNamespace", "foreign"),
])
def test_prepare_rejects_other_family_or_fixed_provider_before_reservation(field, value):
    runtime, records, plan, context = preparation_setup()
    context.facts["providerRef"][field] = value
    with pytest.raises(ClaudeProviderUnavailable):
        runtime.prepare(plan, context)
    assert records.calls == []


def test_prepare_only_reserves_original_fixed_plan_no_native_effect():
    runtime, records, plan, context = preparation_setup()
    result = runtime.prepare(plan, context)
    assert result["created"] is True and result["nativeStarted"] is False
    assert len(records.calls) == 1
    assert records.calls[0]["private_root_facts"] == plan["privateRootFacts"]
    assert result["unitRef"]["ownerProviderRef"] == context.facts["providerRef"]
    assert result["unitRef"]["sourceRevision"] == "sha256:" + "3" * 64
    assert "unitReservation" not in result


@pytest.mark.parametrize("damage", ["missing", "extra", "owner", "environment", "source"])
def test_prepare_does_not_fabricate_or_repair_owner_reference(damage):
    runtime, records, plan, context = preparation_setup()
    reserve = records.reserve_unit
    def damaged(*args, **kwargs):
        unit, created = reserve(*args, **kwargs)
        if damage == "missing":
            return object(), created
        reference = dict(unit.public_ref)
        if damage == "extra":
            reference["privateRootFacts"] = {"root": "forbidden"}
        elif damage == "owner":
            reference["ownerProviderRef"] = dict(reference["ownerProviderRef"], providerId="pi")
        elif damage == "environment":
            reference["environmentNamespace"] = "foreign"
        elif damage == "source":
            reference.pop("sourceRevision")
        return SimpleNamespace(public_ref=reference), created
    records.reserve_unit = damaged
    with pytest.raises(ClaudeProviderUnavailable, match="public source"):
        runtime.prepare(plan, context)
    assert len(records.calls) == 1  # reserved original; no second reserve or native start.


@pytest.mark.parametrize("field", ["generation", "ownerActivationGeneration"])
def test_prepare_rejects_bool_masquerading_as_owner_generation(field, monkeypatch):
    runtime, records, plan, context = preparation_setup()
    owner = context.facts["providerRef"]
    owner["generation"] = 1
    owner["ownerActivationRef"] = {"environmentNamespace": "test", "pluginId": "claude-provider", "generation": 1}
    original_reserve = records.reserve_unit

    def forged(*args, **kwargs):
        unit, created = original_reserve(*args, **kwargs)
        reference = dict(unit.public_ref)
        forged_owner = dict(reference["ownerProviderRef"])
        if field == "generation":
            forged_owner["generation"] = True
        else:
            forged_owner["ownerActivationRef"] = dict(forged_owner["ownerActivationRef"], generation=True)
        # Python equality would accept this. The whole public owner reference
        # must retain types, including its nested activation generation.
        assert forged_owner == owner
        reference["ownerProviderRef"] = forged_owner
        return SimpleNamespace(public_ref=reference), created

    records.reserve_unit = forged
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("prepare must not start native process"))
    monkeypatch.setattr("ordessa_harness_claude_code.sdk.installed_sdk_factory",
                        lambda: pytest.fail("prepare must not load actual SDK"))
    with pytest.raises(ClaudeProviderUnavailable, match="public source"):
        runtime.prepare(plan, context)
    assert len(records.calls) == 1
    assert type(owner["generation"]) is int
    assert type(owner["ownerActivationRef"]["generation"]) is int
    assert "start" not in runtime.descriptor.supported_methods
