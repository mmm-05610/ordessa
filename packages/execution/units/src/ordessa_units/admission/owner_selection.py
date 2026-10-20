"""Pure selection inputs and checks for one deployment Agent owner.

This module validates the original explicit ports; it creates no issuer,
Environment, journal, records, root binding or execution permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from ordessa_units.errors import UnitGuaranteeUnavailable
from .owner_ports import AgentProviderView
from .invocation import InvocationAuthorityPort, InvocationCurrentStatePort

class AgentOwnerUnavailable(UnitGuaranteeUnavailable):
    code = "AGENT_OWNER_UNAVAILABLE"


@dataclass(frozen=True)
class FreshUnitFactory:
    """Explicit trusted selection, called only by the original UnitManager.

    The callback receives (environment_id, fixed_plan, provider_view). Binding
    does not call it or grant permission. It must return a fresh UnitInstance
    on the view's records/verifier; Manager retains its original one-shot gate.
    """
    create_instance: Callable
    finalize_effect_write_guard_factory: Callable | None = None

    def __post_init__(self):
        if not callable(self.create_instance):
            raise AgentOwnerUnavailable("explicit fresh Unit factory is required")
        if (self.finalize_effect_write_guard_factory is not None
                and not callable(self.finalize_effect_write_guard_factory)):
            raise AgentOwnerUnavailable("effect-write factory finalizer must be callable")


@dataclass(frozen=True)
class AgentOwnerInputs:
    """Trusted ports only; never accepts an Environment, Store, issuer or records."""
    authority: Any
    current_state: Any
    scope_authority: Any
    native_session_evidence: Any
    management_epoch: Any
    node_evidence_port: Any = None
    preparation_context_port: Any = None
    preparation_observation_port: Any = None
    provider_factory: Callable[[Any, AgentProviderView], Any] | None = None
    lifecycle_observation_port: Any = None
    input_capture_port: Any = None
    managed_capture_content_port: Any = None
    workspace_execution_port: Any = None
    native_input_state_port: Any = None
    first_input_observation_port: Any = None
    configuration_evidence: Any = None
    native_unit_evidence: Any = None
    input_association_evidence: Any = None
    termination_evidence: Any = None
    close: Callable[[], None] | None = None
    fresh_unit_factory: FreshUnitFactory | None = None
    acp_turn_opt_in: bool = False


_REQUIRED = {
    "scope_authority": ("issue_scope", "verify_scope", "map_legacy_scope"),
    "native_session_evidence": ("verify_binding",),
    "management_epoch": ("current_epoch",),
    "preparation_context_port": ("resolve",),
}

_LEGACY_REQUIRED = {
    "node_evidence_port": ("inspect",),
    "preparation_observation_port": ("observe",),
}

_OPTIONAL = {
    "lifecycle_observation_port": ("observe",),
    "input_capture_port": ("inspect",),
    "managed_capture_content_port": ("read_content",),
    "workspace_execution_port": ("authorize_execute", "revalidate_execute"),
    "native_input_state_port": ("inspect",),
    "first_input_observation_port": ("observe",),
    "configuration_evidence": ("verify_configuration", "capture_configuration",
                               "read_configuration_result"),
    "native_unit_evidence": ("verify_unit_binding",),
    "input_association_evidence": ("verify_association",),
    "termination_evidence": ("verify_termination",),
}


def validate_agent_owner_inputs(inputs: AgentOwnerInputs) -> None:
    if not isinstance(inputs, AgentOwnerInputs):
        raise AgentOwnerUnavailable("explicit AgentOwnerInputs are required")
    if not isinstance(inputs.authority, InvocationAuthorityPort):
        raise AgentOwnerUnavailable("invocation authority port is unavailable")
    if not isinstance(inputs.current_state, InvocationCurrentStatePort):
        raise AgentOwnerUnavailable("invocation current-state port is unavailable")
    fresh = inputs.fresh_unit_factory is not None
    if fresh:
        if type(inputs.fresh_unit_factory) is not FreshUnitFactory:
            raise AgentOwnerUnavailable("explicit FreshUnitFactory selection is required")
        if inputs.provider_factory is not None:
            raise AgentOwnerUnavailable("fresh Unit and legacy provider selections cannot be combined")
        if any(getattr(inputs, name) is not None for name in
               ("node_evidence_port", "preparation_observation_port", "lifecycle_observation_port")):
            raise AgentOwnerUnavailable("fresh Unit observations must come from the original Manager")
    elif not callable(inputs.provider_factory):
        raise AgentOwnerUnavailable("public provider factory is unavailable")
    if type(inputs.acp_turn_opt_in) is not bool or inputs.acp_turn_opt_in and not fresh:
        raise AgentOwnerUnavailable("ACP durable opt-in requires explicit fresh Unit selection")
    required = _REQUIRED if fresh else {**_REQUIRED, **_LEGACY_REQUIRED}
    for name, methods in (*required.items(), *_OPTIONAL.items()):
        port = getattr(inputs, name)
        if port is None:
            if name in required:
                raise AgentOwnerUnavailable(f"Agent owner port {name!r} is unavailable")
            continue
        if any(not callable(getattr(port, method, None)) for method in methods):
            raise AgentOwnerUnavailable(f"Agent owner port {name!r} is incomplete")
    if inputs.close is not None and not callable(inputs.close):
        raise AgentOwnerUnavailable("owner close callback is invalid")


def bind_unit_manager(inputs: AgentOwnerInputs, *, environment_id, provider_view: AgentProviderView):
    """Bind the fresh selection after the host creates its original records.

    Creates only one live Manager, no records/store/issuer or native effects.
    Legacy selection is refused rather than reinterpreted or used as fallback.
    """
    from ordessa_units.definitions.admission_identity import AdmissionNamespace
    from ordessa_units.records import UnitRecords
    from ordessa_units.management.manager import UnitManager
    from ordessa_units.management.instance import UnitInstance
    from ordessa_execution_agents.profiles import decode_revision_ref
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    from .invocation import InvocationIssuer, InvocationVerifier

    validate_agent_owner_inputs(inputs)
    if inputs.fresh_unit_factory is None:
        raise AgentOwnerUnavailable("fresh Unit factory selection is unavailable")
    if type(environment_id) is not AdmissionNamespace or type(provider_view) is not AgentProviderView:
        raise AgentOwnerUnavailable("original AdmissionNamespace and AgentProviderView are required")
    records = provider_view.records
    verifier = provider_view.verifier
    issuer = getattr(getattr(verifier, '_verify', None), '__self__', None)
    if (type(verifier) is not InvocationVerifier or type(issuer) is not InvocationIssuer
            or issuer._authority is not inputs.authority
            or issuer._current_state is not inputs.current_state
            or issuer._authority_issuer.get('environmentNamespace') != environment_id.value
            or issuer._closed):
        raise AgentOwnerUnavailable("fresh Unit verifier must belong to the original selected issuer")
    if (type(records) is not UnitRecords or records.verifier is not provider_view.verifier
            or records.scope_authority is not inputs.scope_authority
            or records.native_evidence is not inputs.native_session_evidence
            or records.epoch_port is not inputs.management_epoch
            or records.configuration_evidence is not inputs.configuration_evidence
            or records.native_unit_evidence is not inputs.native_unit_evidence
            or records.input_association_evidence is not inputs.input_association_evidence
            or records.termination_evidence is not inputs.termination_evidence
            or not records.journal.new_unit_admission_valid(environment_id.value)
            or records.acp_turn_available is not inputs.acp_turn_opt_in
            or records.journal.acp_turn_opt_in is not inputs.acp_turn_opt_in):
        raise AgentOwnerUnavailable("fresh Unit binding must retain original selected records and ACP opt-in")
    factory = inputs.fresh_unit_factory.create_instance
    # Capture this immutable view; the factory never sees the mutable inputs
    # carrier or the issuer and cannot substitute another view via wire params.
    def create(plan):
        snapshot = plan['profileSnapshot']
        definition = snapshot['manifest']['harnessDefinitionRef']
        revision = decode_revision_ref(dict(snapshot['ref']))
        if (revision.environment_namespace != environment_id.value
                or definition.get('environmentNamespace') != environment_id.value):
            raise AgentOwnerUnavailable("fixed Profile must belong to the selected Environment")
        unit = factory(environment_id, plan, provider_view)
        if type(unit) is UnitInstance and (
                unit.profile_revision != revision
                or safe_json(unit.descriptor.definition_ref) != safe_json(definition)):
            raise AgentOwnerUnavailable("factory Unit must retain the fixed Profile and Harness definition")
        return unit  # UnitManager additionally checks type, original owners and freshness.

    with records.journal._admission_guard_lock:
        if getattr(records.journal, '_fresh_unit_manager_binding', None) is not None:
            raise AgentOwnerUnavailable("original journal already has a fresh Unit Manager binding")
        creation_preflight = getattr(inputs.preparation_context_port,
                                     "ensure_unit_creation_ready", None)
        has_finalizer = inputs.fresh_unit_factory.finalize_effect_write_guard_factory is not None
        if has_finalizer and not callable(creation_preflight):
            raise AgentOwnerUnavailable("Deferred fresh Unit factory requires original creation preflight")
        if creation_preflight is not None and not callable(creation_preflight):
            raise AgentOwnerUnavailable("Original creation preflight must be callable")
        manager = UnitManager(create_instance=create,
                              records=records, verifier=provider_view.verifier,
                              creation_preflight=creation_preflight if callable(creation_preflight) else None)
        # Live ownership only. A cold journal cannot reconstruct handles.
        records.journal._fresh_unit_manager_binding = manager
        return manager


def validate_agent_owner_selection(fingerprint_port, inputs):
    """Validate the explicitly supplied owner inputs before any host I/O."""
    from ordessa_units.definitions.fingerprints import ProtectedFingerprintPort
    if not isinstance(fingerprint_port, ProtectedFingerprintPort):
        raise AgentOwnerUnavailable("protected fingerprint port is required for Agent composition")
    validate_agent_owner_inputs(inputs)


__all__ = ["AgentOwnerUnavailable", "AgentOwnerInputs", "FreshUnitFactory", "bind_unit_manager",
           "validate_agent_owner_inputs", "validate_agent_owner_selection"]
