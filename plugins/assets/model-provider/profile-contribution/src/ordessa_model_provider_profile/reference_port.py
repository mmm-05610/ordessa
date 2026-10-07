# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/ordessa_model_provider_profile/reference_port.py, verbatim)
"""The archive-time reference check, supplied from the Profile side.

A profile "references" a provider config when any of its stored facet values
carries a ``{providerId, modelId}`` pair naming it - the same deep-walk rule
the legacy service used, so the 409 semantics the wire consumers know survive
the port split unchanged.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from ordessa_model_provider.ports import ReferencePort


class ProfileFacetView:
    """One active profile's identity plus its stored configuration values."""

    def __init__(self, profile_id: str, values: Mapping[str, Any]) -> None:
        self.id = profile_id
        self.values = dict(values)


@runtime_checkable
class ProfilesView(Protocol):
    """The read-only profile listing the core needs; injected, not imported."""

    def list_active(self) -> Iterable[ProfileFacetView]: ...


def _model_references(value: Any):
    if isinstance(value, Mapping):
        if set(value) >= {"providerId", "modelId"}:
            yield str(value["providerId"])
        for nested in value.values():
            yield from _model_references(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _model_references(nested)


class ProfileViewReferencePort:
    """``ReferencePort`` over an injected profiles view."""

    def __init__(self, profiles: "ProfilesView") -> None:
        self._profiles = profiles

    def references_of(self, provider_config_id: str) -> list[str]:
        found: list[str] = []
        for profile in self._profiles.list_active():
            if provider_config_id in _model_references(profile.values):
                found.append(profile.id)
        return found
