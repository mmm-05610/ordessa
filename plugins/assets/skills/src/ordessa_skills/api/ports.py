"""Ports the optional adapters consume (docs/design/skills-v2/contracts.md).

The ports are Protocols so the adapters can be type-checked and tested
against fakes without importing the Profile or Harness packages; the real
registration surfaces satisfy them in the integration wave.

STATUS (harness-api checkpoint): the interim `HarnessCapability` /
`HarnessDeliveryPort` Protocols are DELETED — the published
`ordessa_harness_api` vocabulary (`ConfigurationAdapter`,
`ConfigurationCapabilities`, `ConfigurationService`, `ApplicationTarget`)
is the only Harness-facing surface this domain speaks (the bool-shaped
`session_reload`/`skill_mechanism` cell was a second capability vocabulary
next to the evidence table, exactly what the design forbids). `api/` stays
the pure-type area: the published types are consumed in
`harness_adapters/contribution.py`, not re-declared here.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SkillBindingFacet(Protocol):
    """What profile_contribution publishes to the Profile registration port."""

    def bindings_view(self, profile_id: str) -> list[dict[str, Any]]: ...

    def effect_view(self, profile_id: str, session_ref: str) -> list[dict[str, Any]]: ...


class ProfileRegistrationPort(Protocol):
    """Satisfied by the Profile plugin's registration surface (integration wave)."""

    def publish_skill_binding_facet(self, facet: SkillBindingFacet) -> Any: ...
