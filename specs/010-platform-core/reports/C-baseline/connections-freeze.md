# C6 / T026 freeze — pre-existing Agent connection tests and close-call chain

Baseline commit for the frozen shapes: `a08367ef59` (T017 commit on this lane).
Purpose: the Connections platform (T026 tests → T027 implementation → T028
facade relocation) must not silently weaken anything the Agent-side connection
tests already prove. CN-07 (contract `connections-platform.md` §7) is verified
against this file: after T028 every ID below still exists, still runs, and still
asserts the same close/release semantics — relocation may change file paths and
imports only.

## Frozen test inventory (12 IDs)

`apps/desktop/renderer/agent-connections.test.ts` (455 lines, 11 IDs — these are
already listed in `desktop.ids.txt` from the T003 baseline freeze):

1. `lets independent adapters register and releases each with its own scope`
2. `gate predicates match run/interaction state only, across every connection`
3. `switching views over live work keeps the previous client, its run and its approvals alive`
4. `gates reconnect with the same authority as switching and restores it once live work clears`
5. `a release that fails after the reconnect completed reaches the subscriber and the snapshot on its own, and the explicit passes settle it`
6. `a cleanup pass started while the first release is in-flight joins that request and keeps the reference for the failure that follows`
7. `a release that failed before the eviction is seeded into the host view the moment the reference is taken over`
8. `a client whose first release confirms while another channel is still acquiring is forgotten only after that later release settles`
9. `evicting a client without the managed-release lifecycle retains nothing to confirm`
10. `re-evaluates the gate once a held handshake lands, so reconnect cannot cancel a run started during it`
11. `leaves the connecting indicator owned by the handshake that is still pending`

`apps/desktop/renderer/agent-connections-status.test.tsx` (106 lines, 1 ID):

12. `the status bar shows a late release failure automatically, with no selection or click after it lands`

Also in scope as consumer-side regressions (their IDs stay in `desktop.ids.txt`,
not duplicated here): `agent-ordessa-connector.test.ts`, `agent-acp-wiring.test.ts`,
`agent-sessions*.test.*`, `agent-conversation.test.tsx`.

## Frozen close-call chain (current ownership, before T028)

Source of truth: `plugins/connections/service/src/{entry.tsx,workspace.ts}` and
the fake client in `agent-connections.test.ts:147-235`.

| Step | Current behaviour the tests depend on |
| --- | --- |
| Registration | `service.forScope(scope).add({ id, title, connect })`; unmounting that scope removes the registration; adding after scope disposal throws `closed`; snapshot is identity-stable (`getSnapshot() === getSnapshot()`) and every register/unregister notifies subscribers (ID 1 asserts exactly 3 notifications). |
| Open | `service.connect(id)` → `connector.connect()` → an `AgentClient`. Reconnect/`connect` on an unavailable id rejects with `Agent connection unavailable: <id>`. An in-flight handshake for the same id is joined, never doubled. |
| Local close | `AgentClient.dispose()` is **synchronous and only STARTS** the backend stand-down: it announces `in-flight` release states to `subscribeReleaseStates` listeners, and `releasesSettled` resolves only when disposed AND no acquire remains AND nothing stands unconfirmed (ID 5-9). |
| Confirmation | The workspace keeps a `retired` reference per evicted client, seeded from `releaseStates()` **before** disposal (ID 7), re-publishes on every announced transition, and forgets the client only on its own `releasesSettled` attestation — never on an empty live view (ID 8). A client without the managed-release lifecycle retains nothing (ID 9). |
| Explicit retry | `retryReleaseCleanup()` gives each retained client one further attempt, joins an in-flight attempt, and rethrows the first refusal; no automatic retry loop (ID 5, and the `Retry backend release` affordance in ID 12). |
| Business gate | `selectConnection` is view-only: it keeps the previous client, its open run and its pending approvals alive (ID 3). `reconnect` gates on `hasOpenRun`/`hasAwaitingInteraction` over the gated snapshot set and re-evaluates after an awaited handshake lands (ID 4, 10). |
| Indicator ownership | `connectingId` is cleared only by the handshake that owns it (ID 11). |
| UI | Status-bar popover lists connections (`data-connection-id`), and a late release failure surfaces without any user action, with the Retry button (ID 12). |

## What T027/T028 may and may not change

- **May**: move the generic registry/open/close/state/settlement half into
  `@ordessa/connections` (CN-01–CN-06 semantics); move the Agent workspace,
  status UI and gate logic to `plugins/agent/connections` keeping extension id
  `ordessa.agent-connections`; have the Agent facade obtain its clients through
  the platform (`Connector.open` → `ConnectionEndpoint.closeLocal`).
- **Must not**: bind `closeLocal` unaudited to `AgentClient.dispose` such that
  the managed-release lifecycle (announcement, seeding before disposal,
  `releasesSettled` attestation, explicit retry) is lost or inferred from an
  empty record; the local release and the backend stand-down bookkeeping stay
  two distinct, both-observable steps in the facade.
- **Must not**: turn the view-only selection into a teardown, drop the reconnect
  gate, or let the platform perform any business action (§4: no
  run/approval/session/model/provider semantics in the platform).
- **Must**: keep scope unmount releasing connections through `closeLocal`
  exactly once (new-platform tests `CN-03`, `CN-06` and the §5.5 settlement test
  in `packages/desktop-platform/connections/tests/connections.test.ts` already
  assert this) while the Agent-side IDs above still observe their asynchronous
  confirmation chain.

## Mapping: frozen Agent-side semantics → new platform CN tests

| Frozen concern | Platform-side counterpart (T026 tests) |
| --- | --- |
| per-scope registration/unmount | CN-02 `registrant scope closed removes the registration and rejects before connector.open` |
| duplicate stable id | CN-02 `duplicate connector id is rejected at registration` |
| independent instances per scope | CN-04 |
| close started, not confirmed | CN-05 `close_failed` honesty + CN-06 `transportCalls` |
| async cleanup visibility | §5.5 `whenSettled` settlement report |
| cancellation | §5 `aborting the caller signal cancels a not-yet-finished open` |
| backend stand-down confirmation | **stays Agent-side** — no platform test may claim it (CN-07) |
