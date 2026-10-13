"""Contract-owned boundary views of configuration-side mechanism values.

These are structural interfaces, not second models: the owning mechanism
(``harness.configuration.materialization``) keeps the concrete implementations
(``MergeAuthority``, ``PublishedGeneration``). The boundary declares only the
surface it actually uses, so ``contracts`` has **no** runtime or typing
dependency on the mechanism that produces these values.
"""
from __future__ import annotations

from typing import Protocol

from ordessa_execution_agents.harness.definitions import ActionDescriptor


class ConfigurationAuthorityView(Protocol):
    """Boundary view of the server-supplied merge-authority snapshot.

    The concrete ``MergeAuthority`` (configuration mecanism) satisfies this.
    Only the fields read across the boundary are declared.
    """
    scope: str
    actions: tuple[ActionDescriptor, ...]


class PublishedGenerationLease(Protocol):
    """Boundary view of a published generation lease.

    A lease is fd-bound; bytes are digest-checked by the owning mechanism. The
    runtime adapter may read the manifest and bytes but never re-resolve a path.
    """
    generation_name: str
    files: tuple[tuple[tuple[str, ...], str], ...]

    def fileno(self) -> int: ...
    def read_bytes(self, parts: tuple[str, ...]) -> bytes: ...
    def close(self) -> None: ...
    def __enter__(self) -> "PublishedGenerationLease": ...
    def __exit__(self, *unused: object) -> None: ...
