"""`ProfileApiLayerPort` — the resolver's Profile layer over the real facet.

Satisfies `assignments.ports.ProfileLayerPort` (the port table in that
module always named Z1 as the supplier; the profile-api checkpoint is Z1's
answer to §G3) by reading `ProfilePluginServices` — the published facade —
and nothing else:

* `skill_entries(profile_id)` → `services.resolve_preview(profile_id)`,
  filtered to the `assets.skills` facet's items with `source == "profile"`:
  `enable(revision)` / `disable` rows decode through
  :func:`.provider.entry_from_value`; inherit stays the absence of an item
  (the data model's own encoding). Session-overlay-sourced rows are
  deliberately NOT folded in — session overrides arrive per commit through
  the resolver's layer 6 (`wire.py` `sessionOverrides`), which is exactly
  how contracts.md freezes them (会话临时选择下一次提交生效，不能永久回写
  Profile).
* `harness_id(profile_id)` → `services.core.profiles.get(...)` — the
  Profile-owned fact the resolver checks against the target harness
  (`PROFILE_HARNESS_MISMATCH`), read through Profile's own service object;
  this domain never opens the Profile database.
* `revision_identity(profile_id)` → the §G3(c) triple
  (profileId, configRevision, configObjectDigest), taken verbatim from the
  preview envelope's `revision` and `digest` (`Resolution.source_digest()`),
  so the frozen resolution snapshot stamps a REAL Profile revision identity,
  never a synthesized one.

Absence stays typed (G05/G10: 不可用不以静默过滤达成"成功"):

* an unknown profile id refuses with the domain's ``PROFILE_UNKNOWN`` (the
  Profile service said so — distinct from the layer being unwired, which is
  ``PROFILE_LAYER_UNAVAILABLE`` from `NotConfiguredProfileLayerPort`);
* a facet the registry does not know (unregistered provider) simply
  contributes no items — that is Profile's provider-absent semantics
  (`resolution.unavailable`), surfaced here as an honest empty layer,
  because the resolver's own contract already treats a missing row as
  inherit and the describe/registration path is where a real outage is
  visible to the operator; an outage recorded in `unavailable` is raised as
  a typed refusal instead of being filtered.

Read-only by construction: no method of this class reaches a writer of the
Profile API (the tests pin that with a recording spy), which is the "never
write profile storage behind its back" half of §G3.
"""
from __future__ import annotations

from typing import Any, Sequence

from ..api.errors import AssetDomainError
from ..assignments.ports import ProfileSkillEntry
from .provider import FACET_ID, entry_from_value

#: The refusal code for a profile id the Profile service itself does not
#: know. `PROFILE_UNKNOWN` is the resolver-vocabulary code already named in
# `profile_facet.py`'s note (it was reserved for exactly this supplier).
PROFILE_UNKNOWN = "PROFILE_UNKNOWN"
_PROFILE_LAYER_OUTAGE = "PROFILE_LAYER_OUTAGE"


class ProfileApiLayerPort:
    """`ProfileLayerPort` backed by a live `ProfilePluginServices`."""

    def __init__(self, services: Any) -> None:
        self._services = services

    # -- ProfileLayerPort -------------------------------------------------------

    def skill_entries(self, profile_id: str) -> Sequence[ProfileSkillEntry]:
        preview = self._preview(profile_id)
        entries: list[ProfileSkillEntry] = []
        for item in preview.get("items") or ():
            if item.get("facet_id") != FACET_ID:
                continue
            if item.get("source") != "profile":
                continue  # overlay rows belong to layer 6, see module docstring
            decoded = entry_from_value(item.get("value"))
            if decoded is None:
                # An unrecognised stored value is refused visibly, never
                # skipped: a silent filter is the fake success contracts.md
                # names. `entry_from_value` already validated the shape at
                # write time, so this only fires on foreign corruption.
                raise AssetDomainError(
                    _PROFILE_LAYER_OUTAGE,
                    "the assets.skills item carries a value this facet does "
                    "not spell; refusing to resolve instead of filtering it",
                    detail=f"{profile_id}/{item.get('item_id')}")
            decision, revision = decoded
            entries.append(ProfileSkillEntry(
                str(item["item_id"]), decision, revision))
        # Profile's own provider-absent facts must not become an implicit
        # "inherit": if any assets.skills row resolved unavailable, the
        # layer answers with a type (quarantine/provider-absent reasons).
        for row in preview.get("unavailable") or ():
            if row.get("facet_id") == FACET_ID:
                raise AssetDomainError(
                    _PROFILE_LAYER_OUTAGE,
                    "the assets.skills layer is unavailable for this profile "
                    f"({row.get('reason')}); the resolver refuses instead of "
                    "treating an outage as inherit",
                    detail=f"{profile_id}/{row.get('item_id')}")
        return tuple(entries)

    def harness_id(self, profile_id: str) -> str | None:
        profile = self._profile_row(profile_id)
        harness = profile.get("harness_id")
        return None if harness is None else str(harness)

    def revision_identity(self, profile_id: str) -> dict[str, Any]:
        preview = self._preview(profile_id)
        return {
            "profileId": str(preview["profile_id"]),
            "configRevision": int(preview["revision"]),
            "configObjectDigest": str(preview["digest"]),
        }

    # -- Profile reads (the only two API touch points) --------------------------

    def _preview(self, profile_id: str) -> dict[str, Any]:
        try:
            return dict(self._services.resolve_preview(profile_id))
        except Exception as exc:  # noqa: BLE001 - classify by Profile's code
            raise self._classify(exc, profile_id) from exc

    def _profile_row(self, profile_id: str) -> dict[str, Any]:
        try:
            row = self._services.core.profiles.get(profile_id)
        except Exception as exc:  # noqa: BLE001 - classify by Profile's code
            raise self._classify(exc, profile_id) from exc
        if row is None:
            raise AssetDomainError(PROFILE_UNKNOWN,
                                   "the Profile service has no such profile",
                                   detail=profile_id)
        return dict(row)

    @staticmethod
    def _classify(exc: Exception, profile_id: str) -> AssetDomainError:
        """Map the Profile service's own refusal onto the domain's typed code.

        Duck-typed on `.code` (ProfileError's frozen spelling) rather than
        importing `ordessa_profile.errors`: the profile package is a sibling
        plugin and this domain's import surface stays pinned by
        tests/test_dependency_direction.py to the published contract modules
        only.
        """
        code = getattr(exc, "code", None)
        if code in ("PROFILE_NOT_FOUND", "PROFILE_UNKNOWN"):
            return AssetDomainError(
                PROFILE_UNKNOWN,
                "the Profile service has no such profile", detail=profile_id)
        if isinstance(exc, LookupError):
            return AssetDomainError(
                PROFILE_UNKNOWN,
                "the Profile service has no such profile", detail=profile_id)
        return AssetDomainError(
            _PROFILE_LAYER_OUTAGE,
            "the Profile layer could not be read", detail=f"{profile_id}: {exc}")


__all__ = ["PROFILE_UNKNOWN", "ProfileApiLayerPort"]
