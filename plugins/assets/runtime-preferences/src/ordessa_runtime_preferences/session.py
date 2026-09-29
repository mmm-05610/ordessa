"""Session semantics for the ``assets.runtime-preferences`` facet: whole-item
overrides on top of a profile, keyed by the exact session reference.

US-6-shaped resolution (profile-v2 contract): the effective value is the
session's override when one exists, else the profile's item value (or the
item default when the profile carries nothing). Overrides are keyed by the
exact session reference, so session A's four-group preferences never leak
into session B (RA-7 isolation counterexamples); an explicit successful
profile switch on a session clears ALL of that session's overrides at once
(the switch is the user saying "follow the other profile now").

Whole-item discipline lives here too: an override replaces the whole item
value — partial patches merge into the draft in the editor, never into a
stored item.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .facet import validate_item_value

SESSION_REF_KEYS = ("serverId", "sessionId")


def _deep_copy(value: Any) -> Any:
    """Item values are validated JSON-safe; a JSON round trip gives callers a
    detached graph (mutations on a returned value can never reach storage)."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def _session_key(session_ref: Mapping[str, Any]) -> tuple[str, ...]:
    missing = [key for key in SESSION_REF_KEYS if key not in session_ref]
    if missing:
        raise ValueError(f"session reference missing {missing}")
    return tuple(str(session_ref[key]) for key in SESSION_REF_KEYS)


@dataclass
class SessionOverrides:
    """The temporary whole-item values one user session carries on top of its
    profile. Items are atomic: setting an item replaces it wholesale."""

    overrides: dict[tuple[str, ...], dict[str, Any]] = field(default_factory=dict)

    def set(self, session_ref: Mapping[str, Any], item_id: str, value: Any) -> None:
        validate_item_value(item_id, value)  # typed refusal on any violation
        self.overrides.setdefault(_session_key(session_ref), {})[item_id] = _deep_copy(value)

    def clear(self, session_ref: Mapping[str, Any]) -> bool:
        """Explicit profile switch: the session's temporary values all go."""
        return self.overrides.pop(_session_key(session_ref), None) is not None

    def get(self, session_ref: Mapping[str, Any]) -> dict[str, Any]:
        return {item: _deep_copy(value)
                for item, value in self.overrides.get(_session_key(session_ref), {}).items()}


class EffectivePreferencesResolver:
    """Effective per-item values for a session following a profile."""

    def __init__(self, overrides: SessionOverrides | None = None) -> None:
        self.overrides = overrides or SessionOverrides()

    def effective(self, session_ref: Mapping[str, Any],
                  profile_items: Mapping[str, Any]) -> dict[str, Any]:
        """Merge: profile item values, then this session's whole-item
        overrides. Absent items stay absent (native defaults follow)."""
        effective = {item: dict(value) if isinstance(value, Mapping) else value
                     for item, value in profile_items.items()}
        effective.update(self.overrides.get(session_ref))
        return effective

    def switch_profile(self, session_ref: Mapping[str, Any]) -> bool:
        """An explicit, successful switch: temporary values clear together."""
        return self.overrides.clear(session_ref)
