"""Dedicated Agent public face, sharing the caller's sole Environment."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    AGENT_CONTRACT_VERSION, ProfileCatalogEntry, ProfileManifest, ProfileRef,
    ProfileNotFound, ProfileRevisionConflict, ProfileValidationError,
)
from .profiles import ProfileCatalog
from .schema import wire_contract, wire_schema_digest
from .directory import DirectoryBindingRef


@dataclass(frozen=True)
class AgentServices:
    profiles: ProfileCatalog


def agent_services(environment) -> AgentServices:
    """Bootstrap one core-owned catalog on the existing Environment.

    No plugin activation, native process or second Environment is created.
    Optional storage/policy availability is checked at each operation.
    """
    with environment._admission_lock:
        environment._check_open()
        services = getattr(environment, "_agent_services", None)
        if services is None:
            services = AgentServices(ProfileCatalog(environment))
            environment._agent_services = services
        return services


__all__ = ["AGENT_CONTRACT_VERSION", "AgentServices", "agent_services",
           "ProfileCatalog", "ProfileCatalogEntry", "ProfileManifest", "ProfileRef",
           "ProfileNotFound", "ProfileRevisionConflict", "ProfileValidationError"]
__all__ += ["wire_contract", "wire_schema_digest"]
__all__ += ["DirectoryBindingRef"]
