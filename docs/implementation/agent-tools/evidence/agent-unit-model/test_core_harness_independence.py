"""Two unrelated generic RuntimeProviders through one Pacthold Environment.

These controlled fixtures own their private channel formats. They exercise the
same CoreRegistry, AgentServices, preparation, configuration, and owner-read
surfaces; they are contract evidence, not native-process or model evidence.
"""
from dataclasses import replace
import ast
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "products/agent-tools/tests/integration"))
from test_invocation_authority import Authority
from test_node_publication import Policy

from ordessa_environment_api import (
    AdmissionRefusedError, GuaranteeUnavailableError, RequestKey,
)
from ordessa_environment_api.operations import UsageMutation, operation_holder, safe_json
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from pacthold.agents.assembly import PreparationContext, PreparationObservation
from pacthold.agents.configuration import (
    ApplicationPolicy, ConfigurationChangeRequest, ConfigurationDescription,
    ConfigurationChangeResult, ConfigurationItemResult, ConfigurationSnapshot,
    ConfigurationUnsupported, UnitInspection,
)
from pacthold.agents.contracts import ProfileRef
from pacthold.agents.directory import DirectoryBindingRef
from pacthold.agents.invocation import InvocationCurrentState, InvocationIssuer
from pacthold.agents.nodes import NodePublicationEvidence, decode_node_ref
from pacthold.agents.profiles import ProfileCatalog
from pacthold.agents.public import agent_services
from pacthold.agents.runtime import (
    AgentContributionSet, RUNTIME_METHODS, RUNTIME_PROVIDER_VERSION,
    RuntimeProviderDescriptor,
)
from pacthold.public import Environment, InstallationRecord


_METHODS = tuple(RUNTIME_METHODS)


def _source(provider_ref, ref):
    return {"environmentNamespace": "env", "ownerProviderRef": json.loads(safe_json(provider_ref)),
            "sourceRevision": "owner-rev-1", "ref": ref}


class _CurrentState:
    """Trusted fixture supplies the exact current provider and fixed directory."""
    def __init__(self, directory):
        self.directory = directory

    def inspect(self, request, pinned_provider_ref, context_ref, target_ref, action):
        return InvocationCurrentState(pinned_provider_ref, True, 0, self.directory, True)


class _PreparationContext:
    def __init__(self, directory):
        self.directory = directory

    def resolve(self, request, manifest, admitted, node_ref, context, options):
        return PreparationContext(self.directory,
            {"installationRef": {"environmentNamespace": "env", "installationId": admitted.descriptor.provider_id,
                                  "sourceRevision": "fixture-install-1"}},
            {"nodeRef": node_ref, "privateBinding": admitted.descriptor.definition_ref})


class _OwnerEvidence:
    """Fixture-owned receipt and owner-read projection for both providers."""
    def __init__(self, catalog, providers):
        self.catalog, self.providers = catalog, providers

    def observe(self, operation, step, reply):
        provider_ref = step.pinned_provider_ref
        provider_id = provider_ref["providerId"]
        unit_ref = _source(provider_ref, "unit:" + provider_id)
        usages = ()
        if step.step_id == "prepare":
            usages = (UsageMutation(operation.intent.operation_ref + ".unit", 0, None,
                operation_holder(operation.request, operation.intent.operation_ref), unit_ref,
                ("use",), "active"),)
        return PreparationObservation(step.step_id, provider_ref, step.input_digest,
            step.recovery_correlation, _source(provider_ref, "receipt:" + step.step_id),
            {"unitRef": unit_ref}, usages)

    def inspect(self, operation, steps):
        provider_ref = operation.intent.steps[0].pinned_provider_ref
        definition_ref = self.catalog.read(ProfileRef.from_dict(
            json.loads(safe_json(operation.intent.profile_snapshot_ref)))).content["harnessDefinitionRef"]
        provider = self.providers[definition_ref["definitionId"]]
        unit_ref = steps[0].evidence["preparedUnit"]["unitRef"]
        return NodePublicationEvidence(provider_ref,
            {"nodeRef": operation.intent.node_ref, "operationRef": operation.intent.operation_ref,
             "profileSnapshotRef": operation.intent.profile_snapshot_ref,
             "preparationContextRef": operation.intent.context_ref,
             "harnessProviderRef": provider_ref, "harnessDefinitionRef": definition_ref,
             "harnessUnitRef": unit_ref, "configurationTargetRef": provider.target_ref,
             "nativeSessionRefs": ()},
            tuple({"stepId": row.intent.step_id, "providerRef": row.intent.pinned_provider_ref,
                   "inputDigest": row.intent.input_digest,
                   "recoveryCorrelation": row.intent.recovery_correlation,
                   "evidenceRef": row.evidence["evidenceRef"]} for row in steps),
            (_source(provider_ref, "access:" + provider.descriptor.provider_id),))


class _ProviderBase:
    provider_id = ""
    definition_id = ""
    configuration_kind = ""
    configuration_schema = ""
    initial_payload = None
    update_payload = None

    def __init__(self, *, supported_methods=_METHODS):
        self.descriptor = RuntimeProviderDescriptor(self.provider_id, RUNTIME_PROVIDER_VERSION,
            {"environmentNamespace": "env", "definitionId": self.definition_id, "revision": "1"},
            "sha256:" + ("a" if self.provider_id == "provider.record" else "b") * 64,
            tuple(supported_methods))
        self.issuer = None
        self.directory = None
        self.provider_ref = None
        self.target_ref = None
        self.value = None
        self.revision = "native-rev-1"
        self.private_channel_events = []

    def bind_fixture(self, issuer, directory, provider_ref):
        self.issuer, self.directory, self.provider_ref = issuer, directory, provider_ref
        self.target_ref = _source(provider_ref, "configuration-scope:" + self.provider_id)

    def _verify(self, action, invocation):
        facts = invocation.facts
        self.issuer.verifier().verify_and_consume(invocation, action, facts["providerRef"],
                                                  facts["targetRef"], facts["inputDigest"])

    def prepare(self, plan, invocation):
        self._verify("prepare", invocation)
        self.value = self._initial_value(plan)
        self.private_channel_events.append(self._prepare_event(plan))
        return {"accepted": True}

    def start(self, prepared, invocation):
        self._verify("start", invocation)
        self.private_channel_events.append(self._start_event(prepared))
        return {"accepted": True}

    def query_step(self, correlation, invocation):
        self._verify("query", invocation)
        return {"correlation": correlation}

    def inspect_unit(self, unit_ref):
        return UnitInspection(unit_ref, self.provider_ref, self.target_ref, self.directory, 0, "owned",
            "unit-rev-1", "2026-10-06T00:00:00Z", _source(self.provider_ref, "unit-read"))

    def describe_configuration(self, unit_ref):
        return (ConfigurationDescription(self.configuration_kind, self.configuration_schema,
            self._input_schema(), ("value", "reset", "disabled"), "instance", ("live",),
            "readback", "supported"),)

    def inspect_configuration(self, unit_ref):
        return ConfigurationSnapshot(unit_ref, self.target_ref, self.revision,
            "2026-10-06T00:00:00Z", {self.configuration_kind: self.value}, (),
            _source(self.provider_ref, "configuration-read"), "ownerSerialized")

    def apply_configuration(self, unit_ref, change, invocation):
        self._verify("applyConfiguration", invocation)
        declaration = change.declarations[0]
        self.value = self._apply_payload(declaration["payload"])
        self.revision = "native-rev-2"
        facts = invocation.facts
        confirmation = {"operationRef": facts["operationRef"], "unitRef": unit_ref,
            "scopeRef": self.target_ref, "requestDigest": facts["inputDigest"],
            "evidenceRef": _source(self.provider_ref, "configuration-apply")}
        item = ConfigurationItemResult(declaration["declarationId"], "applied", confirmation)
        snapshot = self.inspect_configuration(unit_ref)
        return ConfigurationChangeResult(facts["operationRef"], (item,), snapshot)

    def query_change(self, unit_ref, operation_ref, invocation):
        self._verify("query", invocation)
        raise NotImplementedError("the fixture does not need native query for confirmed writes")

    def plan_preparation(self, snapshot, context, correlation):
        manifest = snapshot["manifest"]
        declaration = manifest["declarations"][0]
        assert declaration["configurationKind"] == self.configuration_kind
        return self._private_plan(correlation, declaration["payload"])

    def _initial_value(self, plan):
        return self._apply_payload(self._plan_payload(plan))


class _RecordChannelProvider(_ProviderBase):
    """Fixture A's private channel is record-oriented."""
    provider_id = "provider.record"
    definition_id = "definition.record"
    configuration_kind = "record.preferences"
    configuration_schema = "record-v4"

    def _input_schema(self):
        return {"type": "object", "required": ["record"], "properties": {"record": {"type": "object"}}}

    def _private_plan(self, correlation, payload):
        # Keep this provider's nested record protocol independent from the
        # command provider while ensuring the core sees only finite JSON.
        return {"record": {"verb": "open", "ticket": correlation["operationRef"],
                           "initial": json.loads(safe_json(payload))}}

    def _plan_payload(self, plan):
        return plan["record"]["initial"]

    def _prepare_event(self, plan):
        return ("record-open", plan["record"]["ticket"])

    def _start_event(self, prepared):
        return {"recordCommit": prepared}

    def _apply_payload(self, payload):
        assert set(payload) == {"record"}
        return payload["record"]


class _CommandChannelProvider(_ProviderBase):
    """Fixture B speaks an unrelated positional command dialect."""
    provider_id = "provider.command"
    definition_id = "definition.command"
    configuration_kind = "command.profile"
    configuration_schema = "command-v9"

    def _input_schema(self):
        return {"type": "object", "required": ["arguments"], "properties": {
            "arguments": {"type": "array", "items": {"type": "string"}, "minItems": 1}}}

    def _private_plan(self, correlation, payload):
        # Keep the provider's positional command dialect private inside a
        # generic JSON plan envelope accepted by the core fingerprint port.
        return {"commandFrame": ["spawn", correlation["startCorrelation"], list(payload["arguments"])]}

    def _plan_payload(self, plan):
        return {"arguments": list(plan["commandFrame"][2])}

    def _prepare_event(self, plan):
        return ["preload", plan["commandFrame"][1], list(plan["commandFrame"][2])]

    def _start_event(self, prepared):
        return ("exec", prepared)

    def _apply_payload(self, payload):
        assert set(payload) == {"arguments"}
        return list(payload["arguments"])


for _method in _METHODS:
    if not hasattr(_ProviderBase, _method):
        setattr(_ProviderBase, _method, lambda *args, **kwargs: None)


def _build_core_pair(data_root, omitted_methods=None):
    data_root.mkdir(parents=True, exist_ok=True)
    store = SqliteStorePort(data_root / "two-providers.sqlite")
    directory = DirectoryBindingRef("env", "shared-directory", 1, "sha256:" + "d" * 64)
    env = Environment("env", store=store, policy=Policy(), principal_scope="principal",
        fingerprint_port=ProtectedFingerprintHmac({"fixture": b"two-provider-contract"}, active_key_id="fixture"))
    omitted_methods = omitted_methods or {}
    providers = tuple(provider_type(supported_methods=tuple(
        method for method in _METHODS if method not in omitted_methods.get(provider_type.provider_id, ())))
        for provider_type in (_RecordChannelProvider, _CommandChannelProvider))
    activations = {}
    for index, provider in enumerate(providers):
        plugin_id = "fixture.plugin." + str(index)
        env.install(InstallationRecord(plugin_id, str(index + 1) * 64))
        env.enable(plugin_id)
        activations[provider.definition_id] = env.activate(plugin_id,
            AgentContributionSet(agent_runtime_providers=(provider,))).activation
    authority = Authority()
    issuer = InvocationIssuer(store, authority, _CurrentState(directory), clock=lambda: 50)
    for provider in providers:
        provider_ref = env.agent_runtime_contribution(provider.descriptor.definition_ref).provider_ref
        provider.bind_fixture(issuer, directory, provider_ref)
    catalog = ProfileCatalog(env)
    owner = _OwnerEvidence(catalog, {item.definition_id: item for item in providers})
    services = agent_services(env, invocation_issuer=issuer, node_evidence_port=owner,
        preparation_context_port=_PreparationContext(directory),
        preparation_observation_port=owner)
    return env, store, providers, activations, issuer, catalog, owner, services


@pytest.fixture
def core_pair(tmp_path):
    parts = _build_core_pair(tmp_path)
    yield parts
    parts[1].close()


def _declaration(provider, payload):
    return {"declarationId": "primary", "configurationKind": provider.configuration_kind,
        "schemaVersion": provider.configuration_schema, "action": "value", "requirement": "required",
        "payload": payload}


def _prepare_and_inspect(parts, provider, suffix):
    env, _, _, _, _, catalog, _, services = parts
    manifest = {"harnessDefinitionRef": dict(provider.descriptor.definition_ref), "schemaVersion": "1",
        "declarations": [_declaration(provider, provider.initial_payload)]}
    entry = catalog.create(profile_id="profile-" + suffix, display_name="Profile " + suffix,
        manifest=manifest, request=RequestKey("env", "principal", "create-" + suffix))
    operation = services.assembly.prepare(RequestKey("env", "principal", "prepare-" + suffix),
        entry.current_manifest_ref, {}, {})
    assert operation.status == "published"
    node_ref = decode_node_ref(operation.intent.node_ref)
    before = services.configuration.inspect(node_ref)
    return operation, node_ref, before


def _prepare_and_change(parts, provider, suffix):
    operation, node_ref, before = _prepare_and_inspect(parts, provider, suffix)
    services = parts[7]
    request = RequestKey("env", "principal", "configure-" + suffix)
    change = ConfigurationChangeRequest(request.request_id, before.source_revision,
        (_declaration(provider, provider.update_payload),), ApplicationPolicy())
    result = services.configuration.apply(request, node_ref, change)
    after = services.configuration.inspect(node_ref)
    return operation, node_ref, before, result, after


def test_two_unrelated_provider_contracts_share_one_core_for_prepare_configure_and_read(core_pair):
    env, store, providers, _, _, _, _, services = core_pair
    assert services is __import__("pacthold.agents.public", fromlist=["agent_services"]).agent_services(env)
    assert {item.descriptor.provider_id for item in env.agent_runtime_contributions()} == {
        "provider.record", "provider.command"}
    expected = (
        ({"record": {"tone": "cool"}}, {"record": {"tone": "warm"}}),
        ({"arguments": ["--profile", "quiet"]}, {"arguments": ["--profile", "bold"]}),
    )
    for provider, (initial, updated), suffix in zip(providers, expected, ("record", "command")):
        provider.initial_payload, provider.update_payload = initial, updated
        operation, node_ref, before, result, after = _prepare_and_change(core_pair, provider, suffix)
        assert operation.intent.steps[0].pinned_provider_ref["providerId"] == provider.provider_id
        assert before.to_dict()["configuration"][provider.configuration_kind] == provider._apply_payload(initial)
        assert result.status == "published"
        assert after.to_dict()["configuration"][provider.configuration_kind] == provider._apply_payload(updated)
        assert [event for event in provider.private_channel_events]
        assert store.read_operation(RequestKey("env", "principal", "configure-" + suffix)).status == "published"
        assert services.nodes.read(node_ref)["binding"]["harnessDefinitionRef"] == provider.descriptor.definition_ref
    assert providers[0].private_channel_events != providers[1].private_channel_events


def test_draining_and_retiring_one_provider_leaves_other_provider_usable(core_pair):
    env, _, providers, activations, _, _, _, services = core_pair
    providers[0].initial_payload, providers[0].update_payload = {"record": {"x": 1}}, {"record": {"x": 2}}
    providers[1].initial_payload, providers[1].update_payload = {"arguments": ["a"]}, {"arguments": ["b"]}
    _, node_a, _, _, _ = _prepare_and_change(core_pair, providers[0], "retire-record")
    _, node_b, _, _, _ = _prepare_and_change(core_pair, providers[1], "keep-command")
    activation = activations[providers[0].definition_id]
    env.drain(activation)
    assert [item["descriptor"]["providerId"] for item in services.providers.list()] == [providers[1].provider_id]
    with pytest.raises(AdmissionRefusedError):
        services.configuration.inspect(node_a)
    assert services.configuration.inspect(node_b).to_dict()["configuration"][providers[1].configuration_kind] == ["b"]
    state, blockers = env.retire(activation)
    assert state == "retired" and blockers == ()
    assert services.configuration.inspect(node_b).to_dict()["configuration"][providers[1].configuration_kind] == ["b"]


def test_wrong_owner_and_version_drift_fail_closed(core_pair):
    env, _, providers, _, _, _, _, services = core_pair
    provider = providers[0]
    provider.initial_payload, provider.update_payload = {"record": {"x": 1}}, {"record": {"x": 2}}
    _, node_ref, before, _, _ = _prepare_and_change(core_pair, provider, "guards")

    original_inspect = provider.inspect_unit
    provider.inspect_unit = lambda unit_ref: replace(original_inspect(unit_ref),
        provider_ref=providers[1].provider_ref)
    with pytest.raises(GuaranteeUnavailableError):
        services.configuration.inspect(node_ref)
    provider.inspect_unit = original_inspect

    provider.descriptor = replace(provider.descriptor, implementation_digest="sha256:" + "f" * 64)
    with pytest.raises(AdmissionRefusedError):
        services.configuration.inspect(node_ref)

    assert before.source_revision == "native-rev-1"


def test_wrong_contract_version_is_rejected_at_provider_descriptor_boundary(core_pair):
    provider = core_pair[2][0]
    with pytest.raises(ValueError):
        replace(provider.descriptor, contract_version="agent-runtime/999")


def test_missing_apply_capability_refuses_before_claim(tmp_path):
    limited = _build_core_pair(tmp_path / "limited",
        {"provider.record": {"apply_configuration"}})
    try:
        limited_provider = limited[2][0]
        limited_provider.initial_payload, limited_provider.update_payload = {"record": {"x": 1}}, {"record": {"x": 2}}
        _, node_ref, before = _prepare_and_inspect(limited, limited_provider, "limited-method")
        request = RequestKey("env", "principal", "limited-method-apply")
        change = ConfigurationChangeRequest(request.request_id, before.source_revision,
            (_declaration(limited_provider, limited_provider.update_payload),), ApplicationPolicy())
        with pytest.raises(ConfigurationUnsupported):
            limited[7].configuration.apply(request, node_ref, change)
        assert limited[1].read_operation(request) is None
        assert limited_provider.revision == "native-rev-1"
    finally:
        limited[1].close()


@pytest.mark.parametrize("module", [
    "ordessa_harness_pi.runtime",
    "ordessa_harness_codex.runtime",
    "ordessa_harness_claude_code.runtime",
    "plugins.harness.pi.runtime",
    "provider_vendor.claude.runtime",
])
def test_brand_import_scanner_detects_injected_imports(module):
    source = f"from {module} import RuntimeProvider\n"
    assert _brand_imports(source), "the static gate must prove it can detect a brand import"


def _brand_imports(source):
    tree = ast.parse(source)
    brands = {"pi", "codex", "claude", "claude_code"}
    matches = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        for module in modules:
            parts = module.lower().split(".")
            if any(part.startswith("ordessa_harness_") or part in brands for part in parts):
                matches.append(module)
    return tuple(matches)


def test_pacthold_agent_core_has_no_brand_specific_imports():
    root = Path(__file__).resolve().parents[5] / "packages/backend/pacthold/src/pacthold"
    sources = [path for section in ("agents", "core") for path in (root / section).rglob("*.py")]
    findings = {str(path.relative_to(root)): _brand_imports(path.read_text(encoding="utf-8"))
                for path in sources}
    assert not {path: imports for path, imports in findings.items() if imports}
