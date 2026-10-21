"""Cross-boundary structural ports for controlled runtime and permits.

Protocols only: they name the methods a deployed implementation must supply.
They acquire no authority, open no connection and execute no effect. The
configuration lease and native receipt are named through contract-owned
structural views (``contracts.ports``), not the mechanism's concrete types.
"""
from __future__ import annotations

from typing import Protocol

from ordessa_agents.harness.definitions import ApplicationTarget, Plan

from ordessa_agents.harness.contracts.models.application import NativeReadback, RuntimeSnapshot
from ordessa_agents.harness.contracts.ports.configuration import PublishedGenerationLease
from ordessa_agents.harness.contracts.ports.records import NativeActivationReceiptView


class ControlledRuntime(Protocol):
    def capture(self, target: ApplicationTarget) -> RuntimeSnapshot: ...
    def activate_generation(self, operation_id: str, target: ApplicationTarget,
                            lease: PublishedGenerationLease,
                            manifest_digest: str) -> NativeActivationReceiptView: ...
    def observe(self, target: ApplicationTarget) -> NativeReadback: ...


class PermitVerifier(Protocol):
    def verify(self, principal: str, target: ApplicationTarget, plan: Plan,
               operation_key: str, permit: str) -> bool: ...
