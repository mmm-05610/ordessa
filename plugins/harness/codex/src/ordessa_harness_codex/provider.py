"""Codex AgentUnit ownership, using the existing deployment-owned UnitRecords.

No registries, daemon, database, or current-config cache lives in this package.
Native channels are live owned handles, not durable truth. Deployment binds
projection/evidence/authorization ports to its original journal and core issuer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import stat
import threading
from typing import Mapping, Protocol

from ordessa_environment_api.operations import safe_json, sealed_mapping
from pacthold.agents.public import (
    RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION,
    ConfigurationDescription, ConfigurationSnapshot, ConfigurationUnsupported,
    UnitInspection,
)


class CodexProviderRefused(RuntimeError):
    code = "CODEX_PROVIDER_REFUSED"


class CodexCapabilityUnsupported(ConfigurationUnsupported):
    pass


class UnitProjectionPort(Protocol):
    """Trusted read/evidence projection from the SAME original UnitRecords."""
    def verify_preparation(self, plan, invocation_facts): ...
    def revalidate_start(self, unit, invocation_context): ...
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
    def bind(self, unit_ref, authorized_lease, client): ...


def _now():
    return datetime.now(timezone.utc).isoformat()


def _plain(value):
    return json.loads(safe_json(value))


class CodexRuntimeProvider:
    def __init__(self, *, definition_ref, implementation_digest, unit_records=None,
                 projection=None, verifier=None, channel_factory=None, lease_port=None):
        self.records, self.projection, self.verifier = unit_records, projection, verifier
        self.channel_factory, self.lease_port = channel_factory, lease_port
        self._channels = {}  # live process handles; never used as persistent recovery proof
        self._lock = threading.RLock()
        methods = ["describe_definition", "inspect_installation", "assess_configuration", "plan_preparation"]
        if records_ready(unit_records, projection, verifier):
            methods += ["prepare", "inspect_unit", "describe_configuration"]
            if callable(getattr(channel_factory, "open", None)):
                methods += ["start", "inspect_configuration", "describe_access"]
                if callable(getattr(lease_port, "bind", None)):
                    methods += ["connect"]
            if callable(getattr(projection, "query_creation", None)):
                methods += ["query_step"]
        self.descriptor = RuntimeProviderDescriptor("codex", RUNTIME_PROVIDER_VERSION,
                    definition_ref, implementation_digest, tuple(methods))

    def _supported(self, name):
        if name not in self.descriptor.supported_methods:
            raise CodexCapabilityUnsupported("Codex capability unavailable: " + name)

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
        return {"unitRef": {"environmentNamespace": provider["environmentNamespace"], "unitId": unit.unit_ref},
                "created": created, "state": "notCreated"}

    def _unit(self, unit_ref):
        if not isinstance(unit_ref, Mapping) or set(unit_ref) != {"environmentNamespace", "unitId"}:
            raise CodexProviderRefused("complete unit reference required")
        unit = self.projection.read_unit(unit_ref)
        if (unit.unit_ref != unit_ref["unitId"] or unit.facts["providerRef"]["environmentNamespace"] != unit_ref["environmentNamespace"] or
                unit.facts["providerRef"].get("providerId") != "codex" or
                unit.facts["providerRef"].get("implementationDigest") != self.descriptor.implementation_digest):
            raise CodexProviderRefused("unit owner differs")
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
        if (not isinstance(facts, Mapping) or facts != original or facts.get("action") != "start"
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
        # The port returns core-issued DirectoryBindingRef plus journal evidence.
        return UnitInspection(unit_ref, unit.facts["providerRef"], unit.scope_ref.to_dict(),
                    projection["directoryBindingRef"], projection["managementEpoch"], "owned",
                    projection["sourceRevision"], _now(), projection["evidenceRef"])

    def describe_configuration(self, unit_ref):
        self._supported("describe_configuration")
        self._unit(unit_ref)
        # Readback available, but pinned config writes have no atomic compare.
        return (ConfigurationDescription("codex.native-config", "0.157.1", {}, (), None, (), "none", "unsupported"),)

    def inspect_configuration(self, unit_ref):
        self._supported("inspect_configuration")
        unit = self._unit(unit_ref)
        binding = self.projection.read_session(unit_ref)
        if binding.state != "confirmed" or unit.unit_ref not in self._channels:
            raise CodexProviderRefused("live confirmed native configuration owner unavailable")
        with self._lock:
            result = self._channels[unit.unit_ref].command("config/read", includeLayers=False)
        config = result.get("config")
        if not isinstance(config, Mapping):
            raise CodexProviderRefused("native configuration readback unavailable")
        # Whitelist nonsecret native fields. Never store account/environment/provider tables.
        known = {k: v for k, v in config.items() if k in {"model", "model_reasoning_effort", "approval_policy", "sandbox_mode"} and isinstance(v, str) and len(v) <= 256}
        revision = "sha256:" + hashlib.sha256(safe_json(known).encode()).hexdigest()
        return ConfigurationSnapshot(unit_ref, unit.scope_ref.to_dict(), revision, _now(), known,
                    ("providerCredentials", "sessionOverrides"),
                    {"environmentNamespace": unit_ref["environmentNamespace"], "evidenceRef": binding.native_facts["evidenceRef"]},
                    "unavailable")

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
        self.describe_access(unit_ref)
        return self.lease_port.bind(unit_ref, authorized_lease, self._channels[unit.unit_ref])

    def apply_configuration(self, unit_ref, change_request, invocation_context):
        raise CodexCapabilityUnsupported("live native configuration CAS/confirmation not integrated")

    def query_change(self, unit_ref, operation_ref, authorized_read_context):
        raise CodexCapabilityUnsupported("durable native change receipts unavailable")

    def stop(self, unit_ref, invocation_context):
        raise CodexCapabilityUnsupported("verified native stop and ownership cut not integrated")

    def release(self, unit_ref, invocation_context):
        raise CodexCapabilityUnsupported("journal scope release and unknown ownership reconciliation unavailable")

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
