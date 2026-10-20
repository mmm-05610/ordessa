"""Namespace and participant identities used by Unit admission and records.

The environment namespace here is an admission/persistence partition. It is
not an execution-environment resource identity or authorization grant.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_LOCAL_ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


def _check_local_id(value: str, what: str) -> str:
    if not isinstance(value, str) or not _LOCAL_ID.match(value):
        raise ValueError(f"{what} must match { _LOCAL_ID.pattern!r}: {value!r}")
    return value


@dataclass(frozen=True)
class AdmissionNamespace:
    """A stable execution admission namespace."""

    value: str

    def __post_init__(self) -> None:
        _check_local_id(self.value, "AdmissionNamespace.value")


@dataclass(frozen=True)
class AgentNodeRef:
    """A participant instance identified within an admission namespace."""

    environment: str
    instance_id: str
    generation: int

    def __post_init__(self) -> None:
        _check_local_id(self.environment, "AgentNodeRef.environment")
        _check_local_id(self.instance_id, "AgentNodeRef.instance_id")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("AgentNodeRef.generation must be a non-negative int")


@dataclass(frozen=True)
class MaterialProviderActivationRef:
    """Provider activation owning a Unit material capability."""

    environment: str
    plugin_id: str
    generation: int

    def __post_init__(self) -> None:
        _check_local_id(self.environment, "MaterialProviderActivationRef.environment")
        _check_local_id(self.plugin_id, "MaterialProviderActivationRef.plugin_id")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("MaterialProviderActivationRef.generation must be a non-negative int")


__all__ = ["AdmissionNamespace", "AgentNodeRef", "MaterialProviderActivationRef"]
