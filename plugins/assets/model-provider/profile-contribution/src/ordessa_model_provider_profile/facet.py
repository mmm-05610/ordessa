# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/ordessa_model_provider_profile/facet.py, verbatim)
"""US-6 resolution semantics: profile facet value vs session override.

Per control, the effective value is the session's override when one exists,
else the profile's latest revision. Overrides are keyed by the exact session
reference, so A's override never leaks to B; an explicit successful profile
switch on a session clears *all* of that session's overrides (the switch is
the user saying "follow the other profile now").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ordessa_model_provider.next_turn import SESSION_REF_KEYS


def _session_key(session_ref: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(session_ref[key]) for key in SESSION_REF_KEYS)


@dataclass
class SessionOverrides:
    """The temporary values one user session carries on top of its profile."""

    overrides: dict[tuple[str, ...], dict[str, Any]] = field(default_factory=dict)

    def set(self, session_ref: Mapping[str, Any], control_id: str, value: Any) -> None:
        self.overrides.setdefault(_session_key(session_ref), {})[control_id] = value

    def clear(self, session_ref: Mapping[str, Any]) -> bool:
        """Explicit profile switch: the session's temporary values all go."""
        return self.overrides.pop(_session_key(session_ref), None) is not None

    def get(self, session_ref: Mapping[str, Any]) -> dict[str, Any]:
        return dict(self.overrides.get(_session_key(session_ref), {}))


class EffectiveChoiceResolver:
    """Effective per-control values for a session following a profile."""

    def __init__(self, overrides: SessionOverrides | None = None) -> None:
        self.overrides = overrides or SessionOverrides()

    def effective(self, session_ref: Mapping[str, Any],
                  profile_revision: Mapping[str, Any]) -> dict[str, Any]:
        """Merge: profile latest revision, then this session's overrides."""
        effective = dict(profile_revision)
        effective.update(self.overrides.get(session_ref))
        return effective

    def switch_profile(self, session_ref: Mapping[str, Any]) -> bool:
        """An explicit, successful switch: temporary values clear together."""
        return self.overrides.clear(session_ref)
