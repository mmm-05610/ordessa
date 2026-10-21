"""Explicit, neutral assembly capabilities attached to a plugin selection.

This extends the existing server_plugins sequence seam without passing a
product object or any domain composition bag to the host. Bare sequences
retain their existing host-only semantics.
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .root_ownership import RootOwnershipPort

@dataclass(frozen=True)
class ServerPluginSelection(Sequence[Any]):
    plugins: tuple[Any, ...]
    contribution_points: tuple[Any, ...] = ()
    environment_factory: Callable[[Path], Any] | None = None
    owned_environment_factory: Callable[[Path, RootOwnershipPort], Any] | None = None
    # Core-owned public method descriptors share the host's sole registry.
    # The resolver supplied by the host returns its current-round Environment.
    # No plugin activation or second dispatcher is created by this capability.
    core_method_factory: Callable[[Callable[[], Any]], tuple[Any, ...]] | None = None

    def __len__(self):
        return len(self.plugins)

    def __getitem__(self, index):
        return self.plugins[index]
