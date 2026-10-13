"""Trusted composition binding to the existing implementation effect owner.

This is a consumer port, not an execution contract or another dispatch engine.
Only the service's finite admitted operation names are passed to it. Native
payloads/results and original effect/write/journal guards stay with that owner.
"""
from typing import Protocol
from .repositories import CommandAccessPort
from .transactions import UoWFactory

# Dispatch is served only by the canonical ExecutionDispatchPort. The original
# reconciliation/readback ports retain their distinct admitted operations.
IMPLEMENTATION_COMMANDS = ("engineering.implementation.reconcile",)
IMPLEMENTATION_QUERIES = ("engineering.implementation.get_dispatch",)


class ImplementationRoutesPort(Protocol):
    factory: UoWFactory
    access: CommandAccessPort

    def invoke(self, operation, parameters, context): ...


__all__ = ["ImplementationRoutesPort", "IMPLEMENTATION_COMMANDS", "IMPLEMENTATION_QUERIES"]
