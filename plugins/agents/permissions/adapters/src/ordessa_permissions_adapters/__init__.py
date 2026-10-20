"""Ordessa Permissions Adapters - per-brand policy adapters (T03/T03b).

The `permissions.policy-adapters@1` compile-time surface of the Permissions
domain: `PiAdapter`, `CodexAdapter`, `ClaudeAdapter`, each implementing the
§C1 shape `supports / compilePolicy / verifyPolicy` keyed by
`(harnessId, nativeVersionRange)`.

Composition authority is the PLATFORM's: callable brand adapter payloads with
`ConfigurationAdapterDescriptor` declarations are contributed on the real Harness public
point `harness.configuration-adapters` (api_version `v1`, facet
`permissions.policy-adapters`) via `PolicyAdaptersPlugin` ->
`ServerPluginRegistration.contributions`. Duplicate/overlap refusal,
field-claim conflicts, owner injection and publish-on-commit are performed
by the point's conflict registry driven through `server_plugin_api`; this
package admits nothing (the former private `PolicyAdapterRegistry` was
removed as a second authority).

Compile is pure - no network, no spawn, no user-config or key access (an AST
gate in tests/ enforces this). Each brand's honesty follows measured repo
evidence (`cells.py`, `matrix.py`), never brand folklore:

* claude-code: only `permissions.ask` / `permissions.deny` are writable;
  loosening knobs (`permissions.allow`, `defaultMode`, `bypassPermissions`)
  refuse typed (`PERMISSION_POSTURE_UNEXPRESSIBLE`);
* codex: `sandbox_mode` / `approval_policy` within the measured strictness
  tables; `danger-full-access` / `never` / `on-failure` are not writable and
  a ceiling-blocked posture refuses - never a bypass; the field claim covers
  `approval_policy` only (`sandbox_mode` is §C2 pre-allocated to the Sandbox
  facet);
* pi: extension-backed only; without a loaded `tool_call` gate observation
  every compile refuses (`POLICY_ADAPTER_MISSING`) - bare Pi is never fine,
  and its contribution claims no native field.

Blocked seams stay registered, not faked: the pre-effect authorization gate
(G1) and the native-receipt plumbing (G2) do not exist in this tree; nothing
here claims them.
"""
from __future__ import annotations

from . import (
    base, cells, claude_code, codex, codes, contribution, dto, matrix, pi,
    ranges, registry, results,
)
from .base import BaseBrandAdapter, PermissionPolicyAdapter
from .cells import CAPABILITY_CELLS, CapabilityCell
from .claude_code import CLAUDE_SETTINGS_TOOLS, ClaudeAdapter
from .codex import CodexAdapter
from .codes import ADAPTER_REMEDIES, AdapterCode
from .contribution import (
    CONFIGURATION_POINT,
    FACET_ID,
    FACET_SCHEMA_VERSION,
    PINNED_NATIVE_VERSIONS,
    POINT_API_VERSION,
    PolicyConfigurationAdapter,
    configuration_descriptor,
    default_adapters,
    default_configuration_descriptors,
    policy_adapter_contributions,
    select_adapter,
)
from .dto import (
    PiToolCallGateEvidence,
    PolicyBinding,
    PolicyCompileSnapshot,
    PolicyObservation,
    SupportEvidence,
)
from .matrix import BRAND_MATRIX, MATRIX_FIELDS, UNKNOWN, MatrixCell
from .pi import PiAdapter
from .ranges import NativeVersionRange, VersionRangeError, parse_version
from .registry import (
    ADAPTER_PLUGIN_ID,
    CONTRACT_ID,
    PolicyAdapterDescriptor,
    PolicyAdaptersPlugin,
)
from .results import (
    CompiledIntentSet,
    CompileRefusal,
    CompileResult,
    SupportOutcome,
    SupportReport,
    VerifyOutcome,
    VerifyResult,
)

__version__ = "0.1.0"

_MODULES = (codes, ranges, results, dto, base, claude_code, codex, pi, cells, matrix,
            contribution, registry)
__all__ = tuple(sorted({name for module in _MODULES for name in module.__all__}))
