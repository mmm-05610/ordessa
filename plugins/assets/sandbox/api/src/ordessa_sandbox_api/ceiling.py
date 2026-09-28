"""Ceiling checks: what the administrator's maximum permits (FR-06)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .coverage import ToolCategory
from .errors import SandboxApiError, SandboxErrorCode
from .intent import NativeSandboxIntent, NetworkMode, brand_coverable_categories


@dataclass(frozen=True)
class SandboxCeiling:
    """One authoritative maximum. Ordinary Profile/user intent can only move
    inside it; multiple ceilings intersect to the strictest, never last-wins."""

    brand: str
    enforce: bool = True
    minimum_strictness: int = 0
    network_allowed_max: bool = True
    required_coverage: frozenset[ToolCategory] = frozenset()
    source: str = ""


def intersect_ceilings(ceilings: Sequence[SandboxCeiling]) -> SandboxCeiling:
    items = list(ceilings)
    if not items:
        raise SandboxApiError(SandboxErrorCode.SANDBOX_INTENT_INVALID,
                              "no ceilings to intersect")
    brands = {item.brand for item in items}
    if len(brands) > 1:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
            f"ceilings for different brands {sorted(brands)} cannot form one "
            "maximum; the weaker one must not win by ordering",
            suggestion="keep one ceiling per brand/harness target")
    return SandboxCeiling(
        brand=items[0].brand,
        enforce=any(item.enforce for item in items),
        minimum_strictness=max(item.minimum_strictness for item in items),
        network_allowed_max=all(item.network_allowed_max for item in items),
        required_coverage=frozenset().union(*(item.required_coverage for item in items)),
        source=";".join(item.source for item in items if item.source),
    )


def check_within_ceiling(requested: NativeSandboxIntent,
                         admin_maximum: Sequence[SandboxCeiling]) -> SandboxCeiling:
    """Validate one intent against the administrator maxima.

    Returns the effective (intersected) ceiling on success. An enforced
    sandbox can never be switched off or loosened from here; a request the
    native schema cannot express refuses outright instead of approximating.
    """
    ceiling = intersect_ceilings(admin_maximum)
    if ceiling.brand != requested.brand:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
            f"ceiling targets {ceiling.brand!r} but the intent is for "
            f"{requested.brand!r}",
            suggestion="reference the ceiling through the same harness brand")
    unexpressible = ceiling.required_coverage - brand_coverable_categories(
        requested.brand)
    if unexpressible:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
            f"{requested.brand}'s native schema cannot express coverage of "
            f"{sorted(str(c) for c in unexpressible)}; refusing to approximate "
            "by ignoring the requirement",
            suggestion="keep such requirements in the Permissions domain")
    if ceiling.enforce and requested.config.sandbox_disabled:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
            "the administrator enforces the native sandbox; a profile/user "
            "intent cannot disable it",
            suggestion="remove the disable attempt or lift nothing")
    if requested.config.strictness < ceiling.minimum_strictness:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
            f"intent strictness {requested.config.strictness} is looser than "
            f"the admin minimum {ceiling.minimum_strictness}",
            suggestion="tighten the intent to at least the ceiling")
    if requested.network is NetworkMode.ALLOWED and not ceiling.network_allowed_max:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
            "the administrator maximum forbids network exposure; the intent "
            "requests it",
            suggestion="set network to disabled")
    missing = ceiling.required_coverage - requested.covered_categories
    if missing:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN,
            f"the ceiling requires coverage of "
            f"{sorted(str(c) for c in missing)} but the intent does not claim it",
            suggestion="declare the covered categories or drop the ceiling")
    return ceiling
