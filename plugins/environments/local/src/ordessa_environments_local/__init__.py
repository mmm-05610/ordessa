"""Local (``isolation=none``) execution environment provider.

The only environment implementation required for v1. It owns real OS processes,
their bidirectional byte streams and a bounded local file area, and it reports
``isolation="none"`` honestly.
"""
from .files import LocalFileArea
from .process import IDENTITY_PREFIX, LocalProcessHandle, spawn
from .provider import (
    ISOLATION,
    PROVIDES,
    REFERENCE_KEYS,
    LocalEnvironmentHandle,
    LocalEnvironmentProvider,
    LocalEnvironmentResourceProvider,
    LocalExecutionSpace,
)

__all__ = [
    "IDENTITY_PREFIX",
    "ISOLATION",
    "PROVIDES",
    "REFERENCE_KEYS",
    "LocalEnvironmentHandle",
    "LocalEnvironmentProvider",
    "LocalEnvironmentResourceProvider",
    "LocalExecutionSpace",
    "LocalFileArea",
    "LocalProcessHandle",
    "spawn",
]
