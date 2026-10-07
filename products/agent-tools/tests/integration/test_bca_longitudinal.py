"""B/C/A longitudinal integration over the real in-tree interfaces.

Freezes (authoritative, executed verbatim):
  B  docs/implementation/agent-tools/configuration-provider-admission-freeze-v1.md
     (s2 definition precise-equality association, s3 admitted metadata)
  C  docs/implementation/agent-tools/material-authorized-handoff-freeze-v1.md
     (s1 consumer-pin admission-side copy trust source, s3 read-result evidence)
  A  docs/implementation/agent-tools/preparation-effects-freeze-v1.md
     (s4 dependency cut: B pin shape along B s2, C material legality = C
      handoff-verified set membership)

Chain proven here with REAL in-tree B/C/A APIs on ONE Environment/Store:

  B  Registry admission of a configuration contribution riding the existing
     AgentContributionSet channel (s1), incl. the s2 precise-equality
     association: the route's definition_ref byte-equals an admitted
     RuntimeProvider descriptor definition_ref in the same Registry.
  B  discovery via Environment.agent_configuration_contribution /
     agent_configuration_contributions and the AgentProviders thin projection
     (s3 read-only metadata, no callable).
  020 validate_reference_extraction over the admitted descriptor, with
     caller-fixed identities derived from B discovery; the extraction's
     reference pins the exact material ResourceRef later handed off.
  C  authorized material read handoff (MaterialOperations.acquire +
     MaterialConsumption.read) with the consumer pin constructed as an
     admission-side copy from B's AdmittedConfigurationProviderMetadata.
     owner_activation (s1 trust source); the admitted-consumer evidence port
     is served by B's real Registry query, not a hand-fabricated pin.
  A  staged effect assembly (reserve -> run_root -> verify_preparation_effect
     -> staged append+seal) whose provider_pin is the B-acknowledged runtime
     pin and whose material_refs are exactly the C handoff-verified pointer
     set read back from the durable C read evidence.

Controlled fixtures only on the provider/owner side: the A "harness" runtime,
the configuration host, the material provider and the observation/context
owners are in-process controlled objects. Real Harness processes, real model
calls, cold recovery, effect-step native execution and node publication of the
expanded recipe are NOT_RUN and are not claimed: the sealed recipe keeps its
effect steps unexecuted and publication stays fail-closed.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from typing import ClassVar

import pytest

from ordessa_environment_api import (
    AdmissionRefusedError,
    IdentityMismatchError,
    RequestKey,
    UnknownResultError,
)
from ordessa_environment_api.identity import ActivationRef, ParticipantInstanceRef
from ordessa_environment_api.operations import (
    OperationIntent,
    StepIntent,
    UsageMutation,
    operation_holder,
    safe_json,
    sealed_mapping,
)
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from pacthold.agents.assembly import (
    AgentAssembly,
    PreparationContext,
    PreparationObservation,
)
from pacthold.agents.configuration_references import (
    ConfigurationReference,
    ConfigurationReferenceExtraction,
    validate_reference_extraction,
)
from pacthold.agents.directory import DirectoryBindingRef
from pacthold.agents.invocation import (
    InvocationCurrentState,
    InvocationGrant,
    InvocationIssuer,
)
from pacthold.agents.material_consumption import (
    AGENT_MATERIAL_CONSUMPTION_CONTRACT_VERSION,
    READ_ACTION,
    MaterialConsumption,
)
from pacthold.agents.material_operations import (
    MaterialOperations,
    material_invocation_target,
    material_operation_facts,
    material_provider_ref,
    material_reservation_usages,
)
from pacthold.agents.materials import (
    AGENT_MATERIAL_CONTRACT_VERSION,
    MaterialAccessMode,
    MaterialCapability,
    MaterialConsumerPin,
    MaterialCorrelation,
    MaterialEvidenceRef,
    MaterialLeaseRef,
    MaterialLifetime,
    MaterialObjectRef,
    MaterialOutcome,
    MaterialProviderPin,
    MaterialReadResult,
    MaterialReceipt,
    MaterialRequest,
    MaterialResult,
    MaterialUseTarget,
    ResourceMaterialDescriptor,
    ResourceRef,
)
from pacthold.agents.nodes import NodePublication, NodePublicationEvidence
from pacthold.agents.preparation_effects import (
    EffectStep,
    PreparationEffectPlan,
    verify_preparation_effect,
)
from pacthold.agents.profiles import ProfileCatalog
from pacthold.agents.public import (
    AdmittedConfigurationProviderMetadata,
    agent_services,
)
from pacthold.agents.runtime import (
    RUNTIME_METHODS,
    RUNTIME_PROVIDER_VERSION,
    AgentContributionSet,
    RuntimeProviderDescriptor,
)
from pacthold.core.configuration_admission import (
    CONFIGURATION_PROVIDER_VERSION,
    ConfigurationContractError,
    ConfigurationProviderPin,
    ConfigurationRoute,
)
from pacthold.public import (
    CoreContributionSet,
    Environment,
    InstallationRecord,
    ReconcileSupport,
    ResourceProviderDescriptor,
)


ENV = "bca-longitudinal"
PRINCIPAL = "principal"
CONTRACT_ID = "sample.alpha@1"

RUNTIME_PROVIDER_ID = "fixture.runtime"
CONFIG_PROVIDER_ID = "fixture.config"
MATERIAL_PROVIDER_ID = "provider.material"

RUNTIME_DEFINITION = {"environmentNamespace": ENV, "definitionId": "fixture",
                      "revision": "1"}
RUNTIME_IMPLEMENTATION = "sha256:" + "a" * 64
CONFIG_IMPLEMENTATION = "sha256:" + "b" * 64

CONFIGURATION_KIND = "assets.model-provider"
CONFIGURATION_SCHEMA = "schema/1"
# 020 extraction contract: declaration digest is a bare lowercase SHA-256 hex
# (test_configuration_provider_contract convention); A's plan digest gate
# accepts the same bounded string, so the cross-lane binding uses one value.
DECLARATION_DIGEST = "c" * 64
DECLARATION_ID = "declaration-bca"

CONSUMER_ID = "fixture.plugin"      # the B-admitted configuration owner host
CONSUMER_VERSION = "1.0"

OUTER_DIGEST = "bca-acquire-digest"
READ_DIGEST = "bca-read-digest"
BAD_READ_DIGEST = "bca-bad-read-digest"
ACQUIRE_STEP = "material-fetch"
READ_STEP = "material-read"
ACQUIRE_OP = "operation-bca-acquire"
READ_OP = "operation-bca-read"
BAD_READ_OP = "operation-bca-bad-read"
MATERIAL_EPOCH = 4
PREPARE_REQUEST = RequestKey(ENV, PRINCIPAL, "bca-prepare")
ACQUIRE_REQUEST_KEY = RequestKey(ENV, PRINCIPAL, "bca-material-acquire")
READ_REQUEST_KEY = RequestKey(ENV, PRINCIPAL, "bca-material-read")
BAD_READ_REQUEST_KEY = RequestKey(ENV, PRINCIPAL, "bca-material-bad-read")

CANARY = "CANARY-BCA-BODY-7d2e91"

BRAND_KEYS = frozenset({
    "command", "argv", "executable", "codec", "brand", "providercommand",
    "nativecommand", "shell", "script", "binary", "path", "cwd",
})


def _scan_brands(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("_", "").replace("-", "")
            assert normalized not in BRAND_KEYS, "brand-shaped key survived: %s" % key
            _scan_brands(child)
    elif isinstance(value, list):
        for child in value:
            _scan_brands(child)


# --------------------------------------------------------------------------
# Controlled fixtures (provider/owner side only; never a real Harness)
# --------------------------------------------------------------------------

class Policy:
    def admit_object_access(self, *args):
        return True

    def admit_invoke(self, *args):
        return True


@dataclass(frozen=True)
class AlphaContract:
    contract_id: ClassVar[str] = CONTRACT_ID


class Authority:
    issuer_ref = {"environmentNamespace": ENV, "issuerId": "controlled-authority"}

    def __init__(self):
        self.revision = "authority-rev-1"

    def authorize(self, request, actions, target_ref, delegation_ref):
        return InvocationGrant(
            principal_scope=request.principal_scope,
            delegation_ref=delegation_ref,
            actions=actions,
            target_ref=target_ref,
            authority_revision=self.revision,
            expires_at=100,
            issuer_ref=self.issuer_ref,
        )

    def revalidate(self, grant, request, actions, target_ref):
        return self.authorize(request, actions, target_ref, grant.delegation_ref)


class CurrentState:
    """Trusted current-state port serving BOTH the A runtime and C material legs.

    Dispatches on the step's pinned provider reference: A preparation steps
    pin the B-acknowledged runtime provider (epoch 0), material steps pin the
    admitted material provider (epoch 4). No cleanup bindings exist in this
    chain, so no acquisition relationship is fabricated here.
    """

    def __init__(self):
        self.runtime_provider_ref = None
        self.material_provider_ref = None

    def inspect(self, request, pinned_provider_ref, context_ref, target_ref, action):
        directory = DirectoryBindingRef.from_dict(
            json.loads(safe_json(context_ref["directoryBindingRef"])))
        if safe_json(pinned_provider_ref) == safe_json(self.runtime_provider_ref):
            return InvocationCurrentState(self.runtime_provider_ref, True, 0,
                                          directory, True)
        if safe_json(pinned_provider_ref) == safe_json(self.material_provider_ref):
            return InvocationCurrentState(self.material_provider_ref, True,
                                          MATERIAL_EPOCH, directory, True)
        raise AssertionError("step pins an unknown provider reference")


class RuntimeHostProvider:
    """Controlled A-side harness runtime; never a real Harness process."""

    def __init__(self):
        self.descriptor = RuntimeProviderDescriptor(
            RUNTIME_PROVIDER_ID, RUNTIME_PROVIDER_VERSION, dict(RUNTIME_DEFINITION),
            RUNTIME_IMPLEMENTATION,
            ("assess_configuration", "plan_preparation", "prepare", "start",
             "query_step"))
        self.calls = []
        self.invocations = {}
        self.issuer = None

    def plan_preparation(self, snapshot, context, correlation):
        return {"snapshot": snapshot, "context": context, "correlation": correlation}

    def _invoke(self, action, invocation):
        facts = invocation.facts
        self.calls.append(action)
        self.invocations[action] = invocation
        self.issuer.verify_and_consume(
            invocation, action, facts["providerRef"], facts["targetRef"],
            facts["inputDigest"])
        return {"ack": True}

    def prepare(self, plan, invocation):
        return self._invoke("prepare", invocation)

    def start(self, prepared, invocation):
        return self._invoke("start", invocation)

    def query_step(self, correlation, invocation):
        return self._invoke("query", invocation)


for _name in RUNTIME_METHODS:
    if not hasattr(RuntimeHostProvider, _name):
        setattr(RuntimeHostProvider, _name, lambda *args, **kwargs: None)


class ConfigurationHostProvider:
    """Controlled B-side configuration provider mounted on a RuntimeProvider.

    Its route acknowledges the RUNTIME host's definition (B s2 cross-provider
    precise-equality association); its Runtime descriptor declares
    assess_configuration so the route is usable at discovery time.
    """

    def __init__(self):
        self.descriptor = RuntimeProviderDescriptor(
            CONFIG_PROVIDER_ID, RUNTIME_PROVIDER_VERSION,
            {"environmentNamespace": ENV, "definitionId": "fixture-config",
             "revision": "1"},
            CONFIG_IMPLEMENTATION, ("assess_configuration",))
        self.configuration_routes = (
            ConfigurationRoute(
                CONFIGURATION_KIND, CONFIGURATION_SCHEMA,
                (dict(RUNTIME_DEFINITION),), ("value",), ("model.selection",)),
        )


for _name in RUNTIME_METHODS:
    setattr(ConfigurationHostProvider, _name, lambda *args, **kwargs: None)


class ControlledMaterialProvider:
    """Registered C-side material provider fixture with inspectable counters."""

    def __init__(self, provider_id, capability, *, version="1.0"):
        self.provider_id = provider_id
        self.display_name = "Controlled BCA material fixture"
        self.version = version
        self.supported_contract_ids = frozenset({CONTRACT_ID})
        self.material_capability = capability
        self.descriptor = None
        self.verifier = None
        self.operation_kind = "bca-material-fixture"
        self.material_target = None
        self.material_provider = None
        self.acquisition_receipt = None
        self.read_calls = 0
        self.content_reads = 0
        self.content_body = CANARY
        self.query_calls = 0
        self.release_calls = 0
        self.c1_calls = {"acquire": 0, "release": 0, "reconcile": 0}

    def describe(self):
        return ResourceProviderDescriptor(
            self.provider_id, self.display_name, self.version,
            ReconcileSupport.SUPPORTED)

    def acquire(self, request):
        self.c1_calls["acquire"] += 1
        raise AssertionError("material coordination must not fall back to C1 acquire")

    def release(self, request):
        self.c1_calls["release"] += 1
        raise AssertionError("material coordination must not fall back to C1 release")

    def reconcile(self, request):
        self.c1_calls["reconcile"] += 1
        raise AssertionError("material coordination must not fall back to C1 reconcile")

    def describe_material(self, resource_ref, principal):
        assert principal == PRINCIPAL
        return self.descriptor

    def _verify(self, invocation, request, action):
        self.verifier.verify_and_consume(
            invocation, action, self.material_provider, self.material_target,
            request.input_digest)

    def resolve_material(self, request, invocation):
        self._verify(invocation, request, "acquire")
        lease = MaterialLeaseRef(
            "lease-bca", request.resource_ref, request.provider_pin,
            request.target, request.correlation)
        receipt = MaterialReceipt(
            request.resource_ref, request.provider_pin, request.target,
            request.correlation, self.descriptor.descriptor_digest,
            MaterialObjectRef(ENV, "opaque-bca-material", "1"),
            self.descriptor.content_digest, self.descriptor.material_type,
            self.descriptor.schema_version, lease,
            self.descriptor.provenance_ref,
            MaterialEvidenceRef(ENV, "bca-acquisition-evidence", "1"))
        self.acquisition_receipt = receipt
        return MaterialResult(MaterialOutcome.SUCCESS, request.correlation,
                              receipt=receipt)

    def read_material(self, request, invocation):
        self.read_calls += 1
        self._verify(invocation, request, READ_ACTION)
        self.content_reads += 1
        _ = self.content_body  # content access counted; body never leaves
        receipt = self.acquisition_receipt
        return MaterialReadResult(
            MaterialOutcome.SUCCESS, request.correlation,
            receipt.immutable_material_ref, receipt.content_digest,
            receipt.evidence_ref, None)

    def query_material(self, request, invocation):
        self.query_calls += 1
        raise AssertionError("read handoff must not use query semantics")

    def release_material(self, request, invocation):
        # The copyComplete release gate stays closed in this chain (read
        # success is not consumption, no owner evidence is presented), so the
        # release path must never dispatch. C's own suite covers release.
        self.release_calls += 1
        raise AssertionError("this chain never releases: no consumption evidence")


class ContextOwner:
    revision = "installation-1"

    def resolve(self, request, manifest, admitted, node, context, options):
        return PreparationContext(
            self.directory,
            {"installationRef": {"environmentNamespace": ENV,
                                 "installationId": "isolated",
                                 "sourceRevision": self.revision}},
            {"nodeRef": node, "privateRootFacts": {"cwd": "/controlled/fixture"}})


def _owner_source(provider_ref, identity):
    return {"environmentNamespace": ENV,
            "ownerProviderRef": json.loads(safe_json(provider_ref)),
            "sourceRevision": "installation-1", "ref": identity}


class Owner:
    """Trusted observation fixture, explicitly not native owner proof."""

    def observe(self, operation, step, reply):
        provider = step.pinned_provider_ref
        unit = _owner_source(provider, "actual-unit")
        holds = () if step.step_id == "start" else (
            UsageMutation(operation.intent.operation_ref + ".unit", 0, None,
                          operation_holder(operation.request,
                                           operation.intent.operation_ref),
                          unit, ("use",), "active"),)
        return PreparationObservation(
            step.step_id, provider, step.input_digest,
            step.recovery_correlation,
            _owner_source(provider, step.step_id + "-receipt"),
            {"unitRef": unit}, holds)

    def inspect(self, operation, steps):
        provider = operation.intent.steps[0].pinned_provider_ref
        unit = steps[0].evidence["preparedUnit"]["unitRef"]
        return NodePublicationEvidence(
            provider,
            {"nodeRef": operation.intent.node_ref,
             "operationRef": operation.intent.operation_ref,
             "profileSnapshotRef": operation.intent.profile_snapshot_ref,
             "preparationContextRef": operation.intent.context_ref,
             "harnessProviderRef": provider,
             "harnessDefinitionRef": dict(RUNTIME_DEFINITION),
             "harnessUnitRef": unit,
             "configurationTargetRef": _owner_source(provider, "target"),
             "nativeSessionRefs": ()},
            tuple({"stepId": row.intent.step_id,
                   "providerRef": row.intent.pinned_provider_ref,
                   "inputDigest": row.intent.input_digest,
                   "recoveryCorrelation": row.intent.recovery_correlation,
                   "evidenceRef": row.evidence["evidenceRef"]} for row in steps),
            (_owner_source(provider, "access"),))


class BAdmittedConsumerPort:
    """Consumer admission evidence served by B's REAL Registry discovery.

    C freeze §1: the expected consumer pin is an admission-side copy; the
    owner_activation is taken from B's AdmittedConfigurationProviderMetadata
    (named trust source). consumer_id/consumer_version remain the controlled
    host declaration — B's frozen metadata carries owner activation only and
    no consumer-id registry (documented boundary, not a protocol extension).
    The port returns None for any identity it does not admit.
    """

    def __init__(self, environment, definition_ref, consumer_id, consumer_version):
        self._environment = environment
        self._definition_ref = definition_ref
        self._consumer_id = consumer_id
        self._consumer_version = consumer_version
        self.lookups = []

    def admitted_consumer_pin(self, consumer_id, consumer_version):
        self.lookups.append((consumer_id, consumer_version))
        if (consumer_id, consumer_version) != (self._consumer_id,
                                               self._consumer_version):
            return None
        admitted = self._environment.agent_configuration_contribution(
            self._definition_ref)
        return MaterialConsumerPin(consumer_id, consumer_version,
                                   admitted.owner_activation)


# --------------------------------------------------------------------------
# Small builders
# --------------------------------------------------------------------------

def _material_descriptor(resource_ref):
    return ResourceMaterialDescriptor(
        resource_ref, "fixture.material", "schema/1", "sha256:" + "1" * 64,
        MaterialLifetime.COPY_COMPLETE, MaterialAccessMode.READ_ONLY,
        MaterialEvidenceRef(ENV, "fixture-provenance", "1"),
        MaterialEvidenceRef(ENV, "fixture-description", "1"))


def _make_material_request(resource_ref, pin, target, descriptor, *,
                           operation_ref, step_id):
    facts = {"resourceRef": resource_ref.to_dict(), "providerPin": pin.to_dict(),
             "target": target.to_dict(),
             "descriptorDigest": descriptor.descriptor_digest}
    input_digest = hashlib.sha256(safe_json(facts).encode("utf-8")).hexdigest()
    correlation = MaterialCorrelation(
        operation_ref, step_id, "recovery-%s-%s" % (operation_ref, step_id),
        input_digest)
    return MaterialRequest(resource_ref, pin, target,
                           descriptor.descriptor_digest, correlation)


def _acquisition_evidence(receipt):
    return {
        "immutableMaterialRef": receipt.immutable_material_ref.to_dict(),
        "contentDigest": receipt.content_digest,
        "evidenceRef": receipt.evidence_ref.to_dict(),
        "provenanceRef": receipt.provenance_ref.to_dict(),
    }


def _plain(value):
    return json.loads(safe_json({"v": value}))["v"]


def _effect_plan(root, context_ref, *, material_refs, pin=None,
                 declaration_digest=DECLARATION_DIGEST):
    steps = (EffectStep("configure-unit", "input-configure",
                        material_refs[0] if material_refs else None,
                        ("prepare",), "correlation-configure-unit"),)
    return PreparationEffectPlan(
        plan_id="effects-bca",
        declaration_digest=declaration_digest,
        provider_pin=(pin if pin is not None else
                      json.loads(safe_json(root.steps[0].pinned_provider_ref))),
        material_refs=tuple(material_refs),
        target=json.loads(safe_json(root.node_ref)),
        scope=json.loads(safe_json(root.profile_snapshot_ref)),
        before_revision=(
            context_ref["contextSources"]["installationRef"]["sourceRevision"]),
        directory_binding_ref=context_ref["directoryBindingRef"],
        management_epoch=root.management_epoch,
        steps=steps,
    )


def _original_facts(root, context_ref, *, verified_materials):
    return dict(
        target=json.loads(safe_json(root.node_ref)),
        scope=json.loads(safe_json(root.profile_snapshot_ref)),
        before_revision=(
            context_ref["contextSources"]["installationRef"]["sourceRevision"]),
        directory_binding_ref=context_ref["directoryBindingRef"],
        management_epoch=root.management_epoch,
        pinned_provider_ref=json.loads(
            safe_json(root.steps[0].pinned_provider_ref)),
        step_correlations={step.step_id: step.recovery_correlation
                           for step in root.steps},
        declaration_digest=DECLARATION_DIGEST,
        approved_action_ids=("configure-unit",),
        verified_materials=verified_materials,
    )


def _hold_rows(store, request_key, operation_ref, step_id):
    holder = operation_holder(request_key, operation_ref)
    rows = store.read_usages(ENV, holder)
    prefix = "%s.material.%s" % (operation_ref, step_id)
    return {row["usageId"]: row for row in rows
            if row["usageId"].startswith(prefix)}


def _assert_holds_active(store):
    holds = _hold_rows(store, ACQUIRE_REQUEST_KEY, ACQUIRE_OP, ACQUIRE_STEP)
    assert len(holds) == 2
    for row in holds.values():
        assert row["state"] == "active"


# --------------------------------------------------------------------------
# The longitudinal chain
# --------------------------------------------------------------------------

def test_bca_longitudinal_chain(tmp_path):
    store = SqliteStorePort(tmp_path / "bca-longitudinal.sqlite")
    policy = Policy()
    env = Environment(
        ENV, store=store, policy=policy, principal_scope=PRINCIPAL,
        fingerprint_port=ProtectedFingerprintHmac(
            {"bca": b"bca-longitudinal-fixture"}, active_key_id="bca"))
    issuer = None
    try:
        # ---------------------------------------------------------- fixtures
        authority = Authority()
        current = CurrentState()
        issuer = InvocationIssuer(store, authority, current, clock=lambda: 50)

        runtime_host = RuntimeHostProvider()
        config_host = ConfigurationHostProvider()

        material_capability = MaterialCapability(
            AGENT_MATERIAL_CONTRACT_VERSION, ("copyComplete",), True, "both")
        material_provider = ControlledMaterialProvider(
            MATERIAL_PROVIDER_ID, material_capability)

        context_owner = ContextOwner()
        context_owner.directory = DirectoryBindingRef(
            ENV, "bca-directory", 1, "sha256:" + "d" * 64)
        directory = context_owner.directory
        owner = Owner()

        # ---------------- B: Registry admission of the configuration contribution
        env.install(InstallationRecord("contracts.owner", "a" * 64))
        env.enable("contracts.owner")
        env.activate("contracts.owner", CoreContributionSet(contracts=(AlphaContract,)))

        env.install(InstallationRecord("fixture.plugin", "b" * 64))
        env.enable("fixture.plugin")
        stage = env.stage_activation(
            "fixture.plugin",
            AgentContributionSet(
                agent_runtime_providers=(runtime_host, config_host)))
        # Staged contributions are not discoverable until commit (B gate).
        services = agent_services(env)
        assert services.providers.configuration_list() == ()
        assert env.agent_configuration_contributions() == ()
        receipt = stage.commit()

        env.install(InstallationRecord("owner.material", "e" * 64))
        env.enable("owner.material")
        material_activation = env.activate(
            "owner.material",
            CoreContributionSet(resource_providers=(material_provider,))).activation

        assert env.registry_snapshot.agent_runtime_provider_ids == (
            CONFIG_PROVIDER_ID, RUNTIME_PROVIDER_ID)
        # B s1: the route mount rode the existing contribution channel.
        assert env._registry.agent_runtime_configuration_routes(
            CONFIG_PROVIDER_ID) is not None
        assert env._registry.agent_runtime_configuration_routes(
            RUNTIME_PROVIDER_ID) is None

        # ---------------- B: discovery through the real admitted metadata
        runtime_definition = dict(runtime_host.descriptor.definition_ref)
        admitted = env.agent_configuration_contribution(runtime_definition)
        assert type(admitted) is AdmittedConfigurationProviderMetadata
        assert admitted.owner_activation == receipt.activation
        assert admitted.descriptor.provider_id == CONFIG_PROVIDER_ID
        assert admitted.descriptor.contract_version == CONFIGURATION_PROVIDER_VERSION
        assert admitted.descriptor.implementation_digest == CONFIG_IMPLEMENTATION
        assert admitted.descriptor.supported_methods == (
            "describe", "validate", "extract_references")
        # B s2 association: the route acknowledged the RUNTIME host's exact
        # definition; assess_configuration is declared, so the definition is
        # recognized (declaration is not capability, but the gate is a gate).
        assert admitted.recognized_definitions == (sealed_mapping(dict(RUNTIME_DEFINITION)),)
        runtime_admitted = env.agent_runtime_contribution(runtime_definition)
        runtime_ref = runtime_admitted.provider_ref
        # The thin projection exposes the same verified subset.
        listed = services.providers.configuration_list()
        assert len(listed) == 1
        assert listed[0]["recognizedDefinitions"] == [dict(RUNTIME_DEFINITION)]
        described = services.providers.configuration_describe(runtime_definition)
        assert described["recognizedDefinitions"] == [dict(RUNTIME_DEFINITION)]
        assert described["providerRef"]["providerId"] == CONFIG_PROVIDER_ID
        # Missing/unacknowledged definitions are refused, never invented.
        with pytest.raises(AdmissionRefusedError):
            env.agent_configuration_contribution(
                {"environmentNamespace": ENV, "definitionId": "nobody",
                 "revision": "1"})

        # ---------------- 020: reference extraction validated against B facts
        config_pin = ConfigurationProviderPin(
            admitted.descriptor.provider_id,
            admitted.descriptor.contract_version,
            admitted.descriptor.implementation_digest,
            admitted.owner_activation)
        resource_ref = ResourceRef(ENV, MATERIAL_PROVIDER_ID, CONTRACT_ID,
                                   "resource-bca", "r1")
        extraction = ConfigurationReferenceExtraction(
            DECLARATION_ID, CONFIGURATION_KIND, CONFIGURATION_SCHEMA, "value",
            DECLARATION_DIGEST, dict(RUNTIME_DEFINITION), config_pin,
            "complete",
            (ConfigurationReference("material.profile", resource_ref,
                                    "profile-material"),),
            None)
        validated = validate_reference_extraction(
            admitted.descriptor, extraction,
            expected_pin=config_pin,
            expected_declaration={
                "declarationId": DECLARATION_ID,
                "configurationKind": admitted.descriptor.routes[0].configuration_kind,
                "schemaVersion": admitted.descriptor.routes[0].schema_version,
                "action": "value",
                "declarationDigest": DECLARATION_DIGEST,
                "definitionRef": dict(RUNTIME_DEFINITION)})
        assert validated.to_dict() == extraction.to_dict()
        # Longitudinal continuity: the extraction reference pins the exact
        # material ResourceRef that C hands off below.
        assert validated.references[0].resource_ref == resource_ref
        # Tampered identities are typed refusals, not silent acceptances.
        foreign_pin = ConfigurationProviderPin(
            CONFIG_PROVIDER_ID, CONFIGURATION_PROVIDER_VERSION,
            CONFIG_IMPLEMENTATION, ActivationRef(ENV, "fixture.plugin", 99))
        with pytest.raises(ConfigurationContractError):
            validate_reference_extraction(
                admitted.descriptor, extraction, expected_pin=foreign_pin,
                expected_declaration={
                    "declarationId": DECLARATION_ID,
                    "configurationKind": CONFIGURATION_KIND,
                    "schemaVersion": CONFIGURATION_SCHEMA, "action": "value",
                    "declarationDigest": DECLARATION_DIGEST,
                    "definitionRef": dict(RUNTIME_DEFINITION)})
        foreign_extraction = ConfigurationReferenceExtraction(
            DECLARATION_ID, CONFIGURATION_KIND, CONFIGURATION_SCHEMA, "value",
            DECLARATION_DIGEST,
            {"environmentNamespace": ENV, "definitionId": "nobody",
             "revision": "1"},
            config_pin, "complete", (), None)
        with pytest.raises(ConfigurationContractError):
            validate_reference_extraction(
                admitted.descriptor, foreign_extraction,
                expected_pin=config_pin,
                expected_declaration={
                    "declarationId": DECLARATION_ID,
                    "configurationKind": CONFIGURATION_KIND,
                    "schemaVersion": CONFIGURATION_SCHEMA, "action": "value",
                    "declarationDigest": DECLARATION_DIGEST,
                    "definitionRef": dict(RUNTIME_DEFINITION)})

        # ---------------- C: material identity, consumer pin from B metadata
        material_descriptor = _material_descriptor(resource_ref)
        material_pin = MaterialProviderPin(MATERIAL_PROVIDER_ID, "1.0",
                                           material_activation)
        target = MaterialUseTarget(
            ParticipantInstanceRef(ENV, "planned-node", 1), directory,
            MATERIAL_EPOCH, "profile-material")
        # C §1: the consumer pin is an admission-side copy from B's admitted
        # configuration metadata (owner_activation), never self-reported.
        consumer_pin = MaterialConsumerPin(
            CONSUMER_ID, CONSUMER_VERSION, admitted.owner_activation)
        assert consumer_pin.owner_activation == receipt.activation
        consumer_port = BAdmittedConsumerPort(
            env, dict(runtime_host.descriptor.definition_ref),
            CONSUMER_ID, CONSUMER_VERSION)

        material_operations = MaterialOperations(env, invocation_issuer=issuer)
        consumption = MaterialConsumption(
            env, invocation_issuer=issuer, admitted_consumer=consumer_port)
        material_provider.descriptor = material_descriptor
        material_provider.material_provider = material_provider_ref(material_pin)
        material_provider.material_target = None  # set per request below
        material_provider.verifier = issuer.verifier()
        current.runtime_provider_ref = runtime_ref
        current.material_provider_ref = material_provider_ref(material_pin)

        # ---------------- C: K1 acquisition through the real operation store
        acquire_request = _make_material_request(
            resource_ref, material_pin, target, material_descriptor,
            operation_ref=ACQUIRE_OP, step_id=ACQUIRE_STEP)
        material_provider.material_target = material_invocation_target(
            acquire_request)
        acquire_context = {
            "environmentNamespace": ENV,
            "directoryBindingRef": directory.to_dict(),
            "materialRequests": {
                ACQUIRE_STEP: material_operation_facts(acquire_request,
                                                       material_descriptor),
            },
            "invocationBindings": {
                ACQUIRE_STEP: {"action": "acquire",
                               "targetRef": material_invocation_target(
                                   acquire_request),
                               "delegationRef": None, "cleanup": False},
            },
        }
        acquire_intent = OperationIntent(
            ACQUIRE_OP, "bca-material-fixture", None, acquire_context,
            (StepIntent(ACQUIRE_STEP, material_provider_ref(material_pin),
                        acquire_request.input_digest,
                        acquire_request.correlation.recovery_correlation,
                        management_epoch=MATERIAL_EPOCH),),
            {"environmentNamespace": ENV, "instanceId": "planned-node",
             "generation": 1},
            MATERIAL_EPOCH)
        store.reserve_operation(
            ACQUIRE_REQUEST_KEY, OUTER_DIGEST, acquire_intent,
            usages=material_reservation_usages(ACQUIRE_REQUEST_KEY,
                                               acquire_request))
        acquire_step = material_operations.acquire(
            ACQUIRE_REQUEST_KEY, OUTER_DIGEST, ACQUIRE_STEP)
        assert acquire_step.outcome == "concluded"
        receipt_row = acquire_step.evidence["materialResult"]["receipt"]
        assert receipt_row["contentDigest"] == material_descriptor.content_digest
        _assert_holds_active(store)
        assert material_provider.c1_calls == {"acquire": 0, "release": 0,
                                              "reconcile": 0}

        # ---------------- C: consumer-pin refusals through the B-backed port
        # A self-reported (different-generation) pin is refused before any
        # claim or dispatch: the port's admission-side copy is gen-1.
        bad_pin = MaterialConsumerPin(
            CONSUMER_ID, CONSUMER_VERSION,
            ActivationRef(ENV, "fixture.plugin", 99))
        bad_read_request = MaterialRequest(
            resource_ref, material_pin, target,
            material_descriptor.descriptor_digest,
            MaterialCorrelation(BAD_READ_OP, READ_STEP,
                                "recovery-%s-%s" % (BAD_READ_OP, READ_STEP),
                                acquire_request.input_digest))
        bad_context = {
            "environmentNamespace": ENV,
            "directoryBindingRef": directory.to_dict(),
            "materialReads": {
                READ_STEP: {
                    "contractVersion": AGENT_MATERIAL_CONSUMPTION_CONTRACT_VERSION,
                    "request": bad_read_request.to_dict(),
                    "consumerPin": bad_pin.to_dict(),
                    "acquisitionEvidence": _acquisition_evidence(
                        material_provider.acquisition_receipt),
                    "originalStepRef": {
                        "environmentNamespace": ENV,
                        "principalScope": PRINCIPAL,
                        "requestId": ACQUIRE_REQUEST_KEY.request_id,
                        "operationDigest": OUTER_DIGEST,
                        "stepId": ACQUIRE_STEP,
                    },
                },
            },
            "invocationBindings": {
                READ_STEP: {"action": READ_ACTION,
                            "targetRef": material_invocation_target(
                                bad_read_request),
                            "delegationRef": None, "cleanup": False},
            },
        }
        bad_intent = OperationIntent(
            BAD_READ_OP, "bca-material-fixture", None, bad_context,
            (StepIntent(READ_STEP, material_provider_ref(material_pin),
                        bad_read_request.input_digest,
                        bad_read_request.correlation.recovery_correlation,
                        management_epoch=MATERIAL_EPOCH),),
            {"environmentNamespace": ENV, "instanceId": "planned-node",
             "generation": 1},
            MATERIAL_EPOCH)
        store.reserve_operation(BAD_READ_REQUEST_KEY, BAD_READ_DIGEST,
                                bad_intent)
        with pytest.raises(AdmissionRefusedError):
            consumption.read(BAD_READ_REQUEST_KEY, BAD_READ_DIGEST, READ_STEP)
        assert store.read_operation_step(BAD_READ_REQUEST_KEY,
                                         READ_STEP) is None
        assert material_provider.read_calls == 0
        _assert_holds_active(store)

        # ---------------- C: K2 authorized read with the B-admitted pin
        read_request = MaterialRequest(
            resource_ref, material_pin, target,
            material_descriptor.descriptor_digest,
            MaterialCorrelation(READ_OP, READ_STEP,
                                "recovery-%s-%s" % (READ_OP, READ_STEP),
                                acquire_request.input_digest))
        read_context = {
            "environmentNamespace": ENV,
            "directoryBindingRef": directory.to_dict(),
            "materialReads": {
                READ_STEP: {
                    "contractVersion": AGENT_MATERIAL_CONSUMPTION_CONTRACT_VERSION,
                    "request": read_request.to_dict(),
                    "consumerPin": consumer_pin.to_dict(),
                    "acquisitionEvidence": _acquisition_evidence(
                        material_provider.acquisition_receipt),
                    "originalStepRef": {
                        "environmentNamespace": ENV,
                        "principalScope": PRINCIPAL,
                        "requestId": ACQUIRE_REQUEST_KEY.request_id,
                        "operationDigest": OUTER_DIGEST,
                        "stepId": ACQUIRE_STEP,
                    },
                },
            },
            "invocationBindings": {
                READ_STEP: {"action": READ_ACTION,
                            "targetRef": material_invocation_target(
                                read_request),
                            "delegationRef": None, "cleanup": False},
            },
        }
        read_intent = OperationIntent(
            READ_OP, "bca-material-fixture", None, read_context,
            (StepIntent(READ_STEP, material_provider_ref(material_pin),
                        read_request.input_digest,
                        read_request.correlation.recovery_correlation,
                        management_epoch=MATERIAL_EPOCH),),
            {"environmentNamespace": ENV, "instanceId": "planned-node",
             "generation": 1},
            MATERIAL_EPOCH)
        store.reserve_operation(READ_REQUEST_KEY, READ_DIGEST, read_intent)
        read_step = consumption.read(READ_REQUEST_KEY, READ_DIGEST, READ_STEP)
        assert read_step.outcome == "concluded"
        read_result = read_step.evidence["materialReadResult"]
        assert read_result["outcome"] == MaterialOutcome.SUCCESS.value
        original_receipt = material_provider.acquisition_receipt
        assert read_result["immutableMaterialRef"] == (
            original_receipt.immutable_material_ref.to_dict())
        assert read_result["contentDigest"] == original_receipt.content_digest
        assert read_result["evidenceRef"] == (
            original_receipt.evidence_ref.to_dict())
        # C §3: read success is pointer-only — no lease, no body.
        assert "leaseRef" not in read_result
        assert CANARY.encode() not in safe_json(read_result).encode()
        assert material_provider.read_calls == 1
        assert material_provider.content_reads == 1
        assert material_provider.query_calls == 0
        assert (CONSUMER_ID, CONSUMER_VERSION) in consumer_port.lookups
        # Replay returns the durable record without a second dispatch.
        replay = consumption.read(READ_REQUEST_KEY, READ_DIGEST, READ_STEP)
        assert replay == read_step
        assert material_provider.read_calls == 1
        _assert_holds_active(store)

        # ---------------- C→A: the handoff-verified pointer set
        # A freeze s4: material_refs legality = membership in the C
        # handoff-verified set. The set is read back from the DURABLE C read
        # evidence (pointer pair immutableMaterialRef+contentDigest), not
        # asserted by the caller.
        verified_materials = (
            {"immutableMaterialRef": read_result["immutableMaterialRef"],
             "contentDigest": read_result["contentDigest"]},
        )
        assert set(verified_materials[0]) == {"immutableMaterialRef",
                                              "contentDigest"}

        # ---------------- A: staged preparation on the B-acknowledged runtime
        runtime_host.issuer = issuer
        catalog = ProfileCatalog(env)
        entry = catalog.create(
            profile_id="bca-profile", display_name="BCA profile",
            manifest={"harnessDefinitionRef": dict(runtime_definition),
                      "schemaVersion": "1", "declarations": []},
            request=RequestKey(ENV, PRINCIPAL, "bca-create-profile"))
        nodes = NodePublication(env, evidence_port=owner)
        coordinator = AgentAssembly(
            env, catalog, nodes, invocation_issuer=issuer,
            context_port=context_owner, observation_port=owner)
        staged_api = coordinator.staged_assembly()
        record = staged_api.reserve(PREPARE_REQUEST,
                                    entry.current_manifest_ref, {}, {})
        root = record.root_intent
        # B→A seam: A's pinned provider ref is exactly the admitted runtime
        # provider whose definition B's route acknowledged (s2 association).
        assert safe_json(root.steps[0].pinned_provider_ref) == safe_json(
            runtime_ref)
        assert runtime_host.descriptor.definition_ref["definitionId"] == (
            RUNTIME_DEFINITION["definitionId"])
        operation = staged_api.run_root(PREPARE_REQUEST)
        assert operation.status == "running"
        assert runtime_host.calls == ["prepare", "start"]
        for step_id in ("prepare", "start"):
            row = store.read_operation_step(PREPARE_REQUEST, step_id)
            assert row is not None and row.outcome == "concluded"
        context_ref = json.loads(safe_json(operation.intent.context_ref))

        # ---------------- A: five-item verification against original facts
        plan = _effect_plan(root, context_ref,
                            material_refs=verified_materials)
        # Cross-lane: the effect declaration digest IS the B extraction's
        # validated declaration digest.
        assert plan.declaration_digest == validated.declaration_digest
        facts = _original_facts(root, context_ref,
                                verified_materials=verified_materials)
        fixed_scope = verify_preparation_effect(plan, **facts)
        assert fixed_scope.action_ids == ("configure-unit",)
        assert fixed_scope.input_digests == ("input-configure",)
        assert fixed_scope.recovery_correlations == (
            "correlation-configure-unit",)
        assert fixed_scope.material_refs == verified_materials
        assert fixed_scope.target == plan.target
        assert fixed_scope.management_epoch == root.management_epoch
        recomputed = _plain(fixed_scope.to_dict())
        del recomputed["effectDigest"]
        assert fixed_scope.effect_digest == hashlib.sha256(
            safe_json(recomputed).encode("utf-8")).hexdigest()

        # ---------------- A negatives before seal (typed, state-untouching)
        before = store.read_staged_operation(PREPARE_REQUEST)
        # s4/§6.2: absent C verification set keeps the occupation unknown —
        # nothing is appended, sealed or called.
        with pytest.raises(UnknownResultError):
            staged_api.seal(PREPARE_REQUEST, plan, verified_materials=None,
                            declaration_digest=DECLARATION_DIGEST,
                            approved_action_ids=("configure-unit",))
        assert store.read_staged_operation(PREPARE_REQUEST) == before
        assert store.read_operation_step(PREPARE_REQUEST,
                                         "configure-unit") is None
        with pytest.raises(UnknownResultError):
            staged_api.publish(PREPARE_REQUEST)
        # A material outside the C-verified set is refused (s1 item 3).
        foreign_materials = (
            {"immutableMaterialRef": {"environmentNamespace": ENV,
                                      "resourceId": "elsewhere"},
             "contentDigest": "sha256:" + "e" * 64},)
        with pytest.raises(IdentityMismatchError):
            staged_api.seal(PREPARE_REQUEST, plan,
                            verified_materials=foreign_materials,
                            declaration_digest=DECLARATION_DIGEST,
                            approved_action_ids=("configure-unit",))
        assert store.read_staged_operation(PREPARE_REQUEST) == before
        # A changed provider pin is refused (s1 item 2 / s6.1).
        changed_pin = json.loads(
            safe_json(root.steps[0].pinned_provider_ref))
        changed_pin["generation"] = 2
        tampered_plan = _effect_plan(root, context_ref,
                                     material_refs=verified_materials,
                                     pin=changed_pin)
        with pytest.raises(IdentityMismatchError):
            verify_preparation_effect(tampered_plan,
                                      **_original_facts(
                                          root, context_ref,
                                          verified_materials=verified_materials))
        # A changed declaration digest is refused (s1 item 4); the digest is
        # the B extraction's validated digest.
        with pytest.raises(IdentityMismatchError):
            staged_api.seal(PREPARE_REQUEST, plan,
                            verified_materials=verified_materials,
                            declaration_digest="sha256:" + "x" * 64,
                            approved_action_ids=("configure-unit",))
        assert store.read_staged_operation(PREPARE_REQUEST) == before
        # Unknown verification facts keep the occupation (s1 unknown rule).
        unknown_facts = _original_facts(root, context_ref,
                                        verified_materials=verified_materials)
        unknown_facts["target"] = None
        with pytest.raises(UnknownResultError):
            verify_preparation_effect(plan, **unknown_facts)

        # ---------------- A: staged append + seal with the C-verified set
        sealed = staged_api.seal(
            PREPARE_REQUEST, plan, verified_materials=verified_materials,
            declaration_digest=DECLARATION_DIGEST,
            approved_action_ids=("configure-unit",))
        assert sealed.sealed is True
        phase = sealed.phase
        assert [step.step_id for step in phase.steps] == ["configure-unit"]
        assert phase.steps[0].prerequisite_steps == ("prepare",)
        # The phase pins the ORIGINAL provider reference (B-acknowledged).
        assert safe_json(phase.steps[0].pinned_provider_ref) == safe_json(
            root.steps[0].pinned_provider_ref)
        phase_facts = phase.context_facts
        assert set(phase_facts) == {"effectDigest", "fixedEffectScope"}
        assert phase_facts["effectDigest"] == fixed_scope.effect_digest
        assert re.fullmatch(r"[0-9a-f]{64}", phase_facts["effectDigest"])
        fixed = phase_facts["fixedEffectScope"]
        assert tuple(fixed["actionIds"]) == ("configure-unit",)
        # Phase facts are stored deep-frozen: sequences are tuples.
        assert tuple(fixed["materialRefs"]) == tuple(verified_materials)
        assert fixed["beforeRevision"] == (
            context_ref["contextSources"]["installationRef"]["sourceRevision"])
        # Gate 5: the core never learns brands — every serialized payload.
        for payload in (plan.to_dict(), fixed_scope.to_dict(), phase_facts):
            _scan_brands(payload)
        # Root step records survived the seal untouched.
        for step_id in ("prepare", "start"):
            row = store.read_operation_step(PREPARE_REQUEST, step_id)
            assert row is not None and row.outcome == "concluded"

        # ---------------- Registered NOT_RUN boundaries stay honest
        # Effect-step native execution and node publication of the expanded
        # recipe are not claimed: publish fails closed on the unexecuted
        # effect step (A freeze s6 PARTIAL; real Harness is NOT_RUN).
        with pytest.raises(UnknownResultError):
            staged_api.publish(PREPARE_REQUEST)
        assert store.read_operation(PREPARE_REQUEST).status == "running"
        # The C acquisition occupation is retained end-to-end: read success
        # is not consumption and nothing was released.
        _assert_holds_active(store)
        assert material_provider.content_reads == 1
        assert material_provider.release_calls == 0
        assert material_provider.c1_calls == {"acquire": 0, "release": 0,
                                              "reconcile": 0}
    finally:
        if issuer is not None:
            issuer.close()
        env.close()
        store.close()
