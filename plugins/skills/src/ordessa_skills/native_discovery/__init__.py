"""Read-only native-discovery observation (FR10; G11 split of managed vs
native-discovered). Bodies are never imported; nothing is ever written."""
from __future__ import annotations

from .observation import (
    CANNOT_DISABLE, ORDISSA_DISABLE_SCOPE, DiscoveryReport, DiscoverySlot,
    NativeDiscovery, NativeDiscoveryError, disable_outcome_for,
    observe_native_skills,
)

__all__ = [
    "CANNOT_DISABLE", "ORDISSA_DISABLE_SCOPE", "DiscoveryReport",
    "DiscoverySlot", "NativeDiscovery", "NativeDiscoveryError",
    "disable_outcome_for", "observe_native_skills",
]
