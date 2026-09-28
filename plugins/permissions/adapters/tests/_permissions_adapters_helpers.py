"""T03 adapters test helpers: the ceiling/intent factories and the pin table.

These were previously defined in `conftest.py` and imported from there by
name. Every package in this lane carries its own `conftest.py`, and a
`from conftest import ...` binds whichever one happens to be last in
`sys.modules`, so a cross-package aggregate run resolved them to another
package's conftest. They now live in a uniquely-named module; `conftest.py`
keeps only the pytest fixtures.

Pinned versions are *parsed from the repository* (`harnesses.toml`), never
hardcoded, so a pin change moves the tests with it instead of silently
diverging.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from ordessa_permissions_api import (
    TOOL_KEYS,
    BrandMode,
    EffectiveCeiling,
    PermissionIntent,
    PolicyCeiling,
    intersect_ceilings,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
HARNESSES_TOML = REPO_ROOT / "plugins" / "harness" / "src" / "ordessa_harness" / "harnesses.toml"

#: harness_type used by the adapters for each pinned driver id.
DRIVER_TO_HARNESS_ID = {"codex": "codex", "claude": "claude-code", "pi": "pi"}


def ceiling_entry(key: str, pattern: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"key": key}
    if pattern is not None:
        entry["pattern"] = pattern
    return entry


def make_ceiling(*, deny: Sequence[Any] = (), approval: Sequence[Any] = (),
                 exposure: str = "full", revision: int = 1) -> EffectiveCeiling:
    record = {
        "policyId": f"pol-test-r{revision}",
        "scope": "admin",
        "revision": revision,
        "source": "signed-admin",
        "signed": True,
        "deny": [d if isinstance(d, dict) else ceiling_entry(d) for d in deny],
        "requireApproval": [a if isinstance(a, dict) else ceiling_entry(a)
                            for a in approval],
        "maximumExposure": exposure,
        "effectiveFrom": "2026-01-01T00:00:00+00:00",
    }
    return intersect_ceilings([PolicyCeiling.from_record(record)])


def unverified_ceiling(policy_id: str = "pol-unverified") -> EffectiveCeiling:
    return intersect_ceilings([PolicyCeiling.unverified(policy_id)])


def make_intent(harness_id: str, rules: Sequence[Mapping[str, Any]] = (),
                mode: str | None = None, revision: int = 1) -> PermissionIntent:
    desired = BrandMode.declare(harness_id, mode) if mode is not None else None
    return PermissionIntent.of(
        intent_id=f"intent-{harness_id}-r{revision}", revision=revision,
        harness_id=harness_id, scope="session", rules=list(rules),
        desired_mode=desired)


def full_allow_intent(harness_id: str) -> PermissionIntent:
    """An intent explicitly allowing every declared tool key."""
    return make_intent(harness_id, [{"key": key, "action": "allow"} for key in TOOL_KEYS])
