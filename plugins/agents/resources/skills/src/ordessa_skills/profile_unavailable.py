"""Typed refusal for unsupported Profile-driven Skills projections.

The former Profile facet supplier and session-overlay input are retired.
Assets resource CRUD and its own assignment store remain independent. A
profile-targeted resolution must fail explicitly until a current public input
owner is composed; it must never look like an empty set of disables.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .api.errors import AssetDomainError
from .assignments.ports import ProfileSkillEntry

PROFILE_LAYER_UNAVAILABLE = "PROFILE_LAYER_UNAVAILABLE"


def profile_layer_unavailable(profile_id: str) -> AssetDomainError:
    """The single refusal shape for every unconfigured profile read."""
    return AssetDomainError(
        PROFILE_LAYER_UNAVAILABLE,
        "Profile-driven Skills resolution is unavailable: the former "
        "Profile facet consumer is retired and no current input owner is wired",
        detail=profile_id)


class NotConfiguredProfileLayerPort:
    """Always refuse Profile-based reads with the explicit unavailable type."""

    def skill_entries(self, profile_id: str) -> Sequence[ProfileSkillEntry]:
        raise profile_layer_unavailable(profile_id)

    def harness_id(self, profile_id: str) -> str | None:
        raise profile_layer_unavailable(profile_id)

    def revision_identity(self, profile_id: str) -> Mapping[str, Any]:
        raise profile_layer_unavailable(profile_id)

__all__ = [
    "PROFILE_LAYER_UNAVAILABLE", "NotConfiguredProfileLayerPort",
    "profile_layer_unavailable",
]
