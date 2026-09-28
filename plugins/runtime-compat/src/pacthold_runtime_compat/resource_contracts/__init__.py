"""Provider-neutral, versioned values exchanged during Execution dispatch.

This package deliberately contains no persistence, lifecycle, Ref, provider,
or Work Core imports.  A ``contract_id`` is an incompatible-version boundary.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from . import harness_capabilities
from .agent_box_profile_v1 import AgentBoxProfileV1
from .agent_skill_v1 import AgentSkillV1
from .credential_v1 import CredentialRefV1
from .harness_capabilities import (
    CANONICAL_CAPABILITY_IDS,
    CAPABILITY_CLAIMS_INVALID,
    CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION,
    CAPABILITY_NOT_DECLARED,
    CAPABILITY_NOT_OBSERVED,
    CAPABILITY_OBSERVED_UNSUPPORTED,
    CAPABILITY_SCHEMA_VERSION,
    CAPABILITY_SCOPES,
    CAPABILITY_UNKNOWN_ID,
    CAPABILITY_VALUE_NOT_BOOLEAN,
    CapabilityClaimsInvalid,
    CapabilityDeclaration,
    CapabilityDeclarationError,
    CapabilityUnknownId,
    CapabilityValueNotBoolean,
    canonical_capabilities,
    capability_view,
    merge_capabilities,
    validate_claims,
)
from .prompt_fragment_v1 import PromptFragmentV1
from .workspace_v1 import WorkspaceV1


CONTRACT_TYPES: Mapping[str, type] = MappingProxyType(
    {
        WorkspaceV1.contract_id: WorkspaceV1,
        PromptFragmentV1.contract_id: PromptFragmentV1,
        AgentBoxProfileV1.contract_id: AgentBoxProfileV1,
        CredentialRefV1.contract_id: CredentialRefV1,
        AgentSkillV1.contract_id: AgentSkillV1,
    }
)


def contract_type(contract_id: str) -> type:
    """Return the Python type registered for ``contract_id``."""
    try:
        return CONTRACT_TYPES[contract_id]
    except KeyError as exc:
        raise ValueError(f"unknown resource contract: {contract_id}") from exc


__all__ = [
    "AgentBoxProfileV1",
    "AgentSkillV1",
    "CANONICAL_CAPABILITY_IDS",
    "CAPABILITY_CLAIMS_INVALID",
    "CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION",
    "CAPABILITY_NOT_DECLARED",
    "CAPABILITY_NOT_OBSERVED",
    "CAPABILITY_OBSERVED_UNSUPPORTED",
    "CAPABILITY_SCHEMA_VERSION",
    "CAPABILITY_SCOPES",
    "CAPABILITY_UNKNOWN_ID",
    "CAPABILITY_VALUE_NOT_BOOLEAN",
    "CONTRACT_TYPES",
    "CapabilityClaimsInvalid",
    "CapabilityDeclaration",
    "CapabilityDeclarationError",
    "CapabilityUnknownId",
    "CapabilityValueNotBoolean",
    "CredentialRefV1",
    "PromptFragmentV1",
    "WorkspaceV1",
    "canonical_capabilities",
    "capability_view",
    "contract_type",
    "harness_capabilities",
    "merge_capabilities",
    "validate_claims",
]
