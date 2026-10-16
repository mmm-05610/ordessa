"""dsh AgentUnit ownership, using the existing deployment-owned UnitRecords.

No registries, daemon, database, or current-config cache lives in this package.
Native channels are live owned handles, not durable truth. Deployment binds
projection/evidence/authorization ports to its original journal and core issuer.

Channel facts (freeze §1): ACP stdio subprocess (``dsh --profile acp``), the
same subprocess channel shape as codex/pi. ``recover`` is PERMANENTLY absent:
dsh rejects ``session/load``; ``session/resume`` belongs to the bridge
continuation contract (``agent-box.dsh-continuation@1``) and never enters the
provider's supported methods. The four configuration methods are also absent
in this version: no configuration evidence port is pinned for dsh in this tree
(freeze §3). `implementation_digest` is a REQUIRED keyword-only parameter with
no default: the package never generates or guesses it; the deployment
fingerprint gate injects the production digest. Until that gate is backfilled,
this provider must not appear in any production assembly.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import stat
import threading
from typing import Mapping, Protocol

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping
from ordessa_units.public import (
    RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION,
    ConfigurationUnsupported,
    UnitInspection,
)

from .client import PROTOCOL, identity_text

DSH_NATIVE_VERSION = "0.1.5-rc.1"


class DshProviderRefused(RuntimeError):
    code = "DSH_PROVIDER_REFUSED"


class DshCapabilityUnsupported(ConfigurationUnsupported):
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

    The factory installs managed stdin fencing before initialize/session/new.
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


class DshRuntimeProvider:
    def __init__(self, *, definition_ref, implementation_digest, unit_records=None,
                 projection=None, verifier=None, channel_factory=None, lease_port=None,
                 termination_evidence=None):
        if not isinstance(implementation_digest, str) or not implementation_digest:
            raise DshProviderRefused(
                "implementation_digest is required; this package never generates or defaults it")
        self.records, self.projection, self.verifier = unit_records, projection, verifier
        self.channel_factory, self.lease_port = channel_factory, lease_port
        self.termination_evidence = termination_evidence
        self._channels = {}  # live process handles; never used as persistent recovery proof
        self._lock = threading.RLock()
        methods = ["describe_definition", "inspect_installation", "assess_configuration", "plan_preparation"]
        if records_ready(unit_records, projection, verifier):
            methods += ["prepare", "inspect_unit"]
            if callable(getattr(channel_factory, "open", None)):
                methods += ["start", "describe_access"]
                if (callable(getattr(channel_factory, "record", None))
                        and termination_ready(unit_records, termination_evidence)):
                    methods += ["stop", "release"]
                if callable(getattr(lease_port, "bind", None)):
                    methods += ["connect"]
            if callable(getattr(projection, "query_creation", None)):
                methods += ["query_step"]
        # The configuration family (describe_configuration, inspect_configuration,
        # apply_configuration, query_change) is deliberately absent: no
        # configuration evidence port is pinned for dsh in this tree. Calling
        # any of them raises a typed refusal; they never appear in the descriptor.
        self.descriptor = RuntimeProviderDescriptor("dsh", RUNTIME_PROVIDER_VERSION,
                    definition_ref, implementation_digest, tuple(methods))

    def _supported(self, name):
        if name not in self.descriptor.supported_methods:
            raise DshCapabilityUnsupported("dsh capability unavailable: " + name)

    def describe_definition(self, definition_ref):
        if definition_ref != self.descriptor.definition_ref:
            raise DshProviderRefused("definition identity differs")
        return {"familyId": "dsh", "channel": PROTOCOL,
                "contractVersion": RUNTIME_PROVIDER_VERSION,
                "supportedMethods": list(self.descriptor.supported_methods),
                "nativeVersion": DSH_NATIVE_VERSION, "nativeVersionVerified": False,
                "ownership": "owned-process-and-session", "recovery": "unsupported"}

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
            raise DshProviderRefused("fixed snapshot and preparation context required")
        if snapshot.get("manifest", {}).get("declarations"):
            raise DshCapabilityUnsupported("native preparation configuration requires resolved material integration")
        if not isinstance(context.get("privateRootFacts"), Mapping) or not context.get("privateRootFacts"):
            raise DshProviderRefused("explicit isolated root facts required")
        return sealed_mapping({"profileSnapshot": _plain(snapshot), "context": _plain(context),
                               "correlation": _plain(correlation)})

    def _facts(self, context, action, unit=None):
        if self.verifier is None:
            raise DshProviderRefused("invocation verifier absent")
        facts = context.facts
        provider = unit.facts["providerRef"] if unit else facts["providerRef"]
        target = unit.facts["nodeRef"] if unit else facts["targetRef"]
        if (provider.get("providerId") != "dsh" or
                provider.get("implementationDigest") != self.descriptor.implementation_digest or
                provider.get("contractVersion") != RUNTIME_PROVIDER_VERSION):
            raise DshProviderRefused("current admitted provider identity differs")
        verified = self.verifier.verify_and_consume(context, action, provider, target, facts["inputDigest"])
        if (verified.get("action") != action or verified.get("providerRef") != provider or
                verified.get("targetRef") != target or verified.get("inputDigest") != facts["inputDigest"]):
            raise DshProviderRefused("verified invocation identity differs")
        return verified

    def prepare(self, plan, invocation_context):
        self._supported("prepare")
        # UnitRecords consumes exactly the original prepare claim itself.
        facts = invocation_context.facts
        provider = facts["providerRef"]
        if provider.get("providerId") != "dsh" or provider.get("implementationDigest") != self.descriptor.implementation_digest:
            raise DshProviderRefused("prepare provider differs")
        if plan.get("context", {}).get("nodeRef") != facts["targetRef"]:
            raise DshProviderRefused("plan node binding differs")
        unit, created = self.records.reserve_unit(invocation_context, provider_ref=provider,
                        node_ref=facts["targetRef"], input_digest=facts["inputDigest"],
                        private_root_facts=self.projection.verify_preparation(plan, facts))
        public_ref = unit.public_ref
        if (not _complete_unit_reference(public_ref) or public_ref["unitId"] != unit.unit_ref
                or not _same_reference(public_ref["ownerProviderRef"], provider)
                or public_ref["environmentNamespace"] != provider["environmentNamespace"]):
            raise DshProviderRefused("original prepared unit owner reference differs")
        return {"unitRef": public_ref, "created": created, "state": "notCreated"}

    def _unit(self, unit_ref):
        if not _complete_unit_reference(unit_ref):
            raise DshProviderRefused("complete owner-bound unit reference required")
        # The projection must authorize and verify the original owner journal
        # read. A copied public reference never supplies read permission.
        unit = self.projection.read_unit(unit_ref)
        canonical = unit.public_ref
        provider = unit.facts["providerRef"]
        if (not _complete_unit_reference(canonical) or not _same_reference(canonical, unit_ref)
                or unit.unit_ref != canonical["unitId"]
                or not _same_reference(canonical["ownerProviderRef"], provider)
                or provider["environmentNamespace"] != canonical["environmentNamespace"]
                or provider.get("providerId") != "dsh"
                or provider.get("contractVersion") != RUNTIME_PROVIDER_VERSION
                or provider.get("implementationDigest") != self.descriptor.implementation_digest):
            raise DshProviderRefused("unit owner or source differs")
        target = unit.configuration_target_ref
        physical = unit.scope_ref.to_dict()
        if (not isinstance(target, Mapping) or set(target) != {"environmentNamespace", "scopeId", "revision", "ownerProviderRef", "sourceRevision"}
                or not _same_reference(target.get("ownerProviderRef"), provider)
                or any(target.get(key) != physical.get(key) for key in ("environmentNamespace", "scopeId", "revision"))
                or target.get("environmentNamespace") != canonical["environmentNamespace"]
                or not _source_identity(target.get("sourceRevision"))):
            raise DshProviderRefused("original configuration target owner or source unavailable")
        return unit

    def start(self, prepared_unit, invocation_context):
        """Native start over the ACP face: initialize -> session/new.

        There is NO readback RPC on this channel: the frozen dsh ACP frame set
        has no read-only session-state method (session/load is rejected by dsh;
        session/list is not in the frozen frame set; session/prompt would be a
        model call). The native evidence is the ORIGINAL session/new receipt
        plus the initialize result, sealed by the projection owner. A prompt
        receipt is never completion; recover never exists.
        """
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
            capabilities = client.initialize()
            if not isinstance(capabilities, Mapping):
                raise DshProviderRefused("initialize receipt lacks agent capabilities")
            cwd = unit.facts["privateRootFacts"].get("cwd")
            if not isinstance(cwd, str) or not os.path.isabs(cwd):
                raise DshProviderRefused("canonical isolated cwd required")
            self._current_start(unit, invocation_context)
            receipt = client.new_session(cwd=cwd)
            session = receipt.get("sessionId") if isinstance(receipt, Mapping) else None
            if not identity_text(session) or len(session) > 256:
                raise DshProviderRefused("session receipt lacks identity")
            self._current_start(unit, invocation_context)
            observed = {"sessionId": session, "initialize": _plain(capabilities)}
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
            raise DshProviderRefused("native creation outcome unknown; query original operation") from None

    def _current_start(self, unit, context):
        # The deployment proves original claim consumption and current
        # authority/activation/epoch/DirectoryBinding before each native edge.
        facts = self.projection.revalidate_start(unit, context)
        original = context.facts
        if (not isinstance(facts, Mapping) or not _same_reference(facts, original) or facts.get("action") != "start"
                or facts.get("providerRef") != unit.facts["providerRef"]
                or facts.get("targetRef") != unit.facts["nodeRef"] or facts.get("query") is not False
                or facts.get("managementEpoch") != unit.facts["managementEpoch"]):
            raise DshProviderRefused("current start authority unavailable or changed")
        return facts

    def query_step(self, correlation, authorized_read_context):
        self._supported("query_step")
        facts = self._facts(authorized_read_context, "query")
        if facts.get("query") is not True:
            raise DshProviderRefused("read authority required")
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
            raise DshProviderRefused("publication owner or configuration scope differs")
        # DirectoryBinding and current observation revision still belong to
        # their original owners; the fixed Unit source is not substituted.
        return UnitInspection(unit_ref, unit.facts["providerRef"], unit.configuration_target_ref,
                    projection["directoryBindingRef"], projection["managementEpoch"], "owned",
                    projection["sourceRevision"], _now(), projection["evidenceRef"])

    def describe_access(self, unit_ref):
        self._supported("describe_access")
        unit = self._unit(unit_ref)
        binding = self.projection.read_session(unit_ref)
        if binding.state != "confirmed" or unit.unit_ref not in self._channels:
            raise DshProviderRefused("native access not confirmed")
        return {"protocol": PROTOCOL, "unitRef": _plain(unit_ref),
                "nativeSessionId": binding.native_facts["sessionId"], "fullNativeSideEffects": True,
                "leaseRequired": True, "readonlySupported": False}

    def connect(self, unit_ref, authorized_lease):
        self._supported("connect")
        unit = self._unit(unit_ref)
        self.describe_access(unit_ref)
        return self.lease_port.bind(unit_ref, authorized_lease, self._channels[unit.unit_ref])

    # -- configuration family: honestly absent, typed-refused ---------------
    def describe_configuration(self, unit_ref):
        self._supported("describe_configuration")

    def inspect_configuration(self, unit_ref):
        self._supported("inspect_configuration")

    def apply_configuration(self, unit_ref, change_request, invocation_context):
        self._supported("apply_configuration")

    def query_change(self, unit_ref, operation_ref, authorized_read_context):
        self._supported("query_change")

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
            raise DshProviderRefused("original termination attempt projection unavailable")
        correlation = row["identity"].get("correlation")
        if not isinstance(correlation, str) or not correlation:
            raise DshProviderRefused("original termination correlation unavailable")
        return correlation

    def _conclude_termination(self, unit, ticket, action, error):
        """Record the unknown outcome and refuse; the attempt keeps its hold."""
        try:
            self.records.record_termination(ticket, expected_source_revision=1, state="unknown")
        except Exception:
            pass  # never downgrade a concurrently confirmed original attempt
        raise DshProviderRefused(
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
            raise DshProviderRefused("live owned unit requires stop before release")
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
        """Permanently absent (freeze §1): dsh rejects ``session/load``;
        ``session/resume`` belongs to the bridge continuation contract
        (``agent-box.dsh-continuation@1``) and never enters provider methods."""
        raise DshCapabilityUnsupported(
            "dsh permanently refuses cold recovery: session/load is rejected by dsh; "
            "resume belongs to the bridge continuation contract agent-box.dsh-continuation@1")


def records_ready(records, projection, verifier):
    return (all(port is not None for port in (records, projection, verifier))
            and getattr(records, "verifier", None) is verifier
            and callable(getattr(verifier, "verify_and_consume", None))
            and all(callable(getattr(records, method, None)) for method in
                ("reserve_unit", "begin_session", "record_session", "read_unit", "read_session"))
            and all(callable(getattr(projection, method, None)) for method in
                ("verify_preparation", "revalidate_start", "read_unit", "read_session", "publication_facts", "publish_channel")))


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
