"""Ordessa native-sandbox per-brand configuration adapters (`ordessa-sandbox-adapters`, task T05/T05b).

The `sandbox.native-configuration@1` brand facet of the Sandbox asset
(contracts.md §C2): `CodexSandboxAdapter`, `ClaudeSandboxAdapter`,
`PiSandboxAdapter`, each a pure `assess / compile / verify` surface keyed by
`(harnessId, nativeVersionRange)`. Since the foundation checkpoint the three
descriptors are contributed through the REAL `harness.configuration-adapters`
point (`points.py`): the platform (`HarnessContributionRegistry` +
`stage_contributions` + the Server plugin host) is the single composition
authority — duplicate ids, version/entry overlaps and cross-facet native-field
claim collisions are refused there with typed platform errors, never by a
private second registry (the former `SandboxAdapterRegistry`/
`stage_field_claims` are demoted away). Stdlib + consumed contracts only; no
host, no storage, no subprocess, no config write, no harness package code.

Honesty of the brand rules, proven from repo evidence:

* codex — only `read-only`/`workspace-write` are writable postures
  (`posture_config.py:77-79`); the accepted `sandbox_mode` vocabulary is the
  committed version-matched App Server schema `SandboxMode` enum, not the docs;
  `danger-full-access` and an admin-enforced disable refuse, never a bypass;
* claude-code — Bash/PowerShell/Monitor scope only; a `requiredCoverage` of
  read/edit/MCP/network returns `SANDBOX_COVERAGE_UNPROVEN` and the compiled
  output asserts NO broader coverage (absence, not a flag); Linux/WSL2 bwrap +
  macOS Seatbelt supported, native Windows `SANDBOX_PLATFORM_UNSUPPORTED`, an
  unmeasured OS is `SANDBOX_EFFECT_UNKNOWN` (a distinct code);
* pi — extension-backed only; with no loaded sandbox extension nothing is
  compiled and bare Pi is never configured as isolated; the published
  descriptor files zero native-field claims.

The C3 apply seam is BOUND, not registered-blocked, since the `harness-api`
checkpoint (`specs/011-plugin-rollout/checkpoints/harness-api.json`,
implementation `61966e3118`, published `d3f026904e`): `to_harness_c3()` returns
the platform's own `SetField`/`ResetField`/`InvokeAction` over the server-issued
`TargetHandle`, and `CompiledIntent.to_harness_c3()` returns a real `IntentSet`
(`seam.py`); `surface.py` re-expresses each brand through the published
`ConfigurationAdapter` contract; `assess`/`verify` answer with the platform's
`Assessment`/`Verification`, and the former local mirrors
(`AssessReport`/`AssessOutcome`/`VerifyResult`/`VerifyOutcome`/
`SandboxNativeConfigurationAdapter`) are deleted — one vocabulary. The
path-shaped and secret-shaped refusals come from the platform DTOs (`FieldPath`,
`SetField`), not from a parallel guard in this package. What the record itself
still leaves absent — instance generation, an operation-bound native receipt,
any Q5 production verifier — stays `Unknown`; the strongest proof this tree can
back is the controlled-fixture L2 write/read-back loop
(`tests/test_controlled_c4_l2.py`), never a production claim.
"""
from __future__ import annotations

from . import (
    base, claude_code, codex, dto, matrix, pi, points, ranges, registry,
    results, seam, surface,
)
from .base import BaseSandboxAdapter
from .claude_code import ClaudeSandboxAdapter
from .codex import CodexSandboxAdapter
from .dto import AdapterPin, AuthorizedFacts, PiSandboxExtensionEvidence
from .matrix import (
    ADAPTER_CAPABILITY_CELLS,
    MATRIX_FIELDS,
    UNKNOWN_FIELD,
    AdapterCapabilityCell,
)
from .pi import PiSandboxAdapter
from .points import (
    HarnessSandboxConfigurationAdapter,
    HarnessRegistryUnavailable,
    SANDBOX_CONFIGURATION_POINT_ID,
    SANDBOX_FACET_ID,
    SANDBOX_FACET_SCHEMA_VERSION,
    SANDBOX_POINT_API_VERSION,
    build_configuration_batch,
    build_configuration_descriptor,
    pinned_harness_versions,
)
from .ranges import NativeVersionRange, VersionRangeError, parse_version
from .registry import (
    ADAPTER_PLUGIN_ID,
    SANDBOX_NATIVE_CONFIGURATION_CONTRACT_ID,
    SandboxAdaptersServerPlugin,
    default_sandbox_adapters,
)
from .results import (
    ADAPTER_REMEDIES,
    CompiledIntent,
    CompileRefusal,
    CompileResult,
    assessment_supported,
    assessment_unknown,
    assessment_unsupported,
    sandbox_code_of,
    sandbox_reason,
    unknown_verification,
    unsupported_verification,
    verification_match,
    verification_mismatch,
)
from .seam import (
    HARNESS_C3_INTENT_KINDS,
    KIND_INVOKE_ACTION,
    KIND_RESET_FIELD,
    KIND_SET_FIELD,
    CompiledFieldIntent,
    sandbox_contribution_version,
    sandbox_item_id,
)
from .surface import PLATFORM_REFUSAL_CODE, SandboxConfigurationSurface

__version__ = "0.1.0"

_MODULES = (ranges, seam, results, dto, base, codex, claude_code, pi, matrix,
            points, registry, surface)
__all__ = tuple(sorted({name for module in _MODULES for name in module.__all__}))
