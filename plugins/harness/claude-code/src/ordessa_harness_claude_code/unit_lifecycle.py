"""Original Unit journal start/query coordination, not an async execution bridge.

Deployment must provide its owned SDK lifetime/effect barrier. This module
never creates a loop/thread/daemon, copies native truth or closes unknown handles.
Actual processes, SDK operations and receipts belong to the injected original
owner. Controlled test implementations are not production runtime evidence.
"""
from __future__ import annotations

from typing import Mapping

from ordessa_environment_api.operations import safe_json


class ClaudeUnitCoordinationRefused(RuntimeError):
    code = "CLAUDE_UNIT_COORDINATION_REFUSED"


def _methods(port, names):
    return port is not None and all(callable(getattr(port, name, None)) for name in names)


def complete_unit_ref(reference):
    return (isinstance(reference, Mapping)
            and set(reference) == {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}
            and isinstance(reference["ownerProviderRef"], Mapping)
            and all(isinstance(reference[key], str) and bool(reference[key])
                    for key in ("environmentNamespace", "unitId", "sourceRevision")))


class ClaudeUnitCoordinator:
    """Consume an existing claim, retain original owner handles, reconcile only.

    projection.read_unit(ref, context) and resolve_original_start(correlation,
    context) authorize reads from the SAME records. The latter returns a
    UnitReservation, not a latest-session lookup. Both expose .records/.verifier.

    effects.open_owned(unit, opaque_context) returns an owner-retained live
    SDK/channel handle. effects.initialize_owned(unit, handle, opaque_context)
    returns only original native evidence. effects.dispatch_guard(unit, context,
    phase) holds the current native authority through each actual effect. The
    underlying FencedSdkTransport must recheck every SDK-generated write too.
    effects.native_evidence/.records/.verifier must be the existing exact owners.

    observations.query_original_unit(unit, correlation, opaque_query_context)
    returns original evidence or None. It is observation only: never initialize,
    create, send input, close or rebuild. It shares exact records/verifier/owner.
    No port is supplied by default, and no controlled factory is composed here.
    """
    def __init__(self, *, records, verifier, projection, effects=None, observations=None,
                 provider_descriptor):
        self.records, self.verifier, self.projection = records, verifier, projection
        self.effects, self.observations, self.descriptor = effects, observations, provider_descriptor

    def _same_owner(self, port):
        return (port is not None and getattr(port, "records", None) is self.records
                and getattr(port, "verifier", None) is self.verifier
                and getattr(port, "native_evidence", None) is getattr(self.records, "native_unit_evidence", None))

    @property
    def owner_ready(self):
        return (_methods(self.records, ("begin_unit", "record_unit", "read_unit_confirmation", "reconcile_unit_confirmation"))
                and self.verifier is not None and getattr(self.records, "verifier", None) is self.verifier
                and _methods(self.verifier, ("verify_and_consume", "verify_continuation"))
                and _methods(getattr(self.records, "native_unit_evidence", None), ("verify_unit_binding",))
                and _methods(self.projection, ("read_unit",))
                and getattr(self.projection, "records", None) is self.records
                and getattr(self.projection, "verifier", None) is self.verifier)

    @property
    def start_ready(self):
        return (self.owner_ready and self._same_owner(self.effects)
                and _methods(self.effects, ("dispatch_guard", "open_owned", "initialize_owned")))

    @property
    def query_ready(self):
        return (self.owner_ready and self._same_owner(self.observations)
                and _methods(self.projection, ("resolve_original_start",))
                and _methods(self.observations, ("query_original_unit",)))

    def _unit(self, unit, reference, context):
        canonical = getattr(unit, "public_ref", None)
        facts = context.facts
        if (not complete_unit_ref(reference) or not complete_unit_ref(canonical)
                or safe_json(reference) != safe_json(canonical)
                or getattr(unit, "unit_ref", None) != canonical["unitId"]):
            raise ClaudeUnitCoordinationRefused("original Unit source reference differs")
        owner = unit.facts["providerRef"]
        if (safe_json(owner) != safe_json(canonical["ownerProviderRef"])
                or safe_json(owner) != safe_json(facts["providerRef"])
                or safe_json(unit.facts["nodeRef"]) != safe_json(facts["targetRef"])
                or owner.get("providerId") != self.descriptor.provider_id
                or owner.get("contractVersion") != self.descriptor.contract_version
                or owner.get("implementationDigest") != self.descriptor.implementation_digest
                or owner.get("environmentNamespace") != self.descriptor.definition_ref["environmentNamespace"]):
            raise ClaudeUnitCoordinationRefused("original Unit provider or operation target differs")
        return unit

    def _continue(self, unit, context, *, query=False):
        facts = context.facts
        action = "query" if query else "start"
        verified = self.verifier.verify_continuation(context, action, unit.facts["providerRef"],
            unit.facts["nodeRef"], facts["inputDigest"])
        if (not isinstance(verified, Mapping) or verified.get("query") is not query
                or verified.get("action") != action
                or safe_json(verified.get("providerRef")) != safe_json(unit.facts["providerRef"])
                or safe_json(verified.get("targetRef")) != safe_json(unit.facts["nodeRef"])
                or verified.get("inputDigest") != facts["inputDigest"]):
            raise ClaudeUnitCoordinationRefused("original invocation continuation differs")

    def _reply(self, unit, binding=None, context=None):
        reply = {"unitRef": unit.public_ref, "state": "unknown"}
        if binding is not None:
            reply["state"] = binding.state
            if binding.state in {"confirmed", "opening", "unknown"}:
                # The owner projection keeps the OBSERVED original start
                # correlation (durable and recovery forms) for later
                # original-creation queries only.
                registrar = getattr(self.projection, "register_original_start", None)
                if callable(registrar):
                    correlation = getattr(binding, "creation_correlation", None)
                    if correlation:
                        registrar(unit, correlation)
                    if context is not None:
                        recovery = getattr(context, "facts", {}).get("recoveryCorrelation")
                        if recovery and recovery != correlation:
                            registrar(unit, recovery)
            if binding.state == "confirmed":
                reply["evidenceRef"] = binding.native_facts["evidenceRef"]
        return reply

    def start(self, prepared_unit, context):
        if not self.start_ready:
            raise ClaudeUnitCoordinationRefused("owned native Unit start/effect cut unavailable")
        if not isinstance(prepared_unit, Mapping) or set(prepared_unit) != {"unitRef"}:
            raise ClaudeUnitCoordinationRefused("exact original prepared Unit required")
        reference = prepared_unit["unitRef"]
        unit = self._unit(self.projection.read_unit(reference, context), reference, context)
        # Only the existing journal consumes start; duplicate invocation cannot
        # mint another ticket, even if the live handle is absent after restart.
        ticket = self.records.begin_unit(unit.unit_ref, context, input_digest=context.facts["inputDigest"])
        try:
            self._continue(unit, context)
            with self.effects.dispatch_guard(unit, context, "open"):
                self._continue(unit, context)
                handle = self.effects.open_owned(unit, context)
            self._continue(unit, context)
            with self.effects.dispatch_guard(unit, context, "initialize"):
                self._continue(unit, context)
                evidence = self.effects.initialize_owned(unit, handle, context)
            self._continue(unit, context)
            # An ACK/cache/None is not confirmation. Existing owner validates
            # actual process/pipe/installation/root/original initialize/liveness.
            binding = self.records.record_unit(ticket, expected_source_revision=2,
                state="confirmed", evidence=evidence)
            return self._reply(unit, binding, context)
        except BaseException as exc:
            try:
                self.records.record_unit(ticket, expected_source_revision=2, state="unknown")
            except Exception:
                # Lost epoch or a newer owner observation retains opening/known
                # evidence. Never reset it, replace the ticket or destroy handle.
                pass
            if not isinstance(exc, Exception):
                raise
            return self._reply(unit)

    def query(self, correlation, context):
        if not self.query_ready:
            raise ClaudeUnitCoordinationRefused("original native Unit query owner unavailable")
        facts = context.facts
        if correlation != facts.get("recoveryCorrelation") or facts.get("query") is not True:
            raise ClaudeUnitCoordinationRefused("query is not original recovery correlation")
        unit = self.projection.resolve_original_start(correlation, context)
        unit = self._unit(unit, getattr(unit, "public_ref", None), context)
        binding = self.records.read_unit_confirmation(unit.unit_ref, context, input_digest=facts["inputDigest"])
        if binding.state == "confirmed":
            # Read authorization alone cannot settle a different operation.
            # Reconcile also checks the persisted original request/step/digest,
            # even when the actual Unit proof was already confirmed.
            binding = self.records.reconcile_unit_confirmation(unit.unit_ref, context,
                input_digest=facts["inputDigest"], expected_source_revision=binding.source_revision,
                evidence=binding.native_facts["evidenceRef"])
            return self._reply(unit, binding)
        if binding.state not in {"opening", "unknown"}:
            return self._reply(unit)
        self._continue(unit, context, query=True)
        evidence = self.observations.query_original_unit(unit, correlation, context)
        self._continue(unit, context, query=True)
        if evidence is None:
            return self._reply(unit, binding)
        # Only the original journal can compare start request/op/step/input and
        # revision. No start ticket/effect port is used in this cold data path.
        binding = self.records.reconcile_unit_confirmation(unit.unit_ref, context,
            input_digest=facts["inputDigest"], expected_source_revision=binding.source_revision,
            evidence=evidence)
        return self._reply(unit, binding)
