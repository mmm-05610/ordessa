"""Codex native-lane adapter (Q4 T04, L1 pure surface).

Facts pinned from the fixed host registry and the T04/T05 research
(``harnesses.toml`` codex entry: ``mcp_target = /runtime/home/.codex/config.toml``,
``mcp_key = mcp_servers``, TOML; R-Q4-3):

* the instance-config (file projection) route is **structurally dead** — the
  declared target is a read-only projection file and collides (registered as
  ``ASSET_SLOT_CONFLICT`` by ``test_subagent_harness_round_086.py``); the Q4
  Codex target is the **session-override intent** (codex-acp 1.1.14 merges
  ``session/new.mcpServers`` into the app-server session config overlay);
* neither route has controlled runtime load/permission evidence yet, so
  ``proven_routes`` is empty and assess never answers ``supported`` here
  (session-override -> ``unknown``; instance-config -> typed ``unsupported``).
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
    REASON_INSTANCE_CONFIG_SLOT_CONFLICT,
    BrandAdapter,
    RevisionProvider,
    assess_native,
    compile_native,
    verify_native,
)

CODEX = BrandAdapter(
    harness_type="codex",
    config_key="mcp_servers",
    config_format="toml",
    destination_kinds=(DESTINATION_INSTANCE_CONFIG, DESTINATION_SESSION_OVERRIDE),
    blocked_destinations={DESTINATION_INSTANCE_CONFIG: REASON_INSTANCE_CONFIG_SLOT_CONFLICT},
    # the read-only projection file the registry pins as mcp_target
    projection_conflict_targets=frozenset({"/runtime/home/.codex/config.toml"}),
    supported_transports=frozenset({"stdio"}),
    default_destination_kind=DESTINATION_SESSION_OVERRIDE,
    proven_routes=frozenset(),  # L1: no runtime evidence for either route
    unknown_reason="codex-session-override-runtime-unproven",
)


def assess(decl, snapshot=None, *, destination_kind=None, revision_provider=None) -> AssessResult:
    return assess_native(CODEX, decl, snapshot,
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
    return compile_native(CODEX, snapshot, destination, provenance,
                          revision_provider=revision_provider,
                          expected_catalog_digests=expected_catalog_digests,
                          strict=strict)


def verify(intent_set: NativeIntentSet, observation: NativeObservation) -> VerifyResult:
    return verify_native(intent_set, observation)


# -- the real C2 surface (T013 harness-api wiring) --------------------------------
#
# The conversion itself lives in ``backend/native_binding.py`` — the single
# Q4-domain <-> harness-api boundary; this module only pins the brand facts
# into it. The returned object implements the published
# ``ordessa_harness_api.ConfigurationAdapter`` Protocol (descriptor +
# assess/compile/verify over the real DTOs). Registration is the product
# assembly's move: ``Contribution("harness.configuration-adapters", "v1",
# configuration_adapter())`` under the declared point (the point's payload
# is the adapter; ``plugins/harness/contributions.py`` validates the
# descriptor). Honesty is unchanged at this surface: ``proven_routes`` is
# empty, so ``assess`` answers ``unsupported`` (the instance-config route
# is structurally blocked for Codex, R-Q4-3) and ``unknown`` (the session-
# override route has no runtime load evidence) — never ``supported``.


def configuration_adapter(**overrides):
    from backend.native_binding import McpNativeConfigurationAdapter

    return McpNativeConfigurationAdapter(CODEX, verify_fn=verify_native, **overrides)
