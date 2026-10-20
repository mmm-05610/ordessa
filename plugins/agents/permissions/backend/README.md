# ordessa-permissions-backend

The §C1 authorizer service and the single authoritative store for approval
facts (`server_approvals`). Public seam only: everything arrives through
`server_plugin_api` types and the injected `database` port; nothing here
imports a host, the compatibility layer, or the harness
(`tests/test_backend_dependency_direction.py` enforces it).

This README documents the **single-writer migration** for the old
`approvals.decide` route (C0's integration request #2, spec
`docs/implementation/specifications/011-c0-foundation-harness/api-requests.md`) and the deactivation
binding (request #1). **Merely activating this plugin is NOT the migration.**

## What is implemented here (the backend's half)

### T018 — `busy()` binds to host deactivation

`PermissionsBackendPlugin.build()` declares the platform's real lifecycle
surface on the registration:

* `stop_hooks` — run by `ServerPluginHost.run_stop_hooks()` (the phase
  `ServerRuntime.stop()` enters first, reverse activation order, before any
  disposal; a raising hook propagates to the caller by platform design). The
  hook reads the T02 `busy()` fact:
  * a decision/admission call executing right now →
    `ContributionOwnerBusyError` (the platform's own refusal type; a live
    reference is never stolen);
  * any open approval or settled-allow grant without a reconciled native
    receipt (`busy() > 0`) → `PermissionsBackendBusyError` — the
    deactivation is refused while the provider stays active, so every row
    stays queryable **and settleable** through the still-live routes;
  * only when `busy() == 0` does the accepted stop close the decision routes:
    afterwards `permissions.approvals.decide`, the delegated
    `approvals.decide`, and the `acp.admission.gate` grant calls refuse
    (`ApprovalRouteClosedError` / typed admission refusal) — a new decision
    can no longer be taken against a provider that is leaving; reads stay
    served.
* `disposal` — the mirror refusal for unload paths that skipped the stop
  phase (`host.deactivate()` does not run stop hooks; the platform disposes
  directly). Disposing with unresolved facts raises; the row is never
  silently dropped with the provider.

Proofs: `tests/test_deactivation_binding.py` (including the real
`ServerPluginHost` sequence refuse → settle + reconcile → stop → shutdown).

### T019 — the old wire method behind ONE authorizer

`delegate.py` provides `LegacyApprovalDelegate`: the OLD
`approvals.decide` wire shape — params mirrored exactly from the compat
core's declaration table `core_wire._PARAM_SHAPES`
(`requestId, approvalId, expectedVersion, decision, scope`; no optional
params, **no `sessionId`**), including the old scope validation — routed
into the SAME `Authorizer.decide` that serves
`permissions.approvals.decide`. One authority, one `server_approvals`
store, one `approval.requested`/`approval.settled` event stream; existing
IDs, CAS on `version` and `decideRequestId` idempotency are preserved.

Fail-closed additions required by the migration rule:

* a row missing the native **operation / session / generation** facts a
  grant needs (`nativeRequestId`, `operationDigest`, `nativeGeneration`,
  session binding) is **refused typed (`outcome: "unknown"`, reason
  `native_facts_missing:…`) before anything is written** — a row the old
  writer minted can no longer be flipped to a decision through the old
  route; missing facts are never treated as permitted;
* the route is **gated**: it exists only for
  `PermissionsBackendPlugin(approval_route="legacy-delegated")`; the
  default (`"q5-only"`) declares no legacy method at all;
* coexisting writers are detected, not tolerated: while the compat route is
  registered, activating the delegated plugin is a platform
  `DuplicateMethodError` (one method id, two owners → typed startup refusal,
  round rolled back); if composition ever hands this plugin a live old
  writer port (`approvals.records` / `compat.handlers`), `build()` refuses
  with `DualAuthorityError`. And at the data level
  (`tests/test_dual_authority.py`), even if both handlers were wired to the
  same database, two settled outcomes for one row remain impossible.

## Current composition boundary and historical migration

The old `plugins/server-compat` source and registration are retired. This backend is the only Permissions plugin owner; Host composition owns admission evidence and injects public ports. No legacy implementation is delegated to or used as a fallback. The explicit `legacy-delegated` option preserves a historical wire method name only; duplicate-owner refusal tests preserve the single-writer guard. These options do not re-enable historical rows or create production readiness.

The following constraints retain historical data and describe the remaining product wiring:

2. **Old rows are intentionally not legacy-decidable any more.** Rows the
   old writer created carry no native correlation; through the delegated
   route their decide is refused typed. Re-requesting approval through the
   Q5 gate is the path for still-live operations; existing data keeps its
   IDs/table/events and remains readable and queryable.
3. Activate only the selected Permissions owner. A duplicate writer still
   fails the platform registration guard; retired compatibility routes must
   never be restored.
4. Native-receipt plumbing and the product wiring of the admission
   evidence sources (`acp.admission.native_evidence`,
   `acp.admission.principal`, `server.instance_id`) stay C0-owned seams
   (G1/G2); this package answers `ready=False` without them.
5. **The submission fence still needs a mintable permit record (T021).**
   `PermissionsHostAcpAuthority` can already be the ACP fence's verifier for
   tool execution — that half answers a plain bool and the fence admits only
   `is True`, so no host type is involved. The submission half it refuses:
   the fence re-checks the permit against a frozen record the host owns
   (`packages/interfaces/server/plugin-api/src/server_plugin_api/acp_admission.py`), its contract is
   published in `server_plugin_api`, the prompt digest is computed by the
   host's private canonicalisation, and only the host's own refusal type
   survives the public port adapter as a typed code. Bind the original public permit/refusal contract through a Host-side authority over
   `ports[acp.admission.gate]`, and drop it in as this authority's
   `permit_binder`. Until then the Host composition keeps building the
   gate with no authority and the port stays `ready=False`;
   `tests/test_host_pre_effect_l2.py` pins both that refusal and the gap.
   Ordering note: the ruling is made before the binder is consulted, so an
   approval-bound allow spends its one-use grant while still admitting
   nothing — never install this authority without a binder.

## Tests

```
.venv-nightly/bin/python -m pytest -q plugins/agents/permissions/backend
```

Historical checkpoint: the earlier 175-test count above was recorded for its
then-current source snapshot and is not a current suite total. The current
recorded backend result is 182 passed with zero skips after the partial-schema
fail-closed cases were added; see
`docs/verification/overnight-upper-structure-20261009/migration-checklist.md`
for the current evidence and its exact scope. This README does not claim a
new test run from this documentation-path repair.
