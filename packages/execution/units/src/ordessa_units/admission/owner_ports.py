"""Typed, identity-preserving inputs for one Agent owner assembly.

This module is deliberately a carrier only.  It does not import a product,
Harness brand, database implementation, or records distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentProviderView:
    """The provider-facing view of the original deployment owner."""
    records: Any
    verifier: Any


@dataclass(frozen=True)
class AgentOwnerPorts:
    """One already-assembled owner and its Pacthold injection ports.

    ``issuer`` is held for identity validation and SDK services; providers
    receive only ``provider_view`` and therefore cannot mint grants.
    """
    issuer: Any
    provider_view: AgentProviderView
    node_evidence_port: Any = None
    preparation_context_port: Any = None
    preparation_observation_port: Any = None
    lifecycle_observation_port: Any = None
    input_capture_port: Any = None
    native_input_state_port: Any = None
    first_input_observation_port: Any = None
    managed_capture_content_port: Any = None
    workspace_execution_port: Any = None
    unit_manager: Any = None

    def validate_for(self, environment: Any) -> None:
        store = getattr(environment, "_store", None)
        if store is None or getattr(self.issuer, "_store", None) is not store:
            raise ValueError("Agent owner issuer must use this Environment's original store")
        verifier = self.provider_view.verifier
        verify = getattr(verifier, "_verify", None)
        if verify is None or getattr(verify, "__self__", None) is not self.issuer:
            raise ValueError("Agent provider verifier must belong to the assembled issuer")
        if getattr(self.provider_view.records, "verifier", None) is not verifier:
            raise ValueError("Agent records must use the assembled verifier")
        if self.unit_manager is not None:
            from ordessa_units.management.manager import UnitManager
            if (type(self.unit_manager) is not UnitManager
                    or self.unit_manager.records is not self.provider_view.records
                    or self.unit_manager.verifier is not verifier):
                raise ValueError("Unit Manager must retain the assembled records and verifier")


__all__ = ["AgentProviderView", "AgentOwnerPorts"]
