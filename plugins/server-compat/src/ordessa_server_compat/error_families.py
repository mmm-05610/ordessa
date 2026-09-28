"""The wire/1 error families owned by the compatibility core (T014-S2a).

`ordessa.server-compat` raises these internal ServerError codes — profile,
session, turn, queue, approval, credential, model, asset/catalog, artifact,
execution and sidecar-worker vocabulary — so their `code -> family` rows live
here, next to the code that produces them, and reach the host's wire/1 error
surface as a `wire.error-families` contribution published by this plugin
(`plugin.py`). They are not copied into the host's `_BY_CODE` table any more:
a composition without this plugin answers these codes with the documented
fall-through (`UNAVAILABLE`), which is the honest typed absence.

Order 147 (`AUD-B-037`) note that travelled with the four `CATALOG_*` rows:
the asset surface's own domain codes were once hardcoded to `INVALID_REQUEST`
in five fallback copies; registering them lets the one shared path assign the
family while `details.internalCode` carries the precise code (the shape order
115 fixed). Client-side catalog problems stay `INVALID_REQUEST` — the
reviewer's ①-④ wording must not drift.

`PROFILE_NOT_FOUND` ownership, stated rather than left ambiguous: the code is
also named in `plugins/harness` (a refusal message), but the profile records
that answer NOT_FOUND are this plugin's, so the row belongs here; harness
never contributes the code.

`SECRET_FIELD_FORBIDDEN` and `CAPABILITY_UNSUPPORTED` are deliberately NOT in
this table even though compat raises them too: pacthold's kernel vocabulary
produces the same codes, and a kernel word must not be re-homed into a
plugin. They stay host-owned rows in `ordessa_server.wire.errors`.
"""
from __future__ import annotations

from types import MappingProxyType

#: The plugin's published mapping. The handler stages/commits/rolls this
#: exact object: its identity is the transaction token, so it must be a
#: module-level singleton, never a fresh copy per build.
COMPAT_ERROR_FAMILIES = MappingProxyType({
    "PROFILE_REVISION_CONFLICT": "CONFLICT_VERSION",
    "QUEUE_VERSION_CONFLICT": "CONFLICT_VERSION",
    "APPROVAL_VERSION_CONFLICT": "CONFLICT_VERSION",
    "REFERENCE_CONFLICT": "CONFLICT_REFERENCE",
    "PROFILE_NOT_FOUND": "NOT_FOUND",
    "SESSION_NOT_FOUND": "NOT_FOUND",
    "TURN_NOT_FOUND": "NOT_FOUND",
    "QUEUE_ITEM_NOT_FOUND": "NOT_FOUND",
    "APPROVAL_NOT_FOUND": "NOT_FOUND",
    "PROVIDER_MODEL_NOT_FOUND": "NOT_FOUND",
    "PROFILE_CONFIGURATION_INVALID": "INVALID_REQUEST",
    "TURN_OVERRIDES_INVALID": "INVALID_REQUEST",
    "HARNESS_UNAVAILABLE": "CAPABILITY_UNSUPPORTED",
    "EXECUTION_CAPABILITY_UNAVAILABLE": "UNAVAILABLE",
    "CREDENTIAL_SOURCE_NOT_AUTHORIZED": "UNAVAILABLE",
    "WORKER_DISCONNECTED": "WORKER_UNREACHABLE",
    "DISPATCH_AMBIGUOUS": "OUTCOME_UNKNOWN",
    "OUTCOME_UNKNOWN": "OUTCOME_UNKNOWN",
    "PROFILE_RECOVERY_REQUIRED": "CONFLICT_REQUEST",
    "PROFILE_ARCHIVED": "CONFLICT_REQUEST",
    "SESSION_ARCHIVED": "CONFLICT_REQUEST",
    "WORKSPACE_ARCHIVED": "CONFLICT_REQUEST",
    "TURN_CONCURRENCY_CONFLICT": "CONFLICT_REQUEST",
    "PROFILE_HARNESS_MISMATCH": "CONFLICT_REQUEST",
    "SESSION_STORE_GUARD_UNAVAILABLE": "CONFLICT_REQUEST",
    "SESSION_STORE_CREDENTIALS_PRESENT": "CONFLICT_REQUEST",
    "SESSION_STORE_GUARD_STRUCTURE": "CONFLICT_REQUEST",
    "EVENT_CURSOR_AHEAD": "INVALID_REQUEST",
    "CATALOG_INVALID": "INVALID_REQUEST",
    "CATALOG_SOURCE_MISSING": "INVALID_REQUEST",
    "CATALOG_ORIGIN_MISSING": "INVALID_REQUEST",
    "CATALOG_ENTRY_UNKNOWN": "INVALID_REQUEST",
})
