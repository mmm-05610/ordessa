"""Claude Code native-lane adapter (Q4 T04, L1 pure surface).

Facts pinned from the fixed host registry and the T04/T05 research
(``harnesses.toml`` claude-code entry:
``mcp_target = /runtime/home/.claude/.claude.json``, ``mcp_key = mcpServers``,
JSON; 086 evidence: the slot sits outside the read-only projection and the
file is a proven read path for the CLI):

* the instance-config route is structurally feasible (no slot conflict), but
  has **no running-load / permission / restart-recovery evidence** in this
  tree, and the session-override consumption by claude-agent-acp 0.81.2 is
  only documented, never probed -> both routes assess ``unknown``;
* ``--strict-mcp-config`` has zero first-hand evidence (research §3.2): it is
  not modelled here as anything;
* the old JSON renderer was stdio-only, so remote definitions stay typed
  ``unsupported`` for rendering at L1.
"""
from __future__ import annotations

from backend.native_intents import (
    DESTINATION_INSTANCE_CONFIG,
    DESTINATION_SESSION_OVERRIDE,
    AssessResult,
    CredentialProvenance,
    Destination,
    NativeIntentSet,
    NativeObservation,
    VerifyResult,
)

from .common import (
    BrandAdapter,
    RevisionProvider,
    assess_native,
    compile_native,
    verify_native,
)

CLAUDE = BrandAdapter(
    harness_type="claude-code",
    config_key="mcpServers",
    config_format="json",
    destination_kinds=(DESTINATION_INSTANCE_CONFIG, DESTINATION_SESSION_OVERRIDE),
    blocked_destinations={},  # instance-config is structurally admissible
    projection_conflict_targets=frozenset(),  # slot moved out of the projection in 086
    supported_transports=frozenset({"stdio"}),
    default_destination_kind=DESTINATION_INSTANCE_CONFIG,
    proven_routes=frozenset(),  # L1: no runtime evidence for either route
    unknown_reason="claude-native-load-and-permission-unproven",
)


def assess(decl, snapshot=None, *, destination_kind=None, revision_provider=None) -> AssessResult:
    return assess_native(CLAUDE, decl, snapshot,
                         destination_kind=destination_kind,
                         revision_provider=revision_provider)


def compile(
    snapshot,
    destination: Destination,
    provenance: CredentialProvenance,
    *,
    revision_provider: RevisionProvider,
    expected_catalog_digests=None,
    strict: bool = False,
) -> NativeIntentSet:
    return compile_native(CLAUDE, snapshot, destination, provenance,
                          revision_provider=revision_provider,
                          expected_catalog_digests=expected_catalog_digests,
                          strict=strict)


def verify(intent_set: NativeIntentSet, observation: NativeObservation) -> VerifyResult:
    return verify_native(intent_set, observation)


# -- the real C2 surface (T013 harness-api wiring) --------------------------------
#
# Brand facts pinned into ``backend/native_binding.py`` (the ONLY Q4-domain
# <-> harness-api conversion point). The returned object implements the
# published ``ConfigurationAdapter`` Protocol with facet ``mcp.servers``;
# the product assembly registers it through the
# ``harness.configuration-adapters@v1`` contribution point. Both routes stay
# ``unknown`` (no runtime load/permission evidence, 086 slot move makes the
# instance-config route structurally admissible but unproven); no cell
# reports ``supported`` without controlled evidence.


def configuration_adapter(**overrides):
    from backend.native_binding import McpNativeConfigurationAdapter

    return McpNativeConfigurationAdapter(CLAUDE, verify_fn=verify_native, **overrides)
