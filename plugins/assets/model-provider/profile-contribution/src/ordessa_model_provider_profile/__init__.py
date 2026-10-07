# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/ordessa_model_provider_profile/__init__.py, verbatim)
"""Optional Profile contribution for the Model Provider family.

Direction of dependence is one-way: this package depends on the
``ordessa_model_provider`` core's port protocols and on nothing else of it -
never the reverse (spec FR-ARCH-3). It supplies:

* ``ProfileViewReferencePort`` - the ``ReferencePort`` the core's archive
  protection consumes (G4): a Profile that still references a config keeps it
  un-archivable;
* ``EffectiveChoiceResolver`` - the facet value / session-override resolution
  semantics of US-6: overrides are per control and per session; the profile's
  latest revision flows everywhere an override does not exist; an explicit
  profile switch clears that session's overrides.
"""
from ordessa_model_provider_profile.facet import (
    EffectiveChoiceResolver, SessionOverrides,
)
from ordessa_model_provider_profile.reference_port import (
    ProfileFacetView, ProfileViewReferencePort, ProfilesView,
)

__all__ = [
    "EffectiveChoiceResolver", "SessionOverrides",
    "ProfileFacetView", "ProfileViewReferencePort", "ProfilesView",
]
