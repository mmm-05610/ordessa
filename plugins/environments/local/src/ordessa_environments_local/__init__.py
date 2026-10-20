"""Local (``isolation=none``) execution environment provider.

The only environment implementation required for v1. It owns real OS processes,
their bidirectional byte streams and a bounded local file area, and it reports
``isolation="none"`` honestly. Managed consumers acquire a :class:`LocalUse`;
the retired local handle/provider path no longer exists.
"""
from .files import LocalFileArea
from .process import IDENTITY_PREFIX, LocalProcessHandle, spawn
from .composition import (
    COMPOSITION_CAPABILITIES,
    ISOLATION,
    MANAGED_VALUES,
    PROVIDER_ID,
    LocalCompositionProvider,
    LocalRuntimeHost,
    LocalSandbox,
    LocalUse,
)
from .provider import (
    REFERENCE_KEYS,
    LocalEnvironmentResourceProvider,
    probe_local,
    resolve_reference,
)

__all__ = [
    "COMPOSITION_CAPABILITIES",
    "IDENTITY_PREFIX",
    "ISOLATION",
    "MANAGED_VALUES",
    "PROVIDER_ID",
    "REFERENCE_KEYS",
    "LocalCompositionProvider",
    "LocalEnvironmentResourceProvider",
    "LocalFileArea",
    "LocalProcessHandle",
    "LocalRuntimeHost",
    "LocalSandbox",
    "LocalUse",
    "probe_local",
    "resolve_reference",
    "spawn",
]
