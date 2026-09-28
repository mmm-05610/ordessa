# ordessa-permissions-backend

The §C1 authorizer service and the single authoritative store for approval
facts (`server_approvals`). Public seam only: everything arrives through
`server_plugin_api` types and the injected `database` port; nothing here
imports a host, the compatibility layer, or the harness
(`tests/test_backend_dependency_direction.py` enforces it).

This README documents the **single-writer migration** for the old
`approvals.decide` route (C0's integration request #2, spec
`specs/011-c0-foundation-harness/api-requests.md`) and the deactivation
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

## What C0 must still do (composition's half — NOT done here)

This package never edits or unregisters `plugins/server-compat`. To
complete the single-writer migration before enabling Q5 Permissions
backend in production:

1. **Retire or delegate the compat route, one of the two:**
   * *Retire*: remove `approvals.decide` from the compat product assembly
     (and its `TransitionCorePlugin` declaration), or
   * *Delegate*: remove the compat registration and enable this plugin
     with `approval_route="legacy-delegated"`, keeping the old wire name
     alive for clients. Both cannot coexist — the host refuses it
     (`DuplicateMethodError`); take that refusal as the checklist that the
     retirement ordering is right: retire the old owner FIRST, then
     activate the delegated plugin (proven in
     `tests/test_legacy_delegate.py::test_enabling_the_delegate_beside_a_live_old_writer_refuses_at_activation`).
2. **Old rows are intentionally not legacy-decidable any more.** Rows the
   old writer created carry no native correlation; through the delegated
   route their decide is refused typed. Re-requesting approval through the
   Q5 gate is the path for still-live operations; existing data keeps its
   IDs/table/events and remains readable and queryable.
3. **Activate the plugin only after step 1** — activating it beside the
   compat writer is exactly the dual-writer counterexample C0 recorded,
   and the platform-level refusal above will surface it at startup.
4. Native-receipt plumbing and the product wiring of the admission
   evidence sources (`acp.admission.native_evidence`,
   `acp.admission.principal`, `server.instance_id`) stay C0-owned seams
   (G1/G2); this package answers `ready=False` without them.
5. **The submission fence still needs a mintable permit record (T021).**
   `PermissionsHostAcpAuthority` can already be the ACP fence's verifier for
   tool execution — that half answers a plain bool and the fence admits only
   `is True`, so no host type is involved. The submission half it refuses:
   the fence re-checks the permit against a frozen record the host owns
   (`apps/server/src/ordessa_server/acp_admission.py:134`), that record is not
   published in `server_plugin_api`, the prompt digest is computed by the
   host's private canonicalisation, and only the host's own refusal type
   survives the public port adapter as a typed code. Publish a mintable permit
   record (and a public refusal type), or install a host-side authority over
   `ports[acp.admission.gate]`, and drop it in as this authority's
   `permit_binder`. Until then `bootstrap/runtime.py:607` keeps building the
   gate with no authority and the port stays `ready=False`;
   `tests/test_host_pre_effect_l2.py` pins both that refusal and the gap.
   Ordering note: the ruling is made before the binder is consulted, so an
   approval-bound allow spends its one-use grant while still admitting
   nothing — never install this authority without a binder.

## Tests

```
.venv/bin/python -m pytest plugins/permissions/backend -q
```

175 tests: 24 of them are the T018/T019 lane above, 17 are the T021 L2
pre-effect lane (`test_host_pre_effect_l2.py`), which drives the host's real
ACP admission gate, port adapter and relay fence against this package's real
authorizer and facts store on a temp-dir product database, with an in-process
fake Agent channel as the side-effect recorder. The remaining 134 pre-existing
backend tests stay green; no assertion was deleted or skipped for any binding.
