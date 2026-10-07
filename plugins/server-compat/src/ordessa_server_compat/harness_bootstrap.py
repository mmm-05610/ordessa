"""Product bootstrap: the canonical kernel path with the assembly injected.

specs/010 T009: the Root-owned shared runtime contracts
(RuntimeHostV1/SandboxV1/TerminalSessionV1, ids ``agent-box.runtime-*@1``
kept verbatim), the seed ``CONTRACT_TYPES`` and the business contribution
kinds are injected into the kernel's single canonical loader path — this
module implements no second loading path.
"""
from __future__ import annotations

from pacthold.extensions.bootstrap import (
    ExtensionEnvironment,
    build_extension_environment as _kernel_build,
    build_extension_environment_from_parts as _kernel_build_from_parts,
)
from pacthold.work_core.registry import ExtensionRegistry

from .harness_catalog import ProductExtensionCatalogBuilder
from pacthold_runtime_compat.legacy_migrations import register_legacy_migrations
from ordessa_skills.resource_contracts import AgentSkillV1
from pacthold.harness_contracts.agent_box_profile_v1 import AgentBoxProfileV1
from pacthold.harness_contracts.credential_v1 import CredentialRefV1
from pacthold.harness_contracts.prompt_fragment_v1 import PromptFragmentV1
from pacthold.harness_contracts.workspace_v1 import WorkspaceV1

#: 032: the resource contract types moved to their owning homes; this seed
#: mapping keeps the assembly's registry bootstrapping in one place.
CONTRACT_TYPES = {
    WorkspaceV1.contract_id: WorkspaceV1,
    PromptFragmentV1.contract_id: PromptFragmentV1,
    AgentBoxProfileV1.contract_id: AgentBoxProfileV1,
    CredentialRefV1.contract_id: CredentialRefV1,
    AgentSkillV1.contract_id: AgentSkillV1,
}
from pacthold_runtime_compat.runtime_composition.protocol import (
    RUNTIME_HOST_CONTRACT_ID,
    SANDBOX_CONTRACT_ID,
    TERMINAL_SESSION_CONTRACT_ID,
    RuntimeHostV1,
    SandboxV1,
    TerminalSessionV1,
)

# Root-owned canonical shared runtime contracts.  They describe the execution
# runtime itself, so their Python types and their single registration point
# belong to the compatibility assembly -- never to a concrete provider plugin.
# Provider plugins resolve and provide these contracts but never re-declare
# a different type under the same id.
SHARED_RUNTIME_CONTRACTS: tuple[type, ...] = (
    RuntimeHostV1,
    SandboxV1,
    TerminalSessionV1,
)


def register_shared_runtime_contracts(registry: ExtensionRegistry) -> None:
    """Register the Root-owned shared runtime contracts exactly once."""
    for contract in SHARED_RUNTIME_CONTRACTS:
        registry.register_root_shared_contract(contract)


def build_product_registry() -> ExtensionRegistry:
    """One fresh registry pre-seeded with the product contract set."""
    registry = ExtensionRegistry(seed_contracts=CONTRACT_TYPES.values())
    register_shared_runtime_contracts(registry)
    return registry


def build_product_environment(
    *,
    strict: bool = False,
    entry_points=None,
    register_migrations: bool = True,
) -> ExtensionEnvironment:
    """Canonical product environment on the kernel loader path.

    Seeds the product contracts, injects the business contribution kinds
    and (by default) registers the sealed historical migration chain before
    anything touches the database.
    """
    if register_migrations:
        register_legacy_migrations()
    return _kernel_build(
        strict=strict,
        entry_points=entry_points,
        registry=build_product_registry(),
        catalog_builder=ProductExtensionCatalogBuilder(),
    )


def build_product_environment_from_parts(registry, report) -> ExtensionEnvironment:
    """Product counterpart of the kernel from-parts environment builder."""
    return _kernel_build_from_parts(registry, report, catalog_builder=ProductExtensionCatalogBuilder())


__all__ = [
    "RUNTIME_HOST_CONTRACT_ID",
    "SANDBOX_CONTRACT_ID",
    "SHARED_RUNTIME_CONTRACTS",
    "TERMINAL_SESSION_CONTRACT_ID",
    "build_product_environment",
    "build_product_environment_from_parts",
    "build_product_registry",
    "register_shared_runtime_contracts",
]
