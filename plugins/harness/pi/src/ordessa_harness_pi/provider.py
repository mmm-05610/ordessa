"""Pi-owned configuration confirmation over a deployment-owned live Unit.

The deployment supplies the existing Unit authority, serializer and journal
receipt ports. No fallback launch, configuration cache or extra operation store
exists here. Native effects use the core's consumed InvocationContext.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Mapping, Protocol

from ordessa_environment_api.operations import safe_json
from pacthold.agents.configuration import (
    ConfigurationChangeRequest, ConfigurationChangeResult, ConfigurationDescription,
    ConfigurationItemResult, ConfigurationSnapshot, UnitInspection,
)
from pacthold.core.lifecycle import RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
from pacthold.agents.invocation import InvocationVerifier


class PiProviderRefused(RuntimeError):
    code = "PI_PROVIDER_UNAVAILABLE"


class UnitOwnerPort(Protocol):
    """Trusted deployment binding to existing Unit/authority, never caller data."""
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


class PiRuntimeProvider:
    """Versioned provider with only actually wired methods advertised.

    Preparation/start/recovery currently require further trusted composition and
    are deliberately unsupported. Configuration support requires explicit ports;
    methods exist to satisfy the runtime protocol, never imply capability.
    """
    def __init__(self, *, definition_ref, implementation_digest, owner=None, confirmations=None, verifier=None):
        owner_methods = ("inspect_unit", "channel", "verify_session", "serialize_configuration", "revalidate_write")
        if owner is not None and any(not callable(getattr(owner, name, None)) for name in owner_methods):
            raise PiProviderRefused("complete trusted Unit owner ports required")
        if confirmations is not None and any(not callable(getattr(confirmations, name, None)) for name in ("record", "read")):
            raise PiProviderRefused("complete existing owner confirmation ports required")
        if verifier is not None and not isinstance(verifier, InvocationVerifier):
            raise PiProviderRefused("existing core InvocationVerifier required")
        self._owner, self._confirmations, self._verifier = owner, confirmations, verifier
        supported = ["describe_definition", "describe_configuration"]
        if owner is not None:
            supported += ["inspect_unit", "inspect_configuration"]
            if confirmations is not None and verifier is not None:
                supported += ["apply_configuration", "query_change"]
        self.descriptor = RuntimeProviderDescriptor("pi", RUNTIME_PROVIDER_VERSION,
                            definition_ref, implementation_digest, tuple(supported))

    def describe_definition(self, definition_ref):
        if definition_ref != self.descriptor.definition_ref:
            raise PiProviderRefused("definition reference differs")
        return {"definitionRef": dict(definition_ref), "familyId": "pi",
                "channel": "pi-rpc/1", "supportedMethods": list(self.descriptor.supported_methods),
                "configurationContract": "agent-configuration/1",
                "nativeVersion": "0.86.1", "runtimeReady": "unknown"}

    def inspect_unit(self, unit_ref):
        if self._owner is None:
            raise PiProviderRefused("trusted current Unit owner is absent")
        unit = self._owner.inspect_unit(unit_ref)
        if not isinstance(unit, UnitInspection) or unit.unit_ref != unit_ref or unit.provider_ref.get("providerId") != "pi":
            raise PiProviderRefused("current Pi Unit evidence differs")
        return unit

    def describe_configuration(self, unit_ref):
        if self._owner is not None:
            self.inspect_unit(unit_ref)
        wired = self._owner is not None and self._confirmations is not None and self._verifier is not None
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
        unit = self.inspect_unit(unit_ref)
        with self._owner.serialize_configuration(unit_ref):
            return self._snapshot(unit)

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
                or facts.get("action") != action or facts.get("providerRef") != unit.provider_ref
                or facts.get("managementEpoch") != unit.management_epoch
                or not _text(facts.get("operationRef")) or not _text(facts.get("inputDigest"))):
            raise PiProviderRefused("verified core invocation facts differ")
        return facts

    def apply_configuration(self, unit_ref, change_request, invocation_context):
        if self._confirmations is None or not isinstance(change_request, ConfigurationChangeRequest):
            raise PiProviderRefused("typed request and existing owner confirmation journal required")
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
        if self._confirmations is None:
            raise PiProviderRefused("original owner confirmation journal unavailable")
        unit = self.inspect_unit(unit_ref)
        facts = self._authorize(unit, authorized_read_context, "query", query=True)
        if facts["operationRef"] != operation_ref:
            raise PiProviderRefused("original operation identity differs")
        result = self._confirmations.read(facts, unit, operation_ref)
        if not isinstance(result, ConfigurationChangeResult) or result.operation_ref != operation_ref:
            raise PiProviderRefused("original native attempt confirmation unavailable")
        for item in result.item_results:
            if item.confirmation is not None and (item.confirmation["unitRef"] != unit_ref
                    or item.confirmation["scopeRef"] != unit.configuration_target_ref
                    or item.confirmation["requestDigest"] != facts["inputDigest"]):
                raise PiProviderRefused("original native receipt target differs")
        return result

    def _unsupported(self, *args, **kwargs):
        raise PiProviderRefused("capability requires verified production Unit composition")

    inspect_installation = assess_configuration = plan_preparation = _unsupported
    prepare = start = query_step = describe_access = connect = _unsupported
    stop = release = recover = _unsupported
