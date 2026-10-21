"""Immutable brand-owned resource values for explicit host composition."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RegistrationDeclarations:
    """Original declaration fragments, without aggregate selection or framing."""
    registry_toml: bytes
    launch_json: bytes
