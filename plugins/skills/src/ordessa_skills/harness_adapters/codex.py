"""Codex adapter — pinned at Codex 0.147.0 / @agentclientprotocol/codex-acp 1.1.14.

Frozen facts (research/brand-matrix.md:20-21,46): both pins are machine
constants (`codex/production.py:88`, `packaging/codex/package.json:13`).
The skills protocol surface (`skills/list` with `cwds[]`,
`perCwdExtraUserRoots`, `forceReload`) is proven **as vendored schema
only** — zero Go/JS code in the repo calls any `skills/*` method
(brand-matrix.md:101-115), so discovery, reload and explicit invocation are
`unknown` and never offered. `CODEX_HOME` isolation is the Harness's own
private-generation concern (`codex/production.py:92,102-105`), not a path
this adapter may name in an intent.
"""
from __future__ import annotations

from typing import Sequence

from .base import (
    AdapterTarget, Assessment, ObservationResult, SkillProjection,
    VerificationOutcome, compile_intent_set,
)
from .capabilities import statement_for
from .conflict import evaluate_against_native_discovery, name_rules_for
from .contribution import SkillsConfigurationAdapter
from .intent import GenerationBounds, ManagedContentRef

HARNESS_ID = "codex"

#: Registry slot template `/runtime/home/skills/{skill_id}`
#: (`harnesses.toml:31-33`, `adapters/generic_cli.py:35-38`); relative
#: label only — the Harness owns the absolute half.
TARGET_SLOT = "skills"

NATIVE_DISCOVERY_RELATIVE = "skills"
NATIVE_DISCOVERY_CATEGORY = "runtime_home_skills"

#: The published-protocol adapter instance registered through the point.
ADAPTER = SkillsConfigurationAdapter(harness_id=HARNESS_ID,
                                     target_slot=TARGET_SLOT)


def assess(target: AdapterTarget) -> Assessment:
    """Refuse unless the target is the pinned Codex/codex-acp pair (G10)."""
    from .base import assess as _assess
    return _assess(target, harness_id=HARNESS_ID)


def compile(resolved_set: Sequence[ManagedContentRef], target: AdapterTarget,
            *, bounds: GenerationBounds,
            removals: Sequence[ManagedContentRef] = ()):
    """One-shot full-set mount declaration for Codex."""
    return compile_intent_set(resolved_set, target, harness_id=HARNESS_ID,
                              target_slot=TARGET_SLOT, bounds=bounds,
                              removals=removals)


def verify(observation_result: ObservationResult) -> VerificationOutcome:
    """Grade one Codex observation. `loaded_evidence` is `unknown`
    (projected-only, brand-matrix.md:46); the approval/list schemas are not
    observations and promote nothing."""
    from .base import verify as _verify
    return _verify(observation_result, harness_id=HARNESS_ID)


def refuse_native_collisions(refs: Sequence[ManagedContentRef],
                             native_names: Sequence[str]) -> None:
    """Codex has no evidenced native namespacing — collisions refuse (G12)."""
    statement = statement_for(HARNESS_ID)
    evaluate_against_native_discovery(
        refs, native_names, name_rules_for(HARNESS_ID),
        statement.value("native_namespacing"))
