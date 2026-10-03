"""The `assets.skills` Profile facet contributed through the real profile-api.

Since the profile-api checkpoint (specs/011-plugin-rollout/checkpoints/
profile-api.json) the Z1 package publishes the consumption surface this
slice had requested as §G3:

* `ordessa_profile.contracts` — `FacetDescriptor` / `ItemDescriptor`, the
  PF04 four-value states (`UNSET` / explicit / `ValueDisabled` /
  provider-absent), `Applicability`, `Violation` / `CompileResult` /
  `ConfigIntent`, `SessionRef` and the `HarnessConfigPort` consumer
  protocol;
* `ordessa_profile.plugin.ProfilePluginServices` — `register_v2_facet
  (provider, owner_plugin_id)` (owner host-injected, never self-declared),
  `describe_facets`, `resolve_preview`.

This package replaces the "profile layer not wired yet" posture of
`profile_facet.py` for compositions that provide the Profile services:
`SkillsFacetProvider` is a `FacetProviderV2` registered through the
published API only, and `ProfileApiLayerPort` satisfies the domain's
`assignments.ports.ProfileLayerPort` from the real facet reads. The
composition decision stays honest:

* when the host composes Profile, `plugin.SkillsServerPlugin` registers the
  facet and injects `ProfileApiLayerPort` — the resolver's fifth layer then
  reads real Profile facts (tri-state `inherit | enable(revision) |
  disable`, fixed revisions);
* when Profile is absent, `profile_facet.NotConfiguredProfileLayerPort`
  stays the default and keeps refusing with a type (contracts.md §Profile:
  可选注册不能反转依赖 — the public content CRUD never hard-depends on
  Profile being enabled);
* `migration/profile_bindings.py` keeps its semantics untouched: the
  legacy-binding migration engine still writes only the domain's own
  assignment tables; nothing here moves it into the facet.

Imports of `ordessa_profile` are deliberately lazy (inside the functions
that speak to the API): this package must stay importable in compositions
without Profile installed — the same optional-registration rule the facet
itself obeys. What the facet does NOT do: it never writes Profile storage
(no `set_facet_values`, no journal, no overlay is touched by this domain —
writes belong to Profile's own wire surface, composed by C0), it never
fabricates an applied/use evidence rung (compile declares no native config
steps: skill projection runs through the Skills harness adapters and the
§G2 seam, and the `HarnessConfigPort` absence stays Profile's own typed
block — `APPLICATION_PORT_ABSENT` — which this layer consumes, never
reimplements).
"""
from .port import ProfileApiLayerPort
from .provider import (
    DISABLE_VALUE,
    FACET_API_MAJOR,
    FACET_ID,
    FACET_SCHEMA_VERSION,
    SkillsFacetProvider,
    decision_value,
    entry_from_value,
    register_skills_facet,
)

__all__ = [
    "DISABLE_VALUE", "FACET_API_MAJOR", "FACET_ID", "FACET_SCHEMA_VERSION",
    "ProfileApiLayerPort", "SkillsFacetProvider", "decision_value",
    "entry_from_value", "register_skills_facet",
]
