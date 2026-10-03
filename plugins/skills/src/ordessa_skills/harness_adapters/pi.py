"""Pi adapter — pinned at Pi 0.84.2 / @automatalabs/pi-acp 0.5.0.

Frozen facts (research/brand-matrix.md:16-17,40): the native version is
evidenced inside the packaged closure (`plugins/harness/packaging/pi/
package-lock.json:45-46`) while the run chain resolves Pi via PATH with no
native version pin (`harnesses.toml:396`); skill discovery, `/reload`,
`/skill:name` and any load evidence are vendor-doc or absent in-repo —
therefore `unknown` and never offered. Everything this module can honestly
declare is a placement intent whose evidence ceiling is `projected`.

No process is spawned, no path is written, no harness symbol is imported —
the module is pure domain data over the published `ordessa_harness_api`
vocabulary; registration rides the published
`harness.configuration-adapters` contribution point (see
`contribution.py` and `plugin.py`).
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

HARNESS_ID = "pi"

#: Logical slot the Harness resolves in its private generation; evidenced
#: as the registry target template `/runtime/home/skills/{skill_id}`
#: (`harnesses.toml:405-406`, `pi/projection.py:27,35`) — recorded here as
#: the relative label only; the absolute half belongs to the Harness.
TARGET_SLOT = "skills"

#: Where a Pi-flavoured guest root is expected to hold natively discovered
#: skills (same evidence). Relative to the observed guest root only.
NATIVE_DISCOVERY_RELATIVE = "skills"
NATIVE_DISCOVERY_CATEGORY = "runtime_home_skills"

#: The published-protocol adapter instance registered through the point.
ADAPTER = SkillsConfigurationAdapter(harness_id=HARNESS_ID,
                                     target_slot=TARGET_SLOT)


def assess(target: AdapterTarget) -> Assessment:
    """Refuse unless the target is the pinned Pi/pi-acp pair (G10)."""
    from .base import assess as _assess
    return _assess(target, harness_id=HARNESS_ID)


def compile(resolved_set: Sequence[ManagedContentRef], target: AdapterTarget,
            *, bounds: GenerationBounds,
            removals: Sequence[ManagedContentRef] = ()):  # noqa: A001 - design vocabulary
    """One-shot full-set mount declaration for Pi (harness-adapters.md 步骤 2).

    `bounds` is the frozen {runtimeGeneration, projectId, profileRevision,
    assignmentRevision} face the set is pinned to; the return is a
    `SkillProjection` carrying the published `IntentSet`.
    """
    return compile_intent_set(resolved_set, target, harness_id=HARNESS_ID,
                              target_slot=TARGET_SLOT, bounds=bounds,
                              removals=removals)


def verify(observation_result: ObservationResult) -> VerificationOutcome:
    """Grade one Pi observation; Pi's `loaded_evidence` is `unknown`
    (brand-matrix.md:40), so no Pi observation can ever reach loaded/used."""
    from .base import verify as _verify
    return _verify(observation_result, harness_id=HARNESS_ID)


def refuse_native_collisions(refs: Sequence[ManagedContentRef],
                             native_names: Sequence[str]) -> None:
    """Pi has no evidenced native namespacing — collisions refuse (G12)."""
    statement = statement_for(HARNESS_ID)
    evaluate_against_native_discovery(
        refs, native_names, name_rules_for(HARNESS_ID),
        statement.value("native_namespacing"))
