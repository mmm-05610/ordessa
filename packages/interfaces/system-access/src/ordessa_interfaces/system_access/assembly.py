"""Generic host assembly: discovery + registry + dispatch, no domain imports."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ordessa_interfaces_contracts import (
    OperationResult, envelope_from_result,
)

from .discovery import load_capabilities
from .operations import RequestContext, invoke
from .registry import CapabilityRegistry, build_registry


@dataclass(frozen=True)
class CapabilityHost:
    """One published registry and its generic dispatch entry points."""

    registry: CapabilityRegistry
    allowlist: tuple[str, ...]

    @property
    def capabilities(self) -> Mapping[str, object]:
        return self.registry.capabilities

    @property
    def operations(self) -> Mapping[str, object]:
        return self.registry.operations

    async def call(self, operation_id: str, request: Mapping[str, object],
                   context: RequestContext) -> OperationResult:
        return await invoke(self.registry, operation_id, request, context)

    def envelope(self, *, command: str, request_id: str, result: OperationResult) -> dict:
        return envelope_from_result(request_id=request_id, command=command, result=result)

    def close(self) -> None:
        self.registry.freeze()


def build_host(allowlist: Iterable[str], bindings: Mapping[str, object], *,
               entry_points=None) -> CapabilityHost:
    """Load the allowlisted factories and publish their validated capabilities."""
    names = tuple(allowlist)
    capabilities = load_capabilities(names, bindings, entry_points=entry_points)
    registry = build_registry(capabilities)
    return CapabilityHost(registry=registry, allowlist=names)


__all__ = ['CapabilityHost', 'build_host']
