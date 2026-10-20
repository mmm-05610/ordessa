"""Assemble one Units owner over caller-provisioned original owners.

The caller supplies the already-open OperationJournal. This module creates no
filesystem paths, stores, grants, environment resources, or application ports;
the Environment store, issuer, records, and optional UnitManager are each
bound once here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ordessa_units.definitions.admission_identity import AdmissionNamespace

from ordessa_units.admission.owner_ports import AgentOwnerPorts, AgentProviderView
from ordessa_units.admission.owner_selection import (
    AgentOwnerInputs,
    AgentOwnerUnavailable,
    bind_unit_manager,
    validate_agent_owner_inputs,
)
from ordessa_units.admission.invocation import InvocationIssuer
from ordessa_units.records import OperationJournal, UnitRecords


@dataclass
class AssembledUnitOwner:
    """The single execution owner and its existing injected service ports."""

    ports: AgentOwnerPorts
    issuer: InvocationIssuer
    verifier: Any
    journal: OperationJournal
    records: UnitRecords
    provider_factory: Callable[[Any, AgentProviderView], Any] | None
    close_callback: Callable[[], None] | None = None
    _revoked: bool = False

    @property
    def provider_view(self) -> AgentProviderView:
        return AgentProviderView(self.records, self.verifier)

    def revoke(self) -> None:
        """Revoke this assembly's live authority; leave caller-owned journal open."""
        if self._revoked:
            return
        self._revoked = True
        first_error = None
        if self.close_callback is not None:
            try:
                self.close_callback()
            except BaseException as exc:
                first_error = exc
        try:
            self.issuer.close()
        except BaseException as exc:
            first_error = first_error or exc
        if first_error is not None:
            raise first_error


def assemble_unit_owner(admission_context, inputs: AgentOwnerInputs, *,
                        journal: OperationJournal) -> AssembledUnitOwner:
    """Bind one pre-provisioned journal and the admission context's original store.

    Journal creation, private-path validation and exclusive file acquisition
    belong to the caller that owns those host resources. This builder only
    assembles execution-owned records and live authority on those exact inputs.
    """
    validate_agent_owner_inputs(inputs)
    check_open = getattr(admission_context, "check_open", None)
    if not callable(check_open):
        raise AgentOwnerUnavailable("original Unit admission context is required")
    check_open()
    store = getattr(admission_context, "store_port", None)
    namespace = getattr(admission_context, "environment_namespace", None)
    if store is None or not isinstance(namespace, str) or not namespace:
        raise AgentOwnerUnavailable("original Unit store and namespace are required")
    if type(journal) is not OperationJournal:
        raise AgentOwnerUnavailable("caller-provisioned original OperationJournal is required")
    if not journal.new_unit_admission_valid(namespace):
        raise AgentOwnerUnavailable("original Unit owner requires its pristine pre-opened journal")

    # These checks bind the selection's original local authority/current-state
    # owners to this context without manufacturing replacements.
    for label, owner in (("invocation authority", inputs.authority),
                         ("current-state owner", inputs.current_state)):
        owner_store = getattr(owner, "store", store)
        if owner_store is not store:
            raise AgentOwnerUnavailable(f"{label} belongs to another original store")
    owner_context = getattr(inputs.preparation_context_port, "admission", admission_context)
    if owner_context is not admission_context:
        raise AgentOwnerUnavailable("Unit selection belongs to another admission context")
    current_namespace = getattr(inputs.current_state, "environment_namespace", namespace)
    if current_namespace != namespace:
        raise AgentOwnerUnavailable("Unit selection belongs to another Environment namespace")

    managed_turn_opt_in = (inputs.managed_capture_content_port is not None
                           and inputs.workspace_execution_port is not None)
    if (journal.managed_turn_opt_in is not managed_turn_opt_in
            or journal.acp_turn_opt_in is not inputs.acp_turn_opt_in):
        raise AgentOwnerUnavailable("journal schema opt-ins differ from the selected original owner")
    attached_records = getattr(inputs.native_session_evidence, "records", None)
    if attached_records is not None:
        raise AgentOwnerUnavailable("native evidence is already bound to an original UnitRecords owner")

    issuer = None
    try:
        issuer = InvocationIssuer(store, inputs.authority, inputs.current_state)
        verifier = issuer.verifier()
        records = UnitRecords(
            journal,
            scope_authority=inputs.scope_authority,
            native_evidence=inputs.native_session_evidence,
            verifier=verifier,
            epoch_port=inputs.management_epoch,
            configuration_evidence=inputs.configuration_evidence,
            native_unit_evidence=inputs.native_unit_evidence,
            input_association_evidence=inputs.input_association_evidence,
            termination_evidence=inputs.termination_evidence,
            managed_turn_opt_in=managed_turn_opt_in,
            acp_turn_opt_in=inputs.acp_turn_opt_in,
        )
        if (issuer._store is not store or records.journal is not journal
                or records.verifier is not verifier):
            raise AgentOwnerUnavailable("Unit owner identity diverged during assembly")

        view = AgentProviderView(records, verifier)
        ports = AgentOwnerPorts(
            issuer=issuer,
            provider_view=view,
            node_evidence_port=inputs.node_evidence_port,
            preparation_context_port=inputs.preparation_context_port,
            preparation_observation_port=inputs.preparation_observation_port,
            lifecycle_observation_port=inputs.lifecycle_observation_port,
            input_capture_port=inputs.input_capture_port,
            native_input_state_port=inputs.native_input_state_port,
            first_input_observation_port=inputs.first_input_observation_port,
            managed_capture_content_port=inputs.managed_capture_content_port,
            workspace_execution_port=inputs.workspace_execution_port,
        )
        ports.validate_for(admission_context)
        manager = None
        if inputs.fresh_unit_factory is not None:
            manager = bind_unit_manager(
                inputs, environment_id=AdmissionNamespace(namespace), provider_view=view
            )
            attach_owner = getattr(inputs.native_session_evidence, "attach_owner", None)
            if callable(attach_owner):
                attach_owner(records)
            ports = AgentOwnerPorts(
                issuer=issuer,
                provider_view=view,
                unit_manager=manager,
                node_evidence_port=inputs.node_evidence_port,
                preparation_context_port=inputs.preparation_context_port,
                preparation_observation_port=inputs.preparation_observation_port,
                lifecycle_observation_port=inputs.lifecycle_observation_port,
                input_capture_port=inputs.input_capture_port,
                native_input_state_port=inputs.native_input_state_port,
                first_input_observation_port=inputs.first_input_observation_port,
                managed_capture_content_port=inputs.managed_capture_content_port,
                workspace_execution_port=inputs.workspace_execution_port,
            )
        ports.validate_for(admission_context)
        return AssembledUnitOwner(
            ports, issuer, verifier, journal, records, inputs.provider_factory, inputs.close
        )
    except BaseException:
        if issuer is not None:
            try:
                issuer.close()
            except BaseException:
                pass
        # Borrowed resources remain open; never fake file cleanup or outcomes.
        raise


__all__ = ["AssembledUnitOwner", "assemble_unit_owner"]
