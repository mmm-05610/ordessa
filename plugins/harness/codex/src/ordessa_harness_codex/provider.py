"""Codex AgentUnit ownership, using the existing deployment-owned UnitRecords.

No registries, daemon, database, or current-config cache lives in this package.
Native channels are live owned handles, not durable truth. Deployment binds
projection/evidence/authorization ports to its original journal and core issuer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import stat
import threading
from typing import Mapping, Protocol

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping
from ordessa_units.public import (
    RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION,
    ConfigurationDescription, ConfigurationSnapshot, ConfigurationUnsupported,
    ConfigurationChangeRequest, ConfigurationChangeResult, ConfigurationItemResult, ConfigurationRevisionConflict,
    UnitInspection,
    PURE_READ_VERSION, OwnerReadContext, OwnerProposalInput,
    OwnerConfigurationOfferBatch, OwnerProposalAssessment,
    ConfigurationContractError, ProfileValidationError,
)
from ordessa_harness_codex.client import PROTOCOL
from .lease import CodexConnectionLeasePort


class CodexProviderRefused(RuntimeError):
    code = "CODEX_PROVIDER_REFUSED"


class CodexCapabilityUnsupported(ConfigurationUnsupported):
    pass


class UnitProjectionPort(Protocol):
    """Trusted read/evidence projection from the SAME original UnitRecords."""
    def verify_preparation(self, plan, invocation_facts): ...
    def revalidate_start(self, unit, invocation_context): ...
    def revalidate_configuration(self, unit, invocation_context): ...
    def read_unit(self, unit_ref): ...
    def read_session(self, unit_ref): ...
    def publication_facts(self, unit_ref): ...
    def publish_channel(self, unit, client, native_evidence): ...
    def query_creation(self, correlation, verified_query_facts): ...


class ChannelFactoryPort(Protocol):
    """Open only the pinned caller-approved installation in an isolated root.

    The factory installs managed stdin fencing before initialize/thread/start.
    It must never inherit user login/config, choose a fallback, or create turns.
    """
    def open(self, private_root_facts, verified_start_facts): ...


class ConnectionLeasePort(Protocol):
    """Bind the native connection behind a per-write authority cut.

    The returned entry preserves the native payload and denies ALL writes after
    revoke/expiry/drain/old activation. Disconnect does not stop the unit. Raw
    client/channel handles must never be exposed to consumers.
    """
    def bind(self, unit_ref, authorized_lease, client, *, native_session_id): ...


class ConfigurationEvidencePort(Protocol):
    """Same owner as UnitRecords.configuration_evidence, never an actual cache.

    capture persists sanitized original RPC receipt+readback evidence and item
    outcomes in the owner's evidence store. read reconstructs only that original
    receipt's ConfigurationChangeResult, including scoped evidence references.
    """
    def verify_configuration(self, unit, identity, native_request_id, native_request_digest, evidence): ...
    def capture_configuration(self, unit, invocation_facts, native_request, native_receipt,
                              before_readback, after_readback, result): ...
    def read_configuration_result(self, unit, attempt): ...


@dataclass(frozen=True)
class PreparedManagedTurn:
    """Original client-local frame plus its owner-derived correlation."""
    unit_ref: Mapping
    client: object
    frame: object
    binding: Mapping


DEFAULTS_KIND = "codex.defaults"
DEFAULTS_SCHEMA = "0.157.1"
DEFAULT_FIELDS = frozenset({"model", "model_reasoning_effort"})
EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh"})


def _now():
    return datetime.now(timezone.utc).isoformat()


def _plain(value):
    return json.loads(safe_json(value))


class CodexRuntimeProvider:
    def __init__(self, *, definition_ref, implementation_digest, unit_records=None,
                 projection=None, verifier=None, channel_factory=None, lease_port=None, configuration_evidence=None,
                 termination_evidence=None):
        self.records, self.projection, self.verifier = unit_records, projection, verifier
        self.channel_factory, self.lease_port = channel_factory, lease_port
        self.configuration_evidence = configuration_evidence
        self.termination_evidence = termination_evidence
        self._configuration_waiters = {}  # live original tickets/receipts only; no cold truth or replay authority
        self._channels = {}  # live process handles; never used as persistent recovery proof
        self._lock = threading.RLock()
        methods = ["describe_definition", "inspect_installation", "assess_configuration", "plan_preparation",
                   "describe_configuration_offers", "assess_configuration_proposal"]
        if records_ready(unit_records, projection, verifier):
            methods += ["prepare", "inspect_unit", "describe_configuration"]
            if callable(getattr(channel_factory, "open", None)):
                methods += ["start", "inspect_configuration", "describe_access"]
                if (callable(getattr(channel_factory, "record", None))
                        and termination_ready(unit_records, termination_evidence)):
                    methods += ["stop", "release"]
                if configuration_ready(unit_records, projection, configuration_evidence):
                    methods += ["apply_configuration", "query_change"]
                # The lease owns only original-Session metadata reads. Native
                # mutations retain the managed reservation paths above.
                if type(lease_port) is CodexConnectionLeasePort:
                    methods += ["connect"]
            if callable(getattr(projection, "query_creation", None)):
                methods += ["query_step"]
        self.descriptor = RuntimeProviderDescriptor("codex", RUNTIME_PROVIDER_VERSION,
                    definition_ref, implementation_digest, tuple(methods), PURE_READ_VERSION)

    def _pure_read_context(self, definition_ref, context):
        """Validate the core's typed read capability without consuming invocation."""
        if not isinstance(context, OwnerReadContext):
            raise CodexProviderRefused("typed owner read context required")
        provider = context.provider_ref
        namespace = self.descriptor.definition_ref["environmentNamespace"]
        if (context.contract_version != PURE_READ_VERSION or context.environment_namespace != namespace
                or not _same_reference(definition_ref, self.descriptor.definition_ref)
                or provider.get("environmentNamespace") != namespace or provider.get("providerId") != "codex"
                or provider.get("contractVersion") != RUNTIME_PROVIDER_VERSION
                or provider.get("implementationDigest") != self.descriptor.implementation_digest
                or type(provider.get("generation")) is not int or provider["generation"] < 1):
            raise CodexProviderRefused("pure read owner identity differs")
        activation = provider.get("ownerActivationRef")
        if (not isinstance(activation, Mapping) or activation.get("environmentNamespace") != namespace
                or type(activation.get("generation")) is not int or activation["generation"] != provider["generation"]
                or not isinstance(activation.get("pluginId"), str) or not activation["pluginId"]):
            raise CodexProviderRefused("pure read owner activation differs")
        return namespace

    def describe_configuration_offers(self, definition_ref, context):
        namespace = self._pure_read_context(definition_ref, context)
        return OwnerConfigurationOfferBatch(context.provider_ref, self.descriptor.definition_ref,
            self.descriptor.definition_ref["revision"], self.descriptor.implementation_digest,
            (_defaults_description("unknown"),), False, PURE_READ_VERSION,
            ("installation", "runtimeReady", "unit", "application", "effect", "credentials"),
            ({"environmentNamespace": namespace, "evidenceId": "codex.defaults.schema:" + DEFAULTS_SCHEMA,
              "descriptorDigest": self.descriptor.implementation_digest, "durability": "computed_nonpersistent"},))

    def assess_configuration_proposal(self, proposal, context):
        if not isinstance(proposal, OwnerProposalInput):
            raise CodexProviderRefused("typed owner proposal required")
        namespace = self._pure_read_context(proposal.definition_ref, context)
        if (not _same_reference(proposal.provider_ref, context.provider_ref)
                or proposal.descriptor_revision != self.descriptor.definition_ref["revision"]):
            raise CodexProviderRefused("pure read input owner or descriptor differs")
        versions = {"descriptor": proposal.descriptor_revision}
        for ref in proposal.source_refs:
            version = ref.get("sourceRevision", ref.get("manifestRevision", ref.get("revision")))
            if (ref.get("environmentNamespace") != namespace or type(version) not in (str, int)
                    or (type(version) is int and version < 1)
                    or (type(version) is str and (not version or len(version) > 256 or any(ord(c) < 32 for c in version)))):
                raise CodexProviderRefused("pure read source version unavailable")
            versions[safe_json(ref)] = version
        evidence = {"environmentNamespace": namespace,
            "evidenceId": "codex.defaults.compile:" + proposal.input_digest,
            "inputDigest": proposal.input_digest, "version": DEFAULTS_SCHEMA,
            "durability": "computed_nonpersistent"}
        invalid = False; skipped = ()
        try:
            data = proposal.proposal_data
            if not isinstance(data, Mapping) or set(data) != {"declarations"} or not isinstance(data["declarations"], (tuple, list)):
                raise ConfigurationContractError("pure read declarations shape differs")
            change = ConfigurationChangeRequest(proposal.input_digest, proposal.descriptor_revision, tuple(data["declarations"]))
            _, _, skipped = self._compile_change(change)
        except (ConfigurationContractError, ProfileValidationError, CodexProviderRefused):
            invalid = True
        rows = []; must_known = False; must_unknown = False
        for obligation in proposal.required_obligations:
            known = obligation["checkerId"] == "codex.defaults.compile" and obligation["checkerVersion"] == DEFAULTS_SCHEMA
            must = obligation["requirement"] == "must"
            must_known = must_known or (must and known)
            must_unknown = must_unknown or (must and not known)
            rows.append({"obligationId": obligation["obligationId"],
                "status": ("failed" if invalid else "passed") if known else "unknown",
                "checkerId": obligation["checkerId"], "checkerVersion": obligation["checkerVersion"],
                "sourceVersions": versions, "evidenceRefs": (evidence,) if known else ()})
        status = "invalid" if invalid else "valid" if must_known and not must_unknown else "unverifiable"
        issues = ({"code": "codex_defaults_declarations_invalid"},) if invalid else ()
        if not invalid and (not must_known or must_unknown): issues += ({"code": "codex_defaults_semantics_unverified"},)
        if skipped: issues += ({"code": "codex_defaults_optional_declarations_skipped", "declarationIds": list(skipped)},)
        return OwnerProposalAssessment(proposal.input_digest, versions, status, issues, tuple(rows),
            "codex.defaults.declaration-compile/" + DEFAULTS_SCHEMA, (evidence,), PURE_READ_VERSION)

    def _supported(self, name):
        if name not in self.descriptor.supported_methods:
            raise CodexCapabilityUnsupported("Codex capability unavailable: " + name)

    @property
    def managed_turn_available(self):
        return getattr(self.records, "managed_turn_available", False) is True

    def _require_managed_turn(self):
        if not self.managed_turn_available:
            raise CodexCapabilityUnsupported("managed Codex turn records are unavailable")

    def describe_definition(self, definition_ref):
        if definition_ref != self.descriptor.definition_ref:
            raise CodexProviderRefused("definition identity differs")
        return {"familyId": "codex", "channel": "codex-app-server/1",
                "contractVersion": RUNTIME_PROVIDER_VERSION,
                "supportedMethods": list(self.descriptor.supported_methods),
                "nativeVersion": "0.157.1", "nativeVersionVerified": False,
                "ownership": "owned-process-and-thread", "recovery": "unsupported"}

    def inspect_installation(self, binding):
        # Discovery never executes the binary, reads login, or guesses a version.
        path = binding.get("executable") if isinstance(binding, Mapping) else None
        valid = False
        if isinstance(path, str) and os.path.isabs(path):
            try:
                valid = stat.S_ISREG(os.stat(path).st_mode) and os.access(path, os.X_OK)
            except OSError:
                pass
        return {"executable": path if valid else None, "installationPresent": valid,
                "runtimeReady": "unknown", "versionVerified": False,
                "reason": "execution-and-version-not-verified" if valid else "installation-missing"}

    def assess_configuration(self, manifest, installation, context):
        declarations = manifest.get("declarations", ()) if isinstance(manifest, Mapping) else ()
        required = [d["declarationId"] for d in declarations if d.get("requirement") == "required"]
        return {"accepted": installation.get("installationPresent") is True and not required,
                "unsupportedRequired": required,
                "optionalSkipped": [d["declarationId"] for d in declarations if d.get("requirement") == "optional"],
                "configurationGuarantee": "unavailable"}

    def plan_preparation(self, snapshot, context, correlation):
        if not isinstance(context, Mapping) or not isinstance(snapshot, Mapping):
            raise CodexProviderRefused("fixed snapshot and preparation context required")
        if snapshot.get("manifest", {}).get("declarations"):
            raise CodexCapabilityUnsupported("native preparation configuration requires resolved material integration")
        if not isinstance(context.get("privateRootFacts"), Mapping) or not context.get("privateRootFacts"):
            raise CodexProviderRefused("explicit isolated root facts required")
        return sealed_mapping({"profileSnapshot": _plain(snapshot), "context": _plain(context),
                               "correlation": _plain(correlation)})

    def _facts(self, context, action, unit=None):
        if self.verifier is None:
            raise CodexProviderRefused("invocation verifier absent")
        facts = context.facts
        provider = unit.facts["providerRef"] if unit else facts["providerRef"]
        target = unit.facts["nodeRef"] if unit else facts["targetRef"]
        if (provider.get("providerId") != "codex" or
                provider.get("implementationDigest") != self.descriptor.implementation_digest or
                provider.get("contractVersion") != RUNTIME_PROVIDER_VERSION):
            raise CodexProviderRefused("current admitted provider identity differs")
        verified = self.verifier.verify_and_consume(context, action, provider, target, facts["inputDigest"])
        if (verified.get("action") != action or verified.get("providerRef") != provider or
                verified.get("targetRef") != target or verified.get("inputDigest") != facts["inputDigest"]):
            raise CodexProviderRefused("verified invocation identity differs")
        return verified

    def prepare(self, plan, invocation_context):
        self._supported("prepare")
        # UnitRecords consumes exactly the original prepare claim itself.
        facts = invocation_context.facts
        provider = facts["providerRef"]
        if provider.get("providerId") != "codex" or provider.get("implementationDigest") != self.descriptor.implementation_digest:
            raise CodexProviderRefused("prepare provider differs")
        if plan.get("context", {}).get("nodeRef") != facts["targetRef"]:
            raise CodexProviderRefused("plan node binding differs")
        unit, created = self.records.reserve_unit(invocation_context, provider_ref=provider,
                        node_ref=facts["targetRef"], input_digest=facts["inputDigest"],
                        private_root_facts=self.projection.verify_preparation(plan, facts))
        public_ref = unit.public_ref
        if (not _complete_unit_reference(public_ref) or public_ref["unitId"] != unit.unit_ref
                or not _same_reference(public_ref["ownerProviderRef"], provider)
                or public_ref["environmentNamespace"] != provider["environmentNamespace"]):
            raise CodexProviderRefused("original prepared unit owner reference differs")
        return {"unitRef": public_ref, "created": created, "state": "notCreated"}

    def _unit(self, unit_ref):
        if not _complete_unit_reference(unit_ref):
            raise CodexProviderRefused("complete owner-bound unit reference required")
        # The projection must authorize and verify the original owner journal
        # read. A copied public reference never supplies read permission.
        unit = self.projection.read_unit(unit_ref)
        canonical = unit.public_ref
        provider = unit.facts["providerRef"]
        if (not _complete_unit_reference(canonical) or not _same_reference(canonical, unit_ref)
                or unit.unit_ref != canonical["unitId"]
                or not _same_reference(canonical["ownerProviderRef"], provider)
                or provider["environmentNamespace"] != canonical["environmentNamespace"]
                or provider.get("providerId") != "codex"
                or provider.get("contractVersion") != RUNTIME_PROVIDER_VERSION
                or provider.get("implementationDigest") != self.descriptor.implementation_digest):
            raise CodexProviderRefused("unit owner or source differs")
        target = unit.configuration_target_ref
        physical = unit.scope_ref.to_dict()
        if (not isinstance(target, Mapping) or set(target) != {"environmentNamespace", "scopeId", "revision", "ownerProviderRef", "sourceRevision"}
                or not _same_reference(target.get("ownerProviderRef"), provider)
                or any(target.get(key) != physical.get(key) for key in ("environmentNamespace", "scopeId", "revision"))
                or target.get("environmentNamespace") != canonical["environmentNamespace"]
                or not _source_identity(target.get("sourceRevision"))):
            raise CodexProviderRefused("original configuration target owner or source unavailable")
        return unit

    def start(self, prepared_unit, invocation_context):
        self._supported("start")
        unit_ref = prepared_unit.get("unitRef")
        unit = self._unit(unit_ref)
        facts = invocation_context.facts
        # Persist opening before native launch. Duplicate starts cannot obtain a ticket.
        ticket = self.records.begin_session(unit.unit_ref, invocation_context, input_digest=facts["inputDigest"])
        client = None
        try:
            verified = self._current_start(unit, invocation_context)
            client = self.channel_factory.open(unit.facts["privateRootFacts"], verified)
            # The opened owned channel record is bound for later termination
            # evidence verification (fixed installation/root/process identity).
            termination = self.termination_evidence
            if (callable(getattr(termination, "bind_unit_channel", None))
                    and callable(getattr(self.channel_factory, "record", None))):
                termination.bind_unit_channel(unit.unit_ref, self.channel_factory.record(client))
            self._current_start(unit, invocation_context)
            client.initialize()
            cwd = unit.facts["privateRootFacts"].get("cwd")
            if not isinstance(cwd, str) or not os.path.isabs(cwd):
                raise CodexProviderRefused("canonical isolated cwd required")
            self._current_start(unit, invocation_context)
            receipt = client.create_thread(cwd=cwd)
            thread = receipt.get("thread")
            if not isinstance(thread, Mapping) or not isinstance(thread.get("id"), str) or not thread["id"]:
                raise CodexProviderRefused("thread receipt lacks identity")
            self._current_start(unit, invocation_context)
            observed = client.command("thread/read", threadId=thread["id"], includeTurns=False)
            if observed.get("thread", {}).get("id") != thread["id"]:
                raise CodexProviderRefused("native thread readback differs")
            self._current_start(unit, invocation_context)
            evidence = self.projection.publish_channel(unit, client, observed)
            binding = self.records.record_session(ticket, expected_source_revision=2, state="confirmed", evidence=evidence)
            with self._lock:
                self._channels[unit.unit_ref] = client
            return {"unitRef": _plain(unit_ref), "nativeBinding": _plain(binding.native_facts),
                    "sourceRevision": str(binding.source_revision), "state": "confirmed"}
        except Exception:
            # No close/kill/retry on unknown: keep any created handle for authorized reconciliation.
            if client is not None:
                with self._lock:
                    self._channels[unit.unit_ref] = client
            try:
                self.records.record_session(ticket, expected_source_revision=2, state="unknown")
            except Exception:
                pass  # a concurrently confirmed original binding is never downgraded
            raise CodexProviderRefused("native creation outcome unknown; query original operation") from None

    def _current_start(self, unit, context):
        # The deployment proves original claim consumption and current
        # authority/activation/epoch/DirectoryBinding before each native edge.
        facts = self.projection.revalidate_start(unit, context)
        original = context.facts
        if (not isinstance(facts, Mapping) or not _same_reference(facts, original) or facts.get("action") != "start"
                or facts.get("providerRef") != unit.facts["providerRef"]
                or facts.get("targetRef") != unit.facts["nodeRef"] or facts.get("query") is not False
                or facts.get("managementEpoch") != unit.facts["managementEpoch"]):
            raise CodexProviderRefused("current start authority unavailable or changed")
        return facts

    def query_step(self, correlation, authorized_read_context):
        self._supported("query_step")
        facts = self._facts(authorized_read_context, "query")
        if facts.get("query") is not True:
            raise CodexProviderRefused("read authority required")
        return self.projection.query_creation(correlation, facts)

    def inspect_unit(self, unit_ref):
        self._supported("inspect_unit")
        unit = self._unit(unit_ref)
        projection = self.projection.publication_facts(unit_ref)
        if (not isinstance(projection, Mapping) or not _same_reference(projection.get("unitRef"), unit.public_ref)
                or not _same_reference(projection.get("providerRef"), unit.facts["providerRef"])
                or not _same_reference(projection.get("configurationTargetRef"), unit.configuration_target_ref)
                or type(projection.get("managementEpoch")) is not int
                or projection["managementEpoch"] != unit.facts["managementEpoch"]):
            raise CodexProviderRefused("publication owner or configuration scope differs")
        # DirectoryBinding and current observation revision still belong to
        # their original owners; the fixed Unit source is not substituted.
        return UnitInspection(unit_ref, unit.facts["providerRef"], unit.configuration_target_ref,
                    projection["directoryBindingRef"], projection["managementEpoch"], "owned",
                    projection["sourceRevision"], _now(), projection["evidenceRef"])

    def describe_configuration(self, unit_ref):
        self._supported("describe_configuration")
        self._unit(unit_ref)
        supported = "apply_configuration" in self.descriptor.supported_methods
        return (_defaults_description("supported" if supported else "unsupported"),)

    def _live(self, unit_ref, unit):
        binding = self.projection.read_session(unit_ref)
        if binding.state != "confirmed" or unit.unit_ref not in self._channels:
            raise CodexProviderRefused("live confirmed native owner unavailable")
        return binding, self._channels[unit.unit_ref]

    def _config_path(self, unit):
        home = unit.facts["privateRootFacts"].get("codexHome")
        if (not isinstance(home, str) or not os.path.isabs(home) or os.path.normpath(home) != home
                or "\x00" in home or home == "/" or home.startswith("//")):
            raise CodexProviderRefused("explicit verified isolated CODEX_HOME required")
        return os.path.join(home, "config.toml")

    def _read_configuration(self, unit_ref, unit, binding, client, *, before_rpc=None):
        if before_rpc: before_rpc()
        raw = client.command("config/read", includeLayers=True)
        config = raw.get("config") if isinstance(raw, Mapping) else None
        if not isinstance(config, Mapping):
            raise CodexProviderRefused("native configuration readback unavailable")
        effective = _safe_defaults(config)
        user, version = {}, None
        try:
            file_path = self._config_path(unit)
        except CodexProviderRefused:
            file_path = None
        matching = [layer for layer in raw.get("layers") or () if isinstance(layer, Mapping)
                    and isinstance(layer.get("name"), Mapping) and layer["name"].get("type") == "user"
                    and layer["name"].get("file") == file_path and layer.get("disabledReason") is None]
        if len(matching) == 1 and isinstance(matching[0].get("version"), str) and 0 < len(matching[0]["version"]) <= 512 and not any(ord(c) < 32 for c in matching[0]["version"]):
            version = matching[0]["version"]
            user = _safe_defaults(matching[0].get("config", {}))
        if before_rpc: before_rpc()
        observed = client.command("thread/read", threadId=binding.native_facts["sessionId"], includeTurns=False)
        thread = observed.get("thread") if isinstance(observed, Mapping) else None
        if not isinstance(thread, Mapping) or thread.get("id") != binding.native_facts["sessionId"]:
            raise CodexProviderRefused("native configuration thread identity differs")
        actual_thread = {key: thread[key] for key in ("model", "reasoningEffort")
                         if isinstance(thread.get(key), str) and 0 < len(thread[key]) <= 256}
        facts = {"defaults": user, "effectiveDefaults": effective, "thread": actual_thread,
                 "nativeUserVersion": version}
        revision = "sha256:" + hashlib.sha256(safe_json(facts).encode()).hexdigest()
        unknown = ["providerCredentials", "threadOverridesOther"]
        for key in ("model", "reasoningEffort"):
            if key not in actual_thread: unknown.append("thread." + key)
        if version is None: unknown.append("defaultsVersion")
        snapshot = ConfigurationSnapshot(unit_ref, unit.configuration_target_ref, revision, _now(),
                    {"defaults": user, "effectiveDefaults": effective, "thread": actual_thread}, tuple(unknown),
                    {"environmentNamespace": unit_ref["environmentNamespace"], "evidenceRef": binding.native_facts["evidenceRef"]},
                    "ownerSerialized" if version and "apply_configuration" in self.descriptor.supported_methods else "unavailable")
        return snapshot, facts

    def inspect_configuration(self, unit_ref):
        self._supported("inspect_configuration")
        unit = self._unit(unit_ref)
        binding, client = self._live(unit_ref, unit)
        with self._lock:
            return self._read_configuration(unit_ref, unit, binding, client)[0]

    def describe_access(self, unit_ref):
        self._supported("describe_access")
        unit = self._unit(unit_ref)
        binding = self.projection.read_session(unit_ref)
        if binding.state != "confirmed" or unit.unit_ref not in self._channels:
            raise CodexProviderRefused("native access not confirmed")
        return {"protocol": "codex-app-server/1", "unitRef": _plain(unit_ref),
                "nativeSessionId": binding.native_facts["sessionId"], "fullNativeSideEffects": True,
                "leaseRequired": True, "readonlySupported": False}

    def connect(self, unit_ref, authorized_lease):
        self._supported("connect")
        unit = self._unit(unit_ref)
        access = self.describe_access(unit_ref)
        return self.lease_port.bind(unit_ref, authorized_lease, self._channels[unit.unit_ref],
                                    native_session_id=access["nativeSessionId"])

    def prepare_managed_turn(self, unit_ref, text):
        self._require_managed_turn()
        """Freeze one text-only turn on the original confirmed live client."""
        self._supported("start")
        if type(text) is not str:
            raise CodexCapabilityUnsupported("managed Codex input must be canonical text")
        unit = self._unit(unit_ref)
        binding = self.projection.read_session(unit_ref)
        client = self._channels.get(unit.unit_ref)
        if (binding.state != "confirmed" or binding.native_facts is None or client is None
                or not isinstance(binding.native_facts.get("sessionId"), str)
                or not binding.native_facts.get("sessionId")):
            raise CodexCapabilityUnsupported("original confirmed live Codex Session is unavailable")
        frame = client.prepare_request("turn/start", {
            "threadId": binding.native_facts["sessionId"],
            "input": [{"type": "text", "text": text}],
        })
        payload = frame.payload
        params = payload.get("params")
        if (payload.get("method") != "turn/start" or not isinstance(params, Mapping)
                or params.get("threadId") != binding.native_facts["sessionId"]
                or params.get("input") != [{"type": "text", "text": text}]):
            client.discard_prepared(frame)
            raise CodexProviderRefused("prepared Codex frame differs from the exact text and original Session")
        facts = {
            "protocol": frame.protocol,
            "nativeRequestId": frame.request_id,
            "frameDigest": frame.frame_digest,
            "method": payload["method"],
            "nativeThreadId": params["threadId"],
        }
        return PreparedManagedTurn(sealed_mapping(_plain(unit_ref)), client, frame,
                                   sealed_mapping(facts))

    def _managed_turn_owner(self, unit_ref, prepared=None):
        unit = self._unit(unit_ref)
        client = self._channels.get(unit.unit_ref)
        session = self.projection.read_session(unit_ref)
        if (client is None or session.state != "confirmed" or session.native_facts is None
                or unit.facts.get("managementEpoch") is None):
            raise CodexCapabilityUnsupported("original confirmed Codex Unit/Session is unavailable")
        return unit, client, session

    def validate_managed_turn(self, unit_ref, binding):
        """Revalidate original Unit, Session, client and frozen request facts."""
        self._require_managed_turn()
        unit, client, session = self._managed_turn_owner(unit_ref)
        expected = {"protocol": PROTOCOL,
            "nativeThreadId": session.native_facts.get("sessionId"),
            "method": "turn/start"}
        return (isinstance(binding, Mapping) and isinstance(binding.get("unitRef"), Mapping)
                and all(binding.get(key) == value for key, value in expected.items())
                and binding.get("managementEpoch") == unit.facts.get("managementEpoch")
                and unit.unit_ref == binding.get("unitRef", {}).get("unitId")
                and safe_json(unit.facts["providerRef"]) == safe_json(binding.get("providerRef")))

    def discard_managed_turn(self, unit_ref, prepared, binding):
        unit, client, _ = self._managed_turn_owner(unit_ref)
        if (type(prepared) is not PreparedManagedTurn or prepared.client is not client
                or safe_json(prepared.unit_ref) != safe_json(unit_ref)):
            raise CodexProviderRefused("prepared frame does not belong to this original Codex Unit")
        client.discard_prepared(prepared.frame)

    def dispatch_managed_turn(self, unit_ref, prepared, invocation, *, before_write, binding, timeout):
        self._require_managed_turn()
        self._supported("start")
        unit, client, session = self._managed_turn_owner(unit_ref, prepared)
        if (type(prepared) is not PreparedManagedTurn or prepared.client is not client
                or safe_json(prepared.unit_ref) != safe_json(unit_ref)
                or not isinstance(binding, Mapping)
                or not set(prepared.binding) <= set(binding)
                or safe_json(prepared.binding) != safe_json({key: binding[key] for key in prepared.binding})
                or not callable(before_write)
                or prepared.frame.request_id != binding.get("nativeRequestId")
                or prepared.frame.frame_digest != binding.get("frameDigest")
                or prepared.frame.protocol != binding.get("protocol")
                or session.native_facts.get("sessionId") != binding.get("nativeThreadId")
                or unit.facts.get("managementEpoch") != binding.get("managementEpoch")):
            raise CodexProviderRefused("dispatch differs from the original frozen Codex frame")
        if not self.validate_managed_turn(unit_ref, binding):
            raise CodexProviderRefused("original Codex Unit/Session changed before dispatch")
        result = client.dispatch_prepared(prepared.frame, before_write=before_write, timeout=timeout)
        turn = result.get("turn") if isinstance(result, Mapping) else None
        if (not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str) or not turn["id"]
                or turn.get("status") != "inProgress"):
            raise CodexProviderRefused("original Codex turn receipt is malformed; outcome unknown")
        receipt = {"contractVersion": "codex-turn-receipt/1",
            "nativeRequestId": prepared.frame.request_id,
            "frameDigest": prepared.frame.frame_digest,
            "nativeThreadId": binding["nativeThreadId"],
            "nativeTurnId": turn["id"], "status": "inProgress",
            "receiptDigest": "sha256:" + hashlib.sha256(safe_json(result).encode("utf-8")).hexdigest()}
        return receipt

    def observe_managed_turn(self, unit_ref, binding, *, authorized_read_context,
                             target_ref, operation_digest, native_turn_id, timeout=0.0):
        self._require_managed_turn()
        self._supported("start")
        if not isinstance(unit_ref, Mapping) or not isinstance(unit_ref.get("ownerProviderRef"), Mapping):
            raise CodexProviderRefused("original owner-bound Unit reference required")
        self.verifier.verify_and_consume(authorized_read_context, "query",
            unit_ref["ownerProviderRef"], target_ref, operation_digest)
        unit, client, session = self._managed_turn_owner(unit_ref)
        if (session.native_facts.get("sessionId") != binding.get("nativeThreadId")
                or unit.facts.get("managementEpoch") != binding.get("managementEpoch")
                or safe_json(unit.facts["providerRef"]) != safe_json(unit_ref["ownerProviderRef"])):
            raise CodexProviderRefused("original Codex Unit/Session changed")
        try:
            event = client.wait_turn_completed(timeout=timeout,
                thread_id=binding["nativeThreadId"], turn_id=native_turn_id)
        except Exception as error:
            raw = getattr(error, "raw", None)
            if not isinstance(raw, Mapping):
                return None
            event = raw
        params = event.get("params") if isinstance(event, Mapping) else None
        turn = params.get("turn") if isinstance(params, Mapping) else None
        if (not isinstance(params, Mapping) or not isinstance(turn, Mapping)
                or params.get("threadId") != binding["nativeThreadId"]
                or turn.get("id") != native_turn_id
                or turn.get("status") not in {"completed", "failed", "interrupted"}):
            return None
        return {"nativeThreadId": params["threadId"], "nativeTurnId": turn["id"],
                "status": turn["status"], "event": _plain(event)}

    def _current_configuration(self, unit, context):
        facts = self.projection.revalidate_configuration(unit, context)
        original = context.facts
        if (not isinstance(facts, Mapping) or not _same_reference(facts, original)
                or facts.get("providerRef") != unit.facts["providerRef"]
                or not _same_reference(facts.get("targetRef"), unit.configuration_target_ref)
                or facts.get("managementEpoch") != unit.facts["managementEpoch"]
                or (facts.get("action"), facts.get("query")) not in {("applyConfiguration", False), ("query", True)}):
            raise CodexProviderRefused("current configuration authority unavailable or changed")
        return facts

    def _compile_change(self, change):
        edits, supported, skipped = [], [], []
        used = set()
        for item in change.declarations:
            valid = (item["configurationKind"] == DEFAULTS_KIND and item["schemaVersion"] == DEFAULTS_SCHEMA
                     and item["action"] in {"value", "reset"} and not item.get("resourceRefs"))
            payload = {key:None for key in sorted(DEFAULT_FIELDS)} if item["action"] == "reset" else item.get("payload", {})
            valid = valid and isinstance(payload, Mapping) and bool(payload) and set(payload) <= DEFAULT_FIELDS
            if valid:
                if item["action"] == "value":
                    valid = all(isinstance(v, str) and 0 < len(v) <= 256 and not any(ord(c) < 32 for c in v)
                                and (k != "model_reasoning_effort" or v in EFFORTS) for k,v in payload.items())
                else:
                    # Native null removes only the explicitly named user defaults.
                    valid = all(v is None for v in payload.values())
            if not valid:
                if item["requirement"] == "required":
                    raise CodexCapabilityUnsupported("required native default declaration unsupported")
                skipped.append(item["declarationId"])
                continue
            if used.intersection(payload):
                raise CodexProviderRefused("overlapping defaults edits require explicit ordering")
            used.update(payload)
            supported.append(item)
            edits.extend({"keyPath": key, "value": value, "mergeStrategy": "replace"} for key,value in payload.items())
        return edits, supported, skipped

    def _unknown_change(self, facts, declarations):
        return ConfigurationChangeResult(facts["operationRef"],
            tuple(ConfigurationItemResult(item["declarationId"], "unknown") for item in declarations))

    def _validate_owner_result(self, unit_ref, unit, facts, declarations, result):
        if (not isinstance(result, ConfigurationChangeResult) or result.operation_ref != facts["operationRef"]
                or {item.declaration_id for item in result.item_results} != {item["declarationId"] for item in declarations}):
            raise CodexProviderRefused("original owner result identity differs")
        for item in result.item_results:
            if item.outcome == "applied":
                proof = item.confirmation
                if (not _same_reference(proof["unitRef"], unit_ref) or not _same_reference(proof["scopeRef"], unit.configuration_target_ref)
                        or proof["requestDigest"] != facts["inputDigest"]):
                    raise CodexProviderRefused("original owner result scope or request differs")
        if result.confirmed_snapshot is not None:
            snapshot = result.confirmed_snapshot
            if not _same_reference(snapshot.unit_ref, unit_ref) or not _same_reference(snapshot.scope_ref, unit.configuration_target_ref):
                raise CodexProviderRefused("original owner snapshot scope differs")
        return result

    def _confirm_change(self, unit_ref, unit, binding, client, context, waiter):
        facts = self._current_configuration(unit, context)
        snapshot, after = self._read_configuration(unit_ref, unit, binding, client,
                            before_rpc=lambda: self._current_configuration(unit, context))
        receipt = waiter["receipt"]
        before = waiter["before"]
        request = waiter["native_request"]
        if (not isinstance(receipt, Mapping) or set(receipt) - {"status", "version", "filePath", "overriddenMetadata"}
                or receipt.get("status") not in {"ok", "okOverridden"}
                or receipt.get("filePath") != self._config_path(unit)
                or not isinstance(receipt.get("version"), str) or receipt["version"] != after["nativeUserVersion"]):
            raise CodexProviderRefused("original native write receipt or readback version unavailable")
        outcomes = []
        for item in waiter["change"].declarations:
            if item["declarationId"] in waiter["skipped"]:
                outcome = "rejected"
            else:
                payload = {key:None for key in DEFAULT_FIELDS} if item["action"] == "reset" else item["payload"]
                if item["action"] == "reset":
                    matches = all(key not in after["defaults"] for key in payload)
                else:
                    matches = all(after["defaults"].get(key) == value and after["effectiveDefaults"].get(key) == value
                                  for key,value in payload.items())
                outcome = "applied" if matches and receipt["status"] == "ok" else "unknown"
            outcomes.append({"declarationId":item["declarationId"], "outcome":outcome})
        summary = {"operationRef": facts["operationRef"], "unitRef": _plain(unit_ref),
                   "scopeRef": _plain(unit.configuration_target_ref), "requestDigest": facts["inputDigest"],
                   "itemOutcomes": outcomes, "confirmedSnapshot": snapshot.to_dict()}
        safe_receipt = {key: receipt[key] for key in ("status", "version", "filePath")}
        evidence = self.configuration_evidence.capture_configuration(unit, facts, request, safe_receipt, before, after, summary)
        self._current_configuration(unit, context)
        if any(item['outcome'] == 'unknown' for item in outcomes):
            # A correlated native receipt does not conclude unknown item
            # effects. Keep the original scope reservation and waiter. The
            # captured owner evidence can substantiate individually applied
            # items, but must not release the unresolved batch's write fence.
            attempt = self.records.record_configuration_change(waiter['ticket'],
                expected_source_revision=waiter['attempt_revision'], state='unknown')
            waiter['attempt_revision'] = attempt.source_revision
            proof = {'operationRef': facts['operationRef'], 'unitRef': unit_ref,
                'scopeRef': unit.configuration_target_ref, 'requestDigest': facts['inputDigest'],
                'evidenceRef': {'environmentNamespace': unit_ref['environmentNamespace'], 'evidenceRef': evidence}}
            result = ConfigurationChangeResult(facts['operationRef'], tuple(
                ConfigurationItemResult(item['declarationId'], item['outcome'],
                    proof if item['outcome'] == 'applied' else None) for item in outcomes), snapshot)
            return self._validate_owner_result(unit_ref, unit, facts, waiter['change'].declarations, result)
        attempt = self.records.record_configuration_change(waiter["ticket"],
                      expected_source_revision=waiter["attempt_revision"], state="confirmed", evidence=evidence)
        self._configuration_waiters.pop(facts["operationRef"], None)
        result = self.configuration_evidence.read_configuration_result(unit, attempt)
        return self._validate_owner_result(unit_ref, unit, facts, waiter["change"].declarations, result)

    def apply_configuration(self, unit_ref, change_request, invocation_context):
        self._supported("apply_configuration")
        if not isinstance(change_request, ConfigurationChangeRequest):
            raise CodexProviderRefused("typed fixed change required")
        unit = self._unit(unit_ref)
        binding, client = self._live(unit_ref, unit)
        edits, supported, skipped = self._compile_change(change_request)
        facts = invocation_context.facts
        if not edits:
            # Consume the original authority even for an explicit no-effect rejection.
            verified = self.verifier.verify_and_consume(invocation_context, "applyConfiguration",
                           unit.facts["providerRef"], unit.configuration_target_ref, facts["inputDigest"])
            if verified != facts: raise CodexProviderRefused("configuration authority differs")
            return ConfigurationChangeResult(facts["operationRef"],
                tuple(ConfigurationItemResult(item["declarationId"], "rejected") for item in change_request.declarations))
        with self._lock:
            # begin consumes original invocation; never consume a second time.
            self._config_path(unit)
            # Refuse a known stale prerequisite before claiming an attempt.
            # Native expectedVersion still checks again at the actual write.
            preliminary, preliminary_facts = self._read_configuration(unit_ref, unit, binding, client)
            if preliminary.source_revision != change_request.expected_configuration_revision or preliminary_facts["nativeUserVersion"] is None:
                raise ConfigurationRevisionConflict("native configuration version prerequisite differs")
            ticket = self.records.begin_configuration_change(unit.unit_ref, invocation_context,
                      input_digest=facts["inputDigest"], expected_revision=change_request.expected_configuration_revision)
            waiter = {"ticket":ticket, "change":change_request, "skipped":skipped, "attempt_revision":1,
                      "before":None, "native_request":None, "receipt":None}
            self._configuration_waiters[facts["operationRef"]] = waiter
            try:
                before_snapshot, before = self._read_configuration(unit_ref, unit, binding, client,
                            before_rpc=lambda: self._current_configuration(unit, invocation_context))
                if before_snapshot.source_revision != change_request.expected_configuration_revision or before["nativeUserVersion"] is None:
                    raise ConfigurationRevisionConflict("native configuration changed before dispatch")
                waiter["before"] = before
                params = {"edits":edits, "filePath":self._config_path(unit),
                          "expectedVersion":before["nativeUserVersion"], "reloadUserConfig":False}
                def before_send(native_request):
                    self._current_configuration(unit, invocation_context)
                    digest = "sha256:" + hashlib.sha256(safe_json(native_request).encode()).hexdigest()
                    attempt = self.records.bind_configuration_dispatch(ticket,
                              native_request_id=native_request["id"], native_request_digest=digest)
                    waiter["native_request"] = native_request
                    waiter["attempt_revision"] = attempt.source_revision
                    self._current_configuration(unit, invocation_context)
                waiter["receipt"] = client.command_once("config/batchWrite", params, before_send=before_send)
                return self._confirm_change(unit_ref, unit, binding, client, invocation_context, waiter)
            except Exception:
                try:
                    attempt = self.records.record_configuration_change(ticket,
                              expected_source_revision=waiter["attempt_revision"], state="unknown")
                    waiter["attempt_revision"] = attempt.source_revision
                except Exception:
                    pass  # never downgrade a concurrently confirmed original receipt
                return self._unknown_change(facts, change_request.declarations)

    def query_change(self, unit_ref, operation_ref, authorized_read_context):
        self._supported("query_change")
        unit = self._unit(unit_ref)
        facts = authorized_read_context.facts
        with self._lock:
            attempt = self.records.query_configuration_change(unit.unit_ref, operation_ref,
                           authorized_read_context, input_digest=facts["inputDigest"])
            declarations = facts["contextRef"].get("effectiveDeclarations", ())
            self._current_configuration(unit, authorized_read_context)
            if attempt.state == "confirmed":
                result = self.configuration_evidence.read_configuration_result(unit, attempt)
                return self._validate_owner_result(unit_ref, unit, facts, declarations, result)
            waiter = self._configuration_waiters.get(operation_ref)
            if waiter is None or waiter["native_request"] is None or attempt.native_request_id != waiter["native_request"]["id"]:
                return self._unknown_change(facts, declarations)
            binding, client = self._live(unit_ref, unit)
            try:
                if waiter["receipt"] is None:
                    waiter["receipt"] = client.recover_request(attempt.native_request_id, timeout=0.05)
                return self._confirm_change(unit_ref, unit, binding, client, authorized_read_context, waiter)
            except Exception:
                return self._unknown_change(facts, declarations)

    # -- unified termination face (records path) ------------------------------
    def _owned_record(self, unit):
        """Resolve the factory record of this unit's live owned channel, or None."""
        with self._lock:
            client = self._channels.get(unit.unit_ref)
        if client is None:
            return None
        return self.channel_factory.record(client)

    def _termination_correlation(self, unit, action):
        """Read the just-opened attempt's correlation from the owner projection."""
        row = self.records.owner_read_termination(unit.unit_ref, action)
        if not isinstance(row, Mapping) or not isinstance(row.get("identity"), Mapping):
            raise CodexProviderRefused("original termination attempt projection unavailable")
        correlation = row["identity"].get("correlation")
        if not isinstance(correlation, str) or not correlation:
            raise CodexProviderRefused("original termination correlation unavailable")
        return correlation

    def _conclude_termination(self, unit, ticket, action, error):
        """Record the unknown outcome and refuse; the attempt keeps its hold."""
        try:
            self.records.record_termination(ticket, expected_source_revision=1, state="unknown")
        except Exception:
            pass  # never downgrade a concurrently confirmed original attempt
        raise CodexProviderRefused(
            f"{action} outcome unknown; the original attempt retains its hold") from error

    def stop(self, unit_ref, invocation_context):
        self._supported("stop")
        unit = self._unit(unit_ref)
        facts = invocation_context.facts
        # The one original stop attempt for this Unit; consumed before effect.
        ticket = self.records.begin_termination(unit.unit_ref, invocation_context,
                                                input_digest=facts["inputDigest"], action="stop")
        try:
            observed = {"action": "stop", "observedAt": _now()}
            record = self._owned_record(unit)
            if record is None:
                observed["ownedProcess"] = "none"  # nothing owned was ever running
            else:
                code = self.channel_factory.close(record.entry)
                observed["pid"] = str(record.channel._process.pid)
                observed["exitCode"] = str(int(code))
            observed["correlation"] = self._termination_correlation(unit, "stop")
            outcome = self.records.record_termination(ticket, expected_source_revision=1,
                                                      state="confirmed", evidence=observed)
            return {"unitRef": _plain(unit_ref), "action": "stop", "state": outcome["state"],
                    "outcome": _plain(outcome["outcome"])}
        except Exception as error:
            self._conclude_termination(unit, ticket, "stop", error)

    def release(self, unit_ref, invocation_context):
        self._supported("release")
        unit = self._unit(unit_ref)
        record = self._owned_record(unit)
        if record is not None and record.channel._process.poll() is None:
            # A live owned unit is stopped first; release never kills (A14),
            # never claims the destructive effect outside the stop ledger and
            # never consumes authority for an impossible release.
            raise CodexProviderRefused("live owned unit requires stop before release")
        facts = invocation_context.facts
        ticket = self.records.begin_termination(unit.unit_ref, invocation_context,
                                                input_digest=facts["inputDigest"], action="release")
        try:
            observed = {"action": "release", "observedAt": _now()}
            if record is None:
                with self._lock:
                    self._channels.pop(unit.unit_ref, None)
                observed["ownedProcess"] = "none"
            else:
                released = self.channel_factory.release(record.entry)
                with self._lock:
                    self._channels.pop(unit.unit_ref, None)
                observed["pid"] = str(released["pid"])
                observed["exitCode"] = str(int(released["exitCode"]))
            revoke = getattr(self.lease_port, "revoke", None)
            if callable(revoke):
                revoke(unit_ref)  # this side's usage ends: borrowed views lose writes
            observed["correlation"] = self._termination_correlation(unit, "release")
            outcome = self.records.record_termination(ticket, expected_source_revision=1,
                                                      state="confirmed", evidence=observed)
            return {"unitRef": _plain(unit_ref), "action": "release", "state": outcome["state"],
                    "outcome": _plain(outcome["outcome"])}
        except Exception as error:
            self._conclude_termination(unit, ticket, "release", error)

    def recover(self, native_binding, invocation_context):
        raise CodexCapabilityUnsupported("cold native recovery requires original durable installation/thread proof")


def records_ready(records, projection, verifier):
    return (all(port is not None for port in (records, projection, verifier))
            and getattr(records, "verifier", None) is verifier
            and callable(getattr(verifier, "verify_and_consume", None))
            and all(callable(getattr(records, method, None)) for method in
                ("reserve_unit", "begin_session", "record_session", "read_unit", "read_session"))
            and all(callable(getattr(projection, method, None)) for method in
                ("verify_preparation", "revalidate_start", "read_unit", "read_session", "publication_facts", "publish_channel")))


def configuration_ready(records, projection, evidence):
    return (evidence is not None and getattr(records, "configuration_evidence", None) is evidence
            and callable(getattr(projection, "revalidate_configuration", None))
            and all(callable(getattr(records, name, None)) for name in ("begin_configuration_change",
                "bind_configuration_dispatch", "record_configuration_change", "query_configuration_change"))
            and all(callable(getattr(evidence, name, None)) for name in
                ("verify_configuration", "capture_configuration", "read_configuration_result")))


def termination_ready(records, evidence):
    """The unified termination face is ready only with the production evidence port.

    The port must be the SAME instance UnitRecords was built with (the one
    owner both consume); absent ports keep stop/release typed-refused.
    """
    return (evidence is not None
            and getattr(records, "termination_evidence", None) is evidence
            and callable(getattr(evidence, "verify_termination", None))
            and callable(getattr(evidence, "bind_unit_channel", None))
            and callable(getattr(evidence, "observe_termination", None))
            and all(callable(getattr(records, name, None)) for name in
                ("begin_termination", "record_termination", "owner_read_termination",
                 "reconcile_termination")))


def _safe_defaults(config):
    if not isinstance(config, Mapping): return {}
    return {key: value for key,value in config.items() if key in DEFAULT_FIELDS
            and isinstance(value, str) and 0 < len(value) <= 256 and not any(ord(c) < 32 for c in value)}


def _defaults_description(status):
    schema = {"type": "object", "properties": {"model": {"type": "string", "minLength": 1, "maxLength": 256},
              "model_reasoning_effort": {"enum": sorted(EFFORTS)}}, "additionalProperties": False, "minProperties": 1}
    supported = status == "supported"
    return ConfigurationDescription(DEFAULTS_KIND, DEFAULTS_SCHEMA, schema,
        ("value", "reset") if status != "unsupported" else (), "instance" if status != "unsupported" else None,
        ("live",) if supported else (), "readback" if supported else "none", status)


def _complete_unit_reference(value):
    # Validate only the published shape. The immutable source hash is obtained
    # from the original authorized UnitReservation, never regenerated here.
    return (isinstance(value, Mapping) and set(value) == {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}
            and isinstance(value.get("environmentNamespace"), str) and bool(value["environmentNamespace"])
            and isinstance(value.get("unitId"), str) and bool(value["unitId"])
            and isinstance(value.get("ownerProviderRef"), Mapping)
            and value["ownerProviderRef"].get("environmentNamespace") == value["environmentNamespace"]
            and _source_identity(value.get("sourceRevision")))


def _same_reference(left, right):
    # JSON identity is type-sensitive (bool is not an integer generation).
    try:
        return safe_json(left) == safe_json(right)
    except (TypeError, ValueError):
        return False


def _source_identity(value):
    return (isinstance(value, str) and len(value) == 71 and value.startswith("sha256:")
            and all(c in "0123456789abcdef" for c in value[7:]))
