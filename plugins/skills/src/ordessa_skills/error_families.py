"""The Skills domain's published wire-refusal seam (foundation contribution API).

Before the foundation checkpoint this package had no plugin-visible typed
refusal path: `wire.py`'s module docstring recorded the request (api-requests
.md §G1) that `server_plugin_api` either add a refusal type or let the
dispatch map an error protocol carrying `.code`. Foundation published both
halves, and this module consumes them the way the other plugins do
(`plugins/server-compat/error_families.py` is the reference pattern):

* `server_plugin_api.ServerError` — the composition-shared internal error the
  host's dispatch projects onto the wire family set;
* the open `wire.error-families` contribution point — this package's
  `code -> family` rows reach the host as a `Contribution` inside the
  registration's `ContributionBatch`; the host stages them with the injected
  owner (`ordessa.skills`), refuses conflicts with other owners' rows for the
  same code, and freezes them per composition. Nothing here mutates a host
  table or falls back on the generic `except Exception` wall.

Domain code → family adjudication (the closed twelve families of
`server_plugin_api.FAMILIES` only; codes raised outside the wire surface —
the `MIGRATION_*` engine and the adapter-internal `HARNESS_*` rulings — are
deliberately absent, their fall-through stays `UNAVAILABLE`):

* bad input / bad value at the declared-shape-plus level -> `INVALID_REQUEST`;
* unknown id in this data domain -> `NOT_FOUND`;
* CAS / expectedVersion / stale-generation moves -> `CONFLICT_VERSION`;
* state conflicts that are not version CAS (duplicate logical row, an
  in-use disable, an existing revision, a settled-key replay) ->
  `CONFLICT_REQUEST`;
* a referenced-but-foreign target (name collision of another asset's slot,
  a snapshot aimed at another target) -> `CONFLICT_REFERENCE`;
* a seam this composition has not composed (profile layer, native target
  root, domain schema not yet created) -> `UNAVAILABLE` — the same family
  the untyped fall-through answered with before, so adopting the seam
  changes the projection's truthfulness (`internalCode` is now the domain
  code, not the exception class name), not the family a client sees.

`CATALOG_*`, `PROFILE_NOT_FOUND`, `PROFILE_HARNESS_MISMATCH` and
`WORKSPACE_ARCHIVED` keep the families the compat surface already publishes
for those frozen code strings, so a product composition that runs both
plugins stages duplicate rows with identical families (co-legible) rather
than a conflict that would refuse the activation round.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any

from server_plugin_api import ServerError

from .api.errors import AssetDomainError

#: The code -> family mapping contributed to
#: ``server_plugin_api.WIRE_ERROR_FAMILIES_POINT_ID`` (api_version
#: ``WIRE_ERROR_FAMILIES_API_VERSION``). One table, declared atomically —
#: same discipline as the `skills.*` method family in `wire.py`.
SKILLS_ERROR_FAMILIES = MappingProxyType({
    # -- request shape/value refusals ------------------------------------
    "INVALID_REQUEST": "INVALID_REQUEST",
    "ASSET_INVALID": "INVALID_REQUEST",
    "ASSET_KIND_NOT_SKILL": "INVALID_REQUEST",
    "ASSIGNMENT_INVALID": "INVALID_REQUEST",
    "CATALOG_INVALID": "INVALID_REQUEST",
    "CATALOG_KINDS": "INVALID_REQUEST",
    "CATALOG_ORIGIN_MISSING": "INVALID_REQUEST",
    "CATALOG_SOURCE_MISSING": "INVALID_REQUEST",
    "CATALOG_ENTRY_UNKNOWN": "INVALID_REQUEST",
    "IMPORT_PATH_INVALID": "INVALID_REQUEST",
    "IMPORT_DIGEST_MISMATCH": "INVALID_REQUEST",
    "IMPORT_CONTENT_DRIFTED": "INVALID_REQUEST",
    "IMPORT_BOUNDS_EXCEEDED": "INVALID_REQUEST",
    "IMPORT_SESSION_INVALID": "INVALID_REQUEST",
    "SESSION_OVERRIDE_INVALID": "INVALID_REQUEST",
    "PREVIEW_REFUSED": "INVALID_REQUEST",
    "SCOPE_INJECTION_MISSING": "INVALID_REQUEST",
    "SKILL_FRONTMATTER_MISSING": "INVALID_REQUEST",
    "SKILL_FRONTMATTER_INVALID": "INVALID_REQUEST",
    "SKILL_DESCRIPTION_MISSING": "INVALID_REQUEST",
    "SKILL_DESCRIPTION_INVALID": "INVALID_REQUEST",
    "SKILL_ASSET_MISSING": "INVALID_REQUEST",
    "SKILL_ASSET_INVALID": "INVALID_REQUEST",
    "SKILL_NAME_INVALID": "INVALID_REQUEST",
    "NATIVE_DISCOVERY_ROOT_INVALID": "INVALID_REQUEST",
    "NATIVE_DISCOVERY_SLOT_INVALID": "INVALID_REQUEST",
    "NATIVE_DISCOVERY_BUDGET_EXCEEDED": "INVALID_REQUEST",
    "SKILL_INTENT_INVALID": "INVALID_REQUEST",
    "SKILL_INTENT_HOST_PATH": "INVALID_REQUEST",
    "SKILL_INTENT_UNBOUNDED": "INVALID_REQUEST",
    # -- unknown ids in this data domain ---------------------------------
    "ASSET_NOT_FOUND": "NOT_FOUND",
    "ASSET_REVISION_UNKNOWN": "NOT_FOUND",
    "ASSIGNMENT_NOT_FOUND": "NOT_FOUND",
    "ASSIGNMENT_ASSET_UNKNOWN": "NOT_FOUND",
    "BINDING_NOT_FOUND": "NOT_FOUND",
    "SOURCE_UNKNOWN": "NOT_FOUND",
    "WORKSPACE_UNKNOWN": "NOT_FOUND",
    "PROFILE_UNKNOWN": "NOT_FOUND",
    "PROFILE_NOT_FOUND": "NOT_FOUND",
    "SKILL_APPROVAL_MISSING": "NOT_FOUND",
    # -- version CAS and stale-generation moves ---------------------------
    "ASSIGNMENT_VERSION_CONFLICT": "CONFLICT_VERSION",
    "BINDING_VERSION_CONFLICT": "CONFLICT_VERSION",
    "SKILL_APPROVAL_DIGEST_MISMATCH": "CONFLICT_VERSION",
    "SNAPSHOT_STALE": "CONFLICT_VERSION",
    # -- state conflicts that are not a version CAS ------------------------
    "ASSIGNMENT_DUPLICATE": "CONFLICT_REQUEST",
    "SKILL_REVISION_EXISTS": "CONFLICT_REQUEST",
    "CANNOT_DISABLE": "CONFLICT_REQUEST",
    "SKILL_IN_USE": "CONFLICT_REQUEST",
    "SKILL_PINNED": "CONFLICT_REQUEST",
    "PROFILE_HARNESS_MISMATCH": "CONFLICT_REQUEST",
    "WORKSPACE_ARCHIVED": "CONFLICT_REQUEST",
    "HARNESS_VERSION_MISMATCH": "CONFLICT_REQUEST",
    # an assignment that contradicts the administrator ceiling: deterministic
    # state conflict, never a retry that can succeed (mandatory_policy.py)
    "MANDATORY_POLICY_CONFLICT": "CONFLICT_REQUEST",
    # -- referenced-but-foreign targets ------------------------------------
    "RESOLUTION_FOREIGN_CONTENT": "CONFLICT_REFERENCE",
    "SNAPSHOT_TARGET_MISMATCH": "CONFLICT_REFERENCE",
    "SKILL_NAME_COLLISION": "CONFLICT_REFERENCE",
    # -- seams this composition has not composed ---------------------------
    "PROFILE_LAYER_UNAVAILABLE": "UNAVAILABLE",
    # the mandatory layer could not be read (no surface composed / store
    # outage / untrusted provenance): retryable once permissions is reachable,
    # and above all NOT reported as "no constraint applies"
    "MANDATORY_POLICY_UNAVAILABLE": "UNAVAILABLE",
    "NATIVE_TARGET_ROOT_UNAVAILABLE": "UNAVAILABLE",
    "ASSIGNMENT_SCHEMA_UNAVAILABLE": "UNAVAILABLE",
    "BINDING_CAS_UNAVAILABLE": "UNAVAILABLE",
})

#: HTTP statuses for the internal-error object (the REST surface of this
#: family is §G1's; the wire/1 projection only reads `code`).
_STATUS_BY_FAMILY = {
    "INVALID_REQUEST": 400,
    "NOT_FOUND": 404,
    "CONFLICT_VERSION": 409,
    "CONFLICT_REQUEST": 409,
    "CONFLICT_REFERENCE": 409,
    "UNAVAILABLE": 503,
}

#: The seam-unavailable half answers retryable; the rest is deterministic.
_RETRYABLE_FAMILIES = frozenset({"UNAVAILABLE"})


def to_server_error(exc: AssetDomainError) -> ServerError:
    """Project one domain refusal onto the published internal-error type.

    The domain keeps raising its own `AssetDomainError` (the stores and the
    resolver refuse in their own vocabulary — tests and callers catch that
    type); the wire layer converts at the boundary so the host's dispatch
    resolves the family through THIS composition's contributed table
    instead of flattening every handler exception into
    `UNAVAILABLE/internalCode=<exception class>`. `code` and `message` are
    carried verbatim — the frozen code spellings of `api/errors.py` are the
    contract, not the class name.
    """
    family = SKILLS_ERROR_FAMILIES.get(exc.code, "UNAVAILABLE")
    return ServerError(
        exc.code,
        f"{exc.message}{f' ({exc.detail})' if exc.detail else ''}",
        status=_STATUS_BY_FAMILY.get(family, 503),
        retryable=family in _RETRYABLE_FAMILIES,
    )


__all__ = ["SKILLS_ERROR_FAMILIES", "to_server_error"]
