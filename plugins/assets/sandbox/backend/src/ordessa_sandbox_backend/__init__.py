"""Ordessa native-sandbox backend (`ordessa-sandbox-backend`, task T04b).

The Sandbox domain's backend service over `ordessa-sandbox-api`: option/version
management (`SandboxOptionCatalogue`), the intent/evidence record store
(`NativeSandboxRepository`), the pre-effect verifier (`SandboxVerifier`,
FR-06), the composition-time field-claim conflict gate and §C4 lifecycle
(`SandboxNativeService`), and Server plugin registration
(`SandboxBackendServerPlugin` / `build_sandbox_plugin`).

This package consumes the sandbox API and the server plugin contract only. It
does **not** import `ordessa_server`, `ordessa_server_compat`, `pacthold`,
`ordessa_harness`, or any `ordessa_permissions_*` — so the Sandbox domain
installs and serves WITHOUT Permissions. Native-effect observation is a
read-only, UNBOUND seam (`probe.py`): the closed Harness C3 intent vocabulary
(`SetField`/`ResetField`/`InvokeAction`/`TargetHandle`/`FieldClaim`) is NOT
copied or re-invented here; it binds to the released `harness-api` only once
the C0 checkpoint publishes (see specs/011-q5-safety/api-requests.md G3 and
the package README). Nothing in this package applies configuration.
"""
from __future__ import annotations

from .catalogue import (
    SANDBOX_BRANDS,
    CatalogueResult,
    CatalogueStatus,
    SandboxOptionCatalogue,
)
from .composition import (
    PERMISSIONS_ADAPTER_ID,
    SANDBOX_ADAPTER_ID,
    CompiledSandboxPlan,
    FacetDescription,
    SandboxNativeService,
    stage_field_claims,
)
from .plugin import (
    PLUGIN_ID,
    SandboxBackendServerPlugin,
    SandboxDescribePort,
    build_sandbox_plugin,
)
from .probe import (
    ConfigurationTarget,
    EffectObservation,
    EffectProbe,
)
from .repository import (
    NativeSandboxRepository,
    SandboxIntentReference,
    TargetFacts,
    VerificationFacts,
)
from .verifier import (
    SandboxVerdict,
    SandboxVerifier,
    VerdictKind,
)

__all__ = [
    "PERMISSIONS_ADAPTER_ID",
    "PLUGIN_ID",
    "SANDBOX_ADAPTER_ID",
    "SANDBOX_BRANDS",
    "CatalogueResult",
    "CatalogueStatus",
    "CompiledSandboxPlan",
    "ConfigurationTarget",
    "EffectObservation",
    "EffectProbe",
    "FacetDescription",
    "NativeSandboxRepository",
    "SandboxBackendServerPlugin",
    "SandboxDescribePort",
    "SandboxIntentReference",
    "SandboxNativeService",
    "SandboxOptionCatalogue",
    "SandboxVerdict",
    "SandboxVerifier",
    "TargetFacts",
    "VerdictKind",
    "VerificationFacts",
    "build_sandbox_plugin",
    "stage_field_claims",
]
