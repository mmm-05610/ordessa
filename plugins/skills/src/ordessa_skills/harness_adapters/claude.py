"""Claude Code adapter — pinned at claude-agent-acp 0.81.2 (SDK 0.3.280).

Frozen facts (research/brand-matrix.md:22-24,52): the ADAPTER pin is
machine-proven (`packaging/claude/package.json:13`,
`claude/production.py:66-67`, asserted by
`test_claude_production_template.py:42`); the CLI version 2.1.274 is a
comment-only first-hand observation (`harnesses.toml:111-113`) and §6 does
not list it among the proven pins — so the native-version capability cell
is `unknown`, yet `assess` still fail-closes on any value other than the
only observed one.

The plugin Skill namespace from the vendor docs (harness-adapters.md:12)
is treated as `unknown` per the registry rule and therefore REFUSED by
collision evaluation — a documented-but-unobserved namespacing mechanism
may not justify letting a managed name collide with a native item.
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

HARNESS_ID = "claude-code"

#: Registry slot template `/runtime/home/.claude/skills/{skill_id}`
#: (`harnesses.toml:110`); the guest-side `.claude` home is pinned by the
#: Harness via CLAUDE_CONFIG_DIR (`claude/production.py:74,80-84`). Here
#: only the relative label exists.
TARGET_SLOT = ".claude/skills"

NATIVE_DISCOVERY_RELATIVE = ".claude/skills"
NATIVE_DISCOVERY_CATEGORY = "runtime_home_claude_skills"

#: The published-protocol adapter instance registered through the point.
ADAPTER = SkillsConfigurationAdapter(harness_id=HARNESS_ID,
                                     target_slot=TARGET_SLOT)


def assess(target: AdapterTarget) -> Assessment:
    """Refuse unless the target matches the pinned adapter (and the only
    observed CLI version) — the CLI pin being comment-grade is reported,
    not hidden (G10)."""
    from .base import assess as _assess
    return _assess(target, harness_id=HARNESS_ID)


def compile(resolved_set: Sequence[ManagedContentRef], target: AdapterTarget,
            *, bounds: GenerationBounds,
            removals: Sequence[ManagedContentRef] = ()):
    """One-shot full-set mount declaration for Claude Code."""
    return compile_intent_set(resolved_set, target, harness_id=HARNESS_ID,
                              target_slot=TARGET_SLOT, bounds=bounds,
                              removals=removals)


def verify(observation_result: ObservationResult) -> VerificationOutcome:
    """Grade one Claude observation. The live production chain never
    observes a Claude skill load (brand-matrix.md:52) — the ceiling is
    `projected`, and the orphaned `claude/profile.py` manifest writes are
    placement facts, nothing more."""
    from .base import verify as _verify
    return _verify(observation_result, harness_id=HARNESS_ID)


def refuse_native_collisions(refs: Sequence[ManagedContentRef],
                             native_names: Sequence[str]) -> None:
    """The vendor-doc plugin namespace is `unknown`, so collisions with
    native-discovered items REFUSE (G12; harness-adapters.md:12)."""
    statement = statement_for(HARNESS_ID)
    evaluate_against_native_discovery(
        refs, native_names, name_rules_for(HARNESS_ID),
        statement.value("native_namespacing"))
