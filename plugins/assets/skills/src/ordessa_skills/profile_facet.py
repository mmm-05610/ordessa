"""Profile-facet adapter for the resolver's Profile layer (FR05 seam).

The resolver's fifth layer is the Profile facet `assets.skills` (docs/
design/skills-v2/contracts.md §Profile / Workspace / Settings). The real
provider EXISTS since the `profile-api` checkpoint
(specs/011-plugin-rollout/checkpoints/profile-api.json): compositions that
hand the plugin a `ProfilePluginServices` register the facet and read the
layer through `profile_contribution/` (the §G3 request, answered). This
module keeps the OTHER half:

* :class:`NotConfiguredProfileLayerPort` is the default when Profile is not
  composed at all — contracts.md 可选注册不能反转依赖: the public content
  CRUD must not hard-depend on Profile being enabled. It answers "profile
  layer unavailable" **with a type** when a profile target is actually
  requested — it never pretends that an empty entry list means
  "everything disabled", and it never fakes a revision identity. When no
  profile target is requested the layer is simply not consulted, so those
  resolutions behave as "the profile layer inherits" (data-model 三态:
  inherit is the absence of the row), which is honest, not a filter.
* `profile_contribution.ProfileApiLayerPort` satisfies the same
  `assignments.ports.ProfileLayerPort` (`skill_entries` / `harness_id` /
  `revision_identity`) from the real facet reads with no change anywhere
  else: the resolver and `SkillsService` receive the port by injection
  (assignments/ports.py pins the supplier table).

Session overrides (§G3(b) then) likewise stay a caller-supplied per-commit
input (`wire.py` maps the bounded `sessionOverrides` param to
`SessionOverride` rows); no session-override store is created here
(contracts.md: 会话覆盖按 Profile 已有 item 机制执行，不新建会话覆盖库).

Migration note (AGENTS.md rule 5 — data compatibility): the legacy
`server_profile_assets` binding rows (compat `assets.bind*` family) are
**read-only history** until the migration ledger lands. This module reads
no row of that table and migrates nothing; the switch of those rows into
assignments belongs to C0's retirement plan (docs/migration/), not here.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .api.errors import AssetDomainError
from .assignments.ports import ProfileSkillEntry, SessionOverride

#: The typed refusal a profile target sees while §G3 is open. Chosen to be
#: distinct from `PROFILE_UNKNOWN` (the profile id may be perfectly real —
#: what is missing is the platform read seam, and saying otherwise would
#: misattribute the outage).
PROFILE_LAYER_UNAVAILABLE = "PROFILE_LAYER_UNAVAILABLE"

_G3 = "specs/011-q1-skills/api-requests.md §G3"


def profile_layer_unavailable(profile_id: str) -> AssetDomainError:
    """The single refusal shape for every unconfigured profile read."""
    return AssetDomainError(
        PROFILE_LAYER_UNAVAILABLE,
        "the Profile facet assets.skills is not wired: the profile-api "
        f"supply is open as {_G3}; the profile layer refuses with a type "
        "instead of pretending empty content means disabled",
        detail=profile_id)


class NotConfiguredProfileLayerPort:
    """The shipped default for `ProfileLayerPort` while §G3 is unlanded.

    * ``skill_entries`` — returned only when a caller has already been
      told the layer is unavailable (``harness_id`` is consulted first by
      the resolver); kept as an empty sequence so a hypothetical caller
      reading entries alone sees "inherit", never a fake disable.
    * ``harness_id`` / ``revision_identity`` — refuse with
      ``PROFILE_LAYER_UNAVAILABLE`` (never None, never a synthesized
      digest): G16/G05 discipline says an unknown capability must be
      visible, not filtered.
    """

    def skill_entries(self, profile_id: str) -> Sequence[ProfileSkillEntry]:
        raise profile_layer_unavailable(profile_id)

    def harness_id(self, profile_id: str) -> str | None:
        raise profile_layer_unavailable(profile_id)

    def revision_identity(self, profile_id: str) -> Mapping[str, Any]:
        raise profile_layer_unavailable(profile_id)


def session_overrides_from(items: Sequence[Mapping[str, Any]]) -> tuple[
        SessionOverride, ...]:
    """Map the bounded wire param (`sessionOverrides`) onto layer-6 rows.

    Values arrive from the session owner (Z1 mechanism, §G3(b)); this
    adapter validates shape only — it never persists anything.
    """
    overrides: list[SessionOverride] = []
    for item in items:
        decision = item.get("decision")
        if decision not in ("inherit", "enable", "disable"):
            raise AssetDomainError(
                "SESSION_OVERRIDE_INVALID", "unknown session override decision",
                detail=str(decision))
        overrides.append(SessionOverride(
            str(item["assetId"]), decision,
            None if item.get("revision") is None else int(item["revision"])))
    return tuple(overrides)


__all__ = [
    "PROFILE_LAYER_UNAVAILABLE", "NotConfiguredProfileLayerPort",
    "profile_layer_unavailable", "session_overrides_from",
]
