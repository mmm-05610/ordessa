"""Explicit production owner assembly for the Agent Tools deployment.

This is the ONLY module of the deployment that imports the original records
owner (``ordessa_units.records``). The default Profile/discovery deployment
never imports this module, so it neither imports nor creates a records owner.

The owner-ports factory supplies the trusted authority/evidence ports. This
module assembles, exactly once, the invocation issuer on the environment's
original store object, one verifier instance consumed by both the records
owner and the providers, and the original OperationJournal/UnitRecords on the
canonical journal path — no second recovery database.

``OwnerPorts`` carries only trust ports: it never carries an issuer, verifier
or records instance, so no second store/issuer/verifier can be mixed in
through the factory. Mixing attempts at the records boundary are refused by
the original single scope-authority and admission pins.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


from ordessa_units.public import (
    InvocationIssuer,
    InvocationCurrentStatePort,
    InvocationAuthorityPort,
    AgentOwnerInputs, AgentOwnerPorts, AgentProviderView, bind_unit_manager,
    validate_agent_owner_inputs,
)
from ordessa_units.definitions.admission_identity import AdmissionNamespace

# Optional evidence ports are validated by the original method surface each
# consumer calls; a present-but-unusable port is refused, never silently
# treated as an absent optional.
_PORT_METHODS = {
    "scope_authority": ("issue_scope", "verify_scope", "map_legacy_scope"),
    "native_session_evidence": ("verify_binding",),
    "management_epoch": ("current_epoch",),
    "node_evidence_port": ("inspect",),
    "preparation_context_port": ("resolve",),
    "preparation_observation_port": ("observe",),
    "lifecycle_observation_port": ("observe",),
    "configuration_evidence": ("verify_configuration",),
    "native_unit_evidence": ("verify_unit_binding",),
    "input_association_evidence": ("verify_association",),
    "termination_evidence": ("verify_termination",),
}
_REQUIRED_PORTS = ("authority", "current_state", "scope_authority",
                   "native_session_evidence", "management_epoch",
                   "node_evidence_port", "preparation_context_port",
                   "preparation_observation_port")
_OPTIONAL_PORTS = ("lifecycle_observation_port", "configuration_evidence", "native_unit_evidence",
                   "input_association_evidence", "termination_evidence")


class OwnerAssemblyRefused(RuntimeError):
    """The explicit owner assembly is incomplete or internally inconsistent."""
    code = "GUARANTEE_UNAVAILABLE"


@dataclass(frozen=True)
class OwnerPorts:
    """Trusted authority/evidence ports for one production owner assembly."""
    authority: Any
    current_state: Any
    scope_authority: Any
    native_session_evidence: Any
    management_epoch: Any
    node_evidence_port: Any
    preparation_context_port: Any
    preparation_observation_port: Any
    lifecycle_observation_port: Any = None
    configuration_evidence: Any = None
    native_unit_evidence: Any = None
    input_association_evidence: Any = None
    termination_evidence: Any = None
    close: Callable[[], None] | None = None
    fresh_unit_factory: Any = None
    acp_turn_opt_in: bool = False


@dataclass(frozen=True)
class OwnerProviderView:
    """Provider-facing view of one assembled owner: verification only.

    Never carries the invocation issuer: providers consume verified facts and
    records, they can never issue grants or tickets.
    """
    records: Any
    verifier: Any


@dataclass(frozen=True)
class AssembledOwner:
    """The single owner of one environment's issuer/verifier/journal/records."""
    issuer: Any
    verifier: Any
    journal: Any
    records: Any
    ports: OwnerPorts
    service_ports: AgentOwnerPorts

    @property
    def provider_view(self) -> OwnerProviderView:
        return OwnerProviderView(records=self.records, verifier=self.verifier)

    def revoke(self):
        """Revoke live permission, preserving any owner-callback failure.

        The optional owner close callback (fencing its native transport) may
        fail or re-enter environment close; the issuer tickets are revoked
        regardless and the first error is raised afterwards.
        """
        first_error = None
        callback = self.ports.close
        if callback is not None:
            if not callable(callback):
                raise OwnerAssemblyRefused("owner close callback must be callable")
            try:
                callback()
            except BaseException as exc:  # noqa: BLE001 - preserved, chain continues
                first_error = exc
        try:
            self.issuer.close()
        except BaseException as exc:  # noqa: BLE001
            first_error = first_error or exc
        if first_error is not None:
            raise first_error


def validate_owner_ports(ports: Any) -> OwnerPorts:
    if not isinstance(ports, OwnerPorts):
        raise OwnerAssemblyRefused("owner ports factory must return OwnerPorts")
    if ports.fresh_unit_factory is not None:
        validate_agent_owner_inputs(_fresh_inputs(ports))
        return ports
    if ports.acp_turn_opt_in is not False:
        raise OwnerAssemblyRefused('ACP opt-in requires explicit fresh Unit selection')
    for name in _REQUIRED_PORTS:
        if getattr(ports, name, None) is None:
            raise OwnerAssemblyRefused(f"owner port {name!r} is required")
    if not isinstance(ports.authority, InvocationAuthorityPort):
        raise OwnerAssemblyRefused("owner authority port is not an InvocationAuthorityPort")
    if not isinstance(ports.current_state, InvocationCurrentStatePort):
        raise OwnerAssemblyRefused("owner current-state port is not an InvocationCurrentStatePort")
    for name, methods in _PORT_METHODS.items():
        port = getattr(ports, name, None)
        if port is None:
            if name in _REQUIRED_PORTS:
                raise OwnerAssemblyRefused(f"owner port {name!r} is required")
            continue
        for method in methods:
            if not callable(getattr(port, method, None)):
                raise OwnerAssemblyRefused(
                    f"owner port {name!r} exposes no callable {method!r}")
    for name in _OPTIONAL_PORTS:
        port = getattr(ports, name, None)
        if port is not None:
            for method in _PORT_METHODS[name]:
                if not callable(getattr(port, method, None)):
                    raise OwnerAssemblyRefused(
                        f"owner port {name!r} exposes no callable {method!r}")
    if ports.close is not None and not callable(ports.close):
        raise OwnerAssemblyRefused("owner close callback must be callable")
    return ports


def _fresh_inputs(ports):
    return AgentOwnerInputs(**{name: getattr(ports, name) for name in (
        'authority', 'current_state', 'scope_authority', 'native_session_evidence',
        'management_epoch', 'node_evidence_port', 'preparation_context_port',
        'preparation_observation_port', 'lifecycle_observation_port',
        'configuration_evidence', 'native_unit_evidence', 'input_association_evidence',
        'termination_evidence', 'close', 'fresh_unit_factory', 'acp_turn_opt_in')})


def assemble_owner(environment: Any, ports: Any, journal: Any) -> AssembledOwner:
    """Build the one issuer/verifier/records triple on the original objects."""
    ports = validate_owner_ports(ports)
    store_port = getattr(environment, "store_port", None)
    if store_port is None:
        raise OwnerAssemblyRefused(
            "the owner assembly requires the environment's explicit store port")
    issuer = InvocationIssuer(store_port, ports.authority, ports.current_state)
    if getattr(issuer, "_store", None) is not store_port:
        raise OwnerAssemblyRefused("invocation issuer did not bind the environment store")
    verifier = issuer.verifier()  # created exactly once
    bound = getattr(verifier, "_verify", None)
    if bound is None or getattr(bound, "__self__", None) is not issuer:
        raise OwnerAssemblyRefused("verifier is not bound to this issuer")
    try:
        from ordessa_units.records import UnitRecords
        records = UnitRecords(
            journal,
            scope_authority=ports.scope_authority,
            native_evidence=ports.native_session_evidence,
            verifier=verifier,
            epoch_port=ports.management_epoch,
            configuration_evidence=ports.configuration_evidence,
            native_unit_evidence=ports.native_unit_evidence,
            input_association_evidence=ports.input_association_evidence,
            termination_evidence=ports.termination_evidence,
            acp_turn_opt_in=ports.acp_turn_opt_in,
        )
        if records.verifier is not verifier or records.journal is not journal:
            raise OwnerAssemblyRefused("records owner must consume the single verifier and journal")
        view = AgentProviderView(records, verifier)
        manager = None
        if ports.fresh_unit_factory is not None:
            attach = getattr(ports.native_session_evidence, 'attach_owner', None)
            if callable(attach):
                attach(records)
            manager = bind_unit_manager(_fresh_inputs(ports),
                environment_id=AdmissionNamespace(environment.environment_id), provider_view=view)
        bundle = AgentOwnerPorts(issuer, view, node_evidence_port=ports.node_evidence_port,
            preparation_context_port=ports.preparation_context_port,
            preparation_observation_port=ports.preparation_observation_port,
            lifecycle_observation_port=ports.lifecycle_observation_port, unit_manager=manager)
        bundle.validate_for(environment)
        return AssembledOwner(issuer=issuer, verifier=verifier, journal=journal,
                              records=records, ports=ports, service_ports=bundle)
    except BaseException as original_error:
        try:
            issuer.close()
        except BaseException as cleanup_error:
            original_error.owner_cleanup_error = cleanup_error
        raise


def canonical_journal_path(core_store_path: Any) -> Path:
    """The original canonical journal location under this deployment's root."""
    root = Path(core_store_path).resolve().parent.parent
    return root / "plugins" / "profile" / "native-configuration.sqlite"


__all__ = ["OwnerPorts", "OwnerProviderView", "AssembledOwner", "OwnerAssemblyRefused",
           "validate_owner_ports", "assemble_owner", "canonical_journal_path"]
