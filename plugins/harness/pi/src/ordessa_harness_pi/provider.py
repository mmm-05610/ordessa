"""Pi-owned configuration confirmation over a deployment-owned live Unit.

The deployment supplies the existing Unit authority, serializer and journal
receipt ports. No fallback launch, configuration cache or extra operation store
exists here. Native effects use the core's consumed InvocationContext.

The records lifecycle path stores every configuration write attempt in the
original ``NativeConfigurationAttempt`` journal (begin → pre-send dispatch
binding → record), confirms applied items ONLY from the observed native
readback (``get_state``), never from the ACK, and keeps the expected-configuration-revision
comparison. Missing production evidence ports keep the surface typed-refused
and never advertised as ready.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Mapping, Protocol

from ordessa_environment_api.operations import safe_json
from pacthold.agents.configuration.change import (
    ConfigurationChangeRequest, ConfigurationChangeResult, ConfigurationDescription,
    ConfigurationItemResult, ConfigurationRevisionConflict, ConfigurationSnapshot, UnitInspection,
)
from pacthold.core.lifecycle import RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
from pacthold.agents.access.invocation import InvocationVerifier
from .lifecycle import PiLifecycleRefused, PiUnitLifecycle, plain, records_ready, same_reference


class PiProviderRefused(PiLifecycleRefused):
    code = "PI_PROVIDER_UNAVAILABLE"


class UnitOwnerPort(Protocol):
    """Trusted deployment binding to existing Unit/authority, never caller data."""
    def read_unit(self, unit_ref): ...  # same authorized journal UnitReservation
    def inspect_unit(self, unit_ref) -> UnitInspection: ...
    def channel(self, unit_ref): ...  # existing PiRpcClient; MUST NOT launch
    def verify_session(self, unit_ref, native_session_id) -> bool: ...
    def serialize_configuration(self, unit_ref): ...  # same canonical scope lock
    def revalidate_write(self, context, facts, unit_ref) -> bool: ...
    # Every setter rechecks the already verified grant and current writer lease,
    # directory, epoch and activation. This never issues replacement authority.


class ConfirmationPort(Protocol):
    """Existing owner journal stores exact attempt receipts, never inferred state."""
    def record(self, facts, unit, declaration, before, after) -> Mapping: ...
    def read(self, facts, unit, operation_ref) -> ConfigurationChangeResult | None: ...


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


def configuration_ready(records, projection, evidence):
    """The records-path configuration seam is ready only with its production ports.

    The evidence port must be the SAME instance UnitRecords was built with;
    anything else is a second store and is never advertised as ready.
    """
    return (evidence is not None
            and getattr(records, "configuration_evidence", None) is evidence
            and callable(getattr(projection, "revalidate_configuration", None))
            and all(callable(getattr(records, name, None)) for name in
                ("begin_configuration_change", "bind_configuration_dispatch",
                 "record_configuration_change", "query_configuration_change"))
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


_KIND_SCHEMAS = {
    "pi.model": {"type": "object", "properties": {"provider": {"type": "string"},
                       "model": {"type": "string"}}, "required": ["provider", "model"],
                       "additionalProperties": False},
    "pi.thinking": {"type": "object", "properties": {"level": {"type": "string"}},
                        "required": ["level"], "additionalProperties": False},
}


def _digest(value):
    return "sha256:" + hashlib.sha256(safe_json(value).encode()).hexdigest()


def _text(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and value.strip() == value and not any(ord(c) < 32 for c in value)


class PiRuntimeProvider(PiUnitLifecycle):
    """Versioned provider with only actually wired methods advertised.

    Preparation/start use the original UnitRecords and explicit trusted ports;
    recovery/settlement remain unsupported. Configuration requires explicit ports;
    methods exist to satisfy the runtime protocol, never imply capability.
    """
    def __init__(self, *, definition_ref, implementation_digest, owner=None, confirmations=None, verifier=None,
                 unit_records=None, projection=None, channel_factory=None, lease_port=None,
                 configuration_evidence=None, termination_evidence=None):
        # The assembled production owner view (frozen two-argument factory
        # contract) carries only the original UnitRecords and verifier. A
        # legacy owner/confirmations composition beside the records lifecycle
        # is never a valid wiring: capability declaration unions both branches
        # and the owner path would silently shadow the records path. Refuse
        # the mix instead of letting the old path join the declaration.
        if unit_records is not None and (owner is not None or confirmations is not None):
            raise PiProviderRefused(
                "records lifecycle and legacy owner/confirmations composition cannot both be wired")
        owner_methods = ("read_unit", "inspect_unit", "channel", "verify_session", "serialize_configuration", "revalidate_write")
        if owner is not None and any(not callable(getattr(owner, name, None)) for name in owner_methods):
            raise PiProviderRefused("complete trusted Unit owner ports required")
        if confirmations is not None and any(not callable(getattr(confirmations, name, None)) for name in ("record", "read")):
            raise PiProviderRefused("complete existing owner confirmation ports required")
        if verifier is not None and not isinstance(verifier, InvocationVerifier):
            raise PiProviderRefused("existing core InvocationVerifier required")
        self._owner, self._confirmations, self._verifier = owner, confirmations, verifier
        self._lifecycle_init(unit_records, projection, channel_factory, lease_port)
        self.configuration_evidence = configuration_evidence
        self.termination_evidence = termination_evidence
        self._configuration_waiters = {}  # live original tickets/receipts only; no cold truth or replay authority
        supported = ["describe_definition", "describe_configuration"]
        if records_ready(unit_records, projection, verifier):
            supported += ["plan_preparation", "prepare", "inspect_unit"]
            if callable(getattr(channel_factory, "open", None)):
                supported += ["start", "describe_access"]
                if (callable(getattr(channel_factory, "record", None))
                        and termination_ready(unit_records, termination_evidence)):
                    supported += ["stop", "release"]
                if configuration_ready(unit_records, projection, configuration_evidence):
                    supported += ["inspect_configuration", "apply_configuration", "query_change"]
                if callable(getattr(lease_port, "bind", None)):
                    supported += ["connect"]
            if callable(getattr(projection, "query_creation", None)):
                supported += ["query_step"]
        if owner is not None:
            supported += ["inspect_unit", "inspect_configuration"]
            if confirmations is not None and verifier is not None:
                supported += ["apply_configuration", "query_change"]
        self.descriptor = RuntimeProviderDescriptor("pi", RUNTIME_PROVIDER_VERSION,
                            definition_ref, implementation_digest, tuple(dict.fromkeys(supported)))

    def describe_definition(self, definition_ref):
        if definition_ref != self.descriptor.definition_ref:
            raise PiProviderRefused("definition reference differs")
        return {"definitionRef": dict(definition_ref), "familyId": "pi",
                "channel": "pi-rpc/1", "supportedMethods": list(self.descriptor.supported_methods),
                "configurationContract": "agent-configuration/1",
                "nativeVersion": "0.86.1", "runtimeReady": "unknown"}

    def inspect_unit(self, unit_ref):
        if self._owner is None:
            if "inspect_unit" in self.descriptor.supported_methods:
                return self._inspect_record(unit_ref)
            raise PiProviderRefused("trusted current Unit owner is absent")
        if (not isinstance(unit_ref, Mapping) or set(unit_ref) !=
                {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}):
            raise PiProviderRefused("complete original Unit source reference required")
        reservation = self._owner.read_unit(unit_ref)
        if not same_reference(getattr(reservation, "public_ref", None), unit_ref):
            raise PiProviderRefused("original Unit source identity differs")
        unit = self._owner.inspect_unit(unit_ref)
        if not isinstance(unit, UnitInspection) or not same_reference(unit.unit_ref, unit_ref) or unit.provider_ref.get("providerId") != "pi" or not same_reference(unit.provider_ref, reservation.public_ref["ownerProviderRef"]) or not same_reference(unit.configuration_target_ref, getattr(reservation, "configuration_target_ref", None)):
            raise PiProviderRefused("current Pi Unit evidence differs")
        return unit

    def describe_configuration(self, unit_ref):
        legacy_wired = self._owner is not None and self._confirmations is not None and self._verifier is not None
        records_wired = "apply_configuration" in self.descriptor.supported_methods
        if legacy_wired:
            self.inspect_unit(unit_ref)
        elif records_wired:
            self._unit_record(unit_ref)
        wired = legacy_wired or records_wired
        return tuple(ConfigurationDescription(kind, "1", schema, ("value",) if wired else (), "session",
                          ("live",) if wired else (), "readback" if wired else "none",
                          "supported" if wired else "unknown") for kind, schema in _KIND_SCHEMAS.items())

    def _snapshot(self, unit):
        try:
            state = self._owner.channel(unit.unit_ref).command("get_state").get("data")
        except Exception:
            raise PiProviderRefused("current native configuration observation unavailable") from None
        if not isinstance(state, Mapping) or not _text(state.get("sessionId")):
            raise PiProviderRefused("native session observation unavailable")
        # Native realm/session identity is checked by the trusted Unit owner on
        # every access; the channel is exclusively bound to that Unit's session.
        if self._owner.verify_session(unit.unit_ref, state["sessionId"]) is not True:
            raise PiProviderRefused("native session binding differs")
        configuration, unknown = {}, []
        model = state.get("model")
        if isinstance(model, Mapping) and _text(model.get("provider")) and _text(model.get("id")):
            configuration["pi.model"] = {"provider": model["provider"], "model": model["id"]}
        else:
            unknown.append("pi.model")
        if _text(state.get("thinkingLevel")):
            configuration["pi.thinking"] = {"level": state["thinkingLevel"]}
        else:
            unknown.append("pi.thinking")
        evidence = {"environmentNamespace": unit.unit_ref["environmentNamespace"],
                    "evidenceId": _digest({"sessionId": state["sessionId"], "configuration": configuration})}
        return ConfigurationSnapshot(unit.unit_ref, unit.configuration_target_ref,
                   _digest({"sessionId": state["sessionId"], "configuration": configuration, "unknown": unknown}),
                   datetime.now(timezone.utc).isoformat(), configuration, tuple(unknown), evidence,
                   "ownerSerialized")

    def inspect_configuration(self, unit_ref):
        if self._owner is not None:
            unit = self.inspect_unit(unit_ref)
            with self._owner.serialize_configuration(unit_ref):
                return self._snapshot(unit)
        self._required('inspect_configuration')
        unit = self._unit_record(unit_ref)
        binding, client = self._live(unit_ref, unit)
        with self._lifecycle_lock:  # one owner-serialized read; never a second authority
            return self._observe_state(unit, client)[0]

    def _observe_state(self, unit, client, *, before_rpc=None):
        """Records-path native readback: same canonical facts, journal session identity.

        The observation is an owner-serialized read of the live confirmed
        session; session identity is checked against the journal's original
        confirmed binding, never against caller data. Returns the typed
        snapshot and the readback facts (used as capture evidence).
        """
        if before_rpc is not None:
            before_rpc()
        try:
            state = client.command("get_state").get("data")
        except Exception:
            raise PiProviderRefused("current native configuration observation unavailable") from None
        if not isinstance(state, Mapping) or not _text(state.get("sessionId")):
            raise PiProviderRefused("native session observation unavailable")
        binding = self.projection.read_session(unit.public_ref)
        native = binding.native_facts
        if (binding.state != "confirmed" or not isinstance(native, Mapping)
                or native.get("sessionId") != state["sessionId"]):
            raise PiProviderRefused("native session binding differs")
        if before_rpc is not None:
            before_rpc()
        configuration, unknown = {}, []
        model = state.get("model")
        if isinstance(model, Mapping) and _text(model.get("provider")) and _text(model.get("id")):
            configuration["pi.model"] = {"provider": model["provider"], "model": model["id"]}
        else:
            unknown.append("pi.model")
        if _text(state.get("thinkingLevel")):
            configuration["pi.thinking"] = {"level": state["thinkingLevel"]}
        else:
            unknown.append("pi.thinking")
        evidence = {"environmentNamespace": unit.public_ref["environmentNamespace"],
                    "evidenceRef": native["evidenceRef"]}
        facts = {"sessionId": state["sessionId"], "configuration": configuration, "unknown": unknown}
        snapshot = ConfigurationSnapshot(unit.public_ref, unit.configuration_target_ref,
                   _digest({"sessionId": state["sessionId"], "configuration": configuration,
                            "unknown": unknown}),
                   datetime.now(timezone.utc).isoformat(), configuration, tuple(unknown), evidence,
                   "ownerSerialized")
        return snapshot, facts

    @staticmethod
    def _valid_declaration(declaration):
        kind, payload = declaration["configurationKind"], declaration.get("payload")
        fields = ("provider", "model") if kind == "pi.model" else ("level",) if kind == "pi.thinking" else ()
        return (declaration["schemaVersion"] == "1" and declaration["action"] == "value"
            and bool(fields) and isinstance(payload, Mapping) and set(payload) == set(fields)
            and all(_text(payload[key]) for key in fields) and not declaration.get("resourceRefs"))

    def _authorize(self, unit, context, action, query=False):
        if self._verifier is None:
            raise PiProviderRefused("existing core InvocationVerifier absent")
        try:
            digest = context.facts["inputDigest"]
            facts = self._verifier.verify_and_consume(context, action, unit.provider_ref,
                                  unit.configuration_target_ref, digest)
        except Exception:
            raise PiProviderRefused("current core invocation refused") from None
        if (not isinstance(facts, Mapping) or facts.get("query") is not query
                or facts.get("action") != action or not same_reference(facts.get("providerRef"), unit.provider_ref)
                or type(facts.get("managementEpoch")) is not int or facts.get("managementEpoch") != unit.management_epoch
                or not _text(facts.get("operationRef")) or not _text(facts.get("inputDigest"))):
            raise PiProviderRefused("verified core invocation facts differ")
        return facts

    # -- records-path change helpers ------------------------------------------
    def _authorize_change(self, unit, context, action, query=False):
        """Verify the original claim facts against the SAME consumed authority."""
        if self._verifier is None:
            raise PiProviderRefused("existing core InvocationVerifier absent")
        try:
            digest = context.facts["inputDigest"]
            facts = self._verifier.verify_and_consume(context, action, unit.facts["providerRef"],
                                  unit.configuration_target_ref, digest)
        except Exception:
            raise PiProviderRefused("current core invocation refused") from None
        if (not isinstance(facts, Mapping) or facts.get("query") is not query
                or facts.get("action") != action
                or not same_reference(facts.get("providerRef"), unit.facts["providerRef"])
                or not same_reference(facts.get("targetRef"), unit.configuration_target_ref)
                or type(facts.get("managementEpoch")) is not int
                or facts.get("managementEpoch") != unit.facts["managementEpoch"]
                or not _text(facts.get("operationRef")) or not _text(facts.get("inputDigest"))):
            raise PiProviderRefused("verified core invocation facts differ")
        return facts

    def _current_configuration(self, unit, context):
        """Current-authority re-check before and after every native write edge."""
        facts = self.projection.revalidate_configuration(unit, context)
        original = context.facts
        if (not isinstance(facts, Mapping) or not same_reference(facts, original)
                or not same_reference(facts.get("providerRef"), unit.facts["providerRef"])
                or not same_reference(facts.get("targetRef"), unit.configuration_target_ref)
                or type(facts.get("managementEpoch")) is not int
                or facts.get("managementEpoch") != unit.facts["managementEpoch"]
                or (facts.get("action"), facts.get("query")) not in
                    {("applyConfiguration", False), ("query", True)}):
            raise PiProviderRefused("current configuration authority unavailable or changed")
        return facts

    def _compile_change(self, change_request):
        """Partition declarations; one native write per journal dispatch record.

        Pi setters are distinct native RPCs, and one attempt carries exactly
        one dispatch identity: anything else is refused BEFORE the journal
        claim (never masked as one write). Required unsupported declarations
        are typed-refused; optional ones are reported rejected.
        """
        effective, rejected = [], []
        for item in change_request.declarations:
            if self._valid_declaration(item):
                effective.append(item)
            elif item["requirement"] == "required":
                raise PiProviderRefused("required native configuration declaration unsupported")
            else:
                rejected.append(item["declarationId"])
        if len(effective) > 1:
            raise PiProviderRefused(
                "pi setters are distinct native writes; they cannot share one dispatch record")
        return effective, rejected

    def _unknown_change(self, facts, declarations):
        return ConfigurationChangeResult(facts["operationRef"], tuple(
            ConfigurationItemResult(item["declarationId"], "unknown") for item in declarations))

    def _validate_owner_result(self, unit_ref, unit, facts, declarations, result):
        if (not isinstance(result, ConfigurationChangeResult) or result.operation_ref != facts["operationRef"]
                or {item.declaration_id for item in result.item_results} != {item["declarationId"] for item in declarations}):
            raise PiProviderRefused("original owner result identity differs")
        for item in result.item_results:
            if item.outcome == "applied":
                proof = item.confirmation
                if (not isinstance(proof, Mapping)
                        or not same_reference(proof["unitRef"], unit_ref)
                        or not same_reference(proof["scopeRef"], unit.configuration_target_ref)
                        or proof["requestDigest"] != facts["inputDigest"]):
                    raise PiProviderRefused("original owner result scope or request differs")
        if result.confirmed_snapshot is not None:
            snapshot = result.confirmed_snapshot
            if (not same_reference(snapshot.unit_ref, unit_ref)
                    or not same_reference(snapshot.scope_ref, unit.configuration_target_ref)):
                raise PiProviderRefused("original owner snapshot scope differs")
        return result

    def _confirm_records_change(self, unit_ref, unit, client, context, waiter):
        """Conclude the attempt from the observed native receipt and readback."""
        facts = self._current_configuration(unit, context)
        after, after_facts = self._observe_state(unit, client,
                                                 before_rpc=lambda: self._current_configuration(unit, context))
        receipt = waiter["receipt"]
        request = waiter["request"]
        if (not isinstance(receipt, Mapping) or not isinstance(request, Mapping)
                or receipt.get("id") != request["id"] or receipt.get("command") != request["type"]
                or receipt.get("success") is not True):
            raise PiProviderRefused("original native write receipt or identity unavailable")
        kind = waiter["declaration"]["configurationKind"]
        if after_facts["configuration"].get(kind) != waiter["payload"]:
            raise PiProviderRefused("native readback differs; the ACK is not evidence of effect")
        summary = {"operationRef": facts["operationRef"], "unitRef": plain(unit_ref),
                   "scopeRef": plain(unit.configuration_target_ref),
                   "requestDigest": facts["inputDigest"],
                   "itemOutcomes": [{"declarationId": item["declarationId"],
                                     "outcome": "applied" if item is waiter["declaration"] else "rejected"}
                                    for item in waiter["all"]],
                   "confirmedSnapshot": after.to_dict()}
        evidence = self.configuration_evidence.capture_configuration(
            unit, facts, request, {key: receipt[key] for key in receipt if key in {"id", "type", "command", "success"}},
            waiter["before"], after_facts, summary)
        self._current_configuration(unit, context)
        attempt = self.records.record_configuration_change(waiter["ticket"],
                      expected_source_revision=waiter["attempt_revision"], state="confirmed",
                      evidence=evidence)
        self._configuration_waiters.pop(facts["operationRef"], None)
        result = self.configuration_evidence.read_configuration_result(unit, attempt)
        return self._validate_owner_result(unit_ref, unit, facts, waiter["all"], result)

    def _apply_records_configuration(self, unit_ref, change_request, invocation_context):
        unit = self._unit_record(unit_ref)
        binding, client = self._live(unit_ref, unit)
        effective, rejected = self._compile_change(change_request)
        facts = invocation_context.facts
        if not effective:
            # Consume the original authority even for an explicit no-effect rejection.
            self._authorize_change(unit, invocation_context, "applyConfiguration")
            return ConfigurationChangeResult(facts["operationRef"], tuple(
                ConfigurationItemResult(item["declarationId"], "rejected")
                for item in change_request.declarations))
        with self._lifecycle_lock:
            # Refuse a known stale prerequisite before claiming an attempt.
            # The comparison is against the observed snapshot revision; pi has
            # no native CAS, the owner serialization here is the declared scope.
            preliminary, _ = self._observe_state(unit, client)
            if preliminary.source_revision != change_request.expected_configuration_revision:
                raise ConfigurationRevisionConflict("native configuration version prerequisite differs")
            # The same journal consumes the original applyConfiguration claim itself.
            ticket = self.records.begin_configuration_change(unit.unit_ref, invocation_context,
                          input_digest=facts["inputDigest"],
                          expected_revision=change_request.expected_configuration_revision)
            declaration = effective[0]
            kind, payload = declaration["configurationKind"], declaration.get("payload")
            command, fields = (("set_model", {"provider": payload["provider"], "modelId": payload["model"]})
                               if kind == "pi.model"
                               else ("set_thinking_level", {"level": payload["level"]}))
            waiter = {"ticket": ticket, "declaration": declaration, "kind": kind, "payload": payload,
                      "all": change_request.declarations,
                      "attempt_revision": 1, "request": None, "receipt": None, "before": None}
            self._configuration_waiters[facts["operationRef"]] = waiter
            try:
                before, before_facts = self._observe_state(
                    unit, client, before_rpc=lambda: self._current_configuration(unit, invocation_context))
                if before.source_revision != change_request.expected_configuration_revision:
                    raise ConfigurationRevisionConflict("native configuration changed before dispatch")
                waiter["before"] = before_facts
                frame = client.prepare_request(command, fields)
                def before_write(wire):
                    self._current_configuration(unit, invocation_context)
                    request = json.loads(wire)
                    attempt = self.records.bind_configuration_dispatch(ticket,
                                  native_request_id=frame.request_id,
                                  native_request_digest=_digest(request))
                    waiter["attempt_revision"] = attempt.source_revision
                    waiter["request"] = request
                    self._current_configuration(unit, invocation_context)
                waiter["receipt"] = client.dispatch_prepared(frame, before_write=before_write)
                return self._confirm_records_change(unit_ref, unit, client, invocation_context, waiter)
            except Exception:
                try:
                    attempt = self.records.record_configuration_change(waiter["ticket"],
                                  expected_source_revision=waiter["attempt_revision"], state="unknown")
                    waiter["attempt_revision"] = attempt.source_revision
                except Exception:
                    pass  # never downgrade a concurrently confirmed original receipt
                return self._unknown_change(facts, change_request.declarations)

    def _query_records_change(self, unit_ref, operation_ref, authorized_read_context):
        unit = self._unit_record(unit_ref)
        facts = authorized_read_context.facts
        with self._lifecycle_lock:
            attempt = self.records.query_configuration_change(unit.unit_ref, operation_ref,
                           authorized_read_context, input_digest=facts["inputDigest"])
            declarations = facts["contextRef"].get("effectiveDeclarations", ())
            self._current_configuration(unit, authorized_read_context)
            if attempt.state == "confirmed":
                result = self.configuration_evidence.read_configuration_result(unit, attempt)
                return self._validate_owner_result(unit_ref, unit, facts, declarations, result)
            waiter = self._configuration_waiters.get(operation_ref)
            if (waiter is None or waiter.get("request") is None
                    or attempt.native_request_id != waiter["request"].get("id")):
                return self._unknown_change(facts, declarations)
            binding, client = self._live(unit_ref, unit)
            try:
                if waiter.get("receipt") is None:
                    raise PiProviderRefused("original native receipt still missing")
                self._current_configuration(unit, authorized_read_context)
                return self._confirm_records_change(unit_ref, unit, client,
                                                    authorized_read_context, waiter)
            except Exception:
                return self._unknown_change(facts, declarations)

    def apply_configuration(self, unit_ref, change_request, invocation_context):
        if "apply_configuration" not in self.descriptor.supported_methods:
            raise PiProviderRefused("typed request and existing owner confirmation journal required")
        if not isinstance(change_request, ConfigurationChangeRequest):
            raise PiProviderRefused("typed request and existing owner confirmation journal required")
        if self._owner is not None:
            return self._apply_owner_configuration(unit_ref, change_request, invocation_context)
        return self._apply_records_configuration(unit_ref, change_request, invocation_context)

    def _apply_owner_configuration(self, unit_ref, change_request, invocation_context):
        unit = self.inspect_unit(unit_ref)
        with self._owner.serialize_configuration(unit_ref):
            facts = self._authorize(unit, invocation_context, "applyConfiguration")
            before = self._snapshot(unit)
            if before.source_revision != change_request.expected_configuration_revision:
                return ConfigurationChangeResult(facts["operationRef"], tuple(
                    ConfigurationItemResult(item["declarationId"], "conflict") for item in change_request.declarations))
            if any(item["requirement"] == "required" and not self._valid_declaration(item)
                   for item in change_request.declarations):
                return ConfigurationChangeResult(facts["operationRef"], tuple(
                    ConfigurationItemResult(item["declarationId"], "rejected") for item in change_request.declarations))
            results, latest, uncertain = [], before, False
            for declaration in change_request.declarations:
                kind, payload = declaration["configurationKind"], declaration.get("payload")
                valid = self._valid_declaration(declaration)
                if not valid or uncertain:
                    results.append(ConfigurationItemResult(declaration["declarationId"], "unknown" if uncertain else "rejected"))
                    continue
                try:
                    # No ACK is used as proof. Native command and observed state
                    # must both agree; any lost receipt retains unknown outcome.
                    if self._owner.revalidate_write(invocation_context, facts, unit_ref) is not True:
                        raise PiProviderRefused("current native writer authority changed")
                    if kind == "pi.model":
                        self._owner.channel(unit_ref).command("set_model", provider=payload["provider"], modelId=payload["model"])
                    else:
                        self._owner.channel(unit_ref).command("set_thinking_level", level=payload["level"])
                    after = self._snapshot(unit)
                    if after.configuration.get(kind) != payload:
                        raise PiProviderRefused("native readback differs")
                    evidence = self._confirmations.record(facts, unit, declaration, latest, after)
                    confirmation = {"operationRef": facts["operationRef"], "unitRef": unit_ref,
                        "scopeRef": unit.configuration_target_ref, "requestDigest": facts["inputDigest"], "evidenceRef": evidence}
                    results.append(ConfigurationItemResult(declaration["declarationId"], "applied", confirmation))
                    latest = after
                except Exception:
                    uncertain = True
                    results.append(ConfigurationItemResult(declaration["declarationId"], "unknown"))
            return ConfigurationChangeResult(facts["operationRef"], tuple(results), latest if not uncertain else None)

    def query_change(self, unit_ref, operation_ref, authorized_read_context):
        if self._owner is not None:
            return self._query_owner_change(unit_ref, operation_ref, authorized_read_context)
        self._required('query_change')
        return self._query_records_change(unit_ref, operation_ref, authorized_read_context)

    def _query_owner_change(self, unit_ref, operation_ref, authorized_read_context):
        unit = self.inspect_unit(unit_ref)
        facts = self._authorize(unit, authorized_read_context, "query", query=True)
        if facts["operationRef"] != operation_ref:
            raise PiProviderRefused("original operation identity differs")
        result = self._confirmations.read(facts, unit, operation_ref)
        if not isinstance(result, ConfigurationChangeResult) or result.operation_ref != operation_ref:
            raise PiProviderRefused("original native attempt confirmation unavailable")
        for item in result.item_results:
            if item.confirmation is not None and (not same_reference(item.confirmation["unitRef"], unit_ref)
                    or not same_reference(item.confirmation["scopeRef"], unit.configuration_target_ref)
                    or item.confirmation["requestDigest"] != facts["inputDigest"]):
                raise PiProviderRefused("original native receipt target differs")
        return result

    def _unsupported(self, *args, **kwargs):
        raise PiProviderRefused("capability requires verified production Unit composition")

    def _unknown_creation(self):
        raise PiProviderRefused("native creation outcome unknown; query original operation") from None

    inspect_installation = assess_configuration = _unsupported
    recover = _unsupported
