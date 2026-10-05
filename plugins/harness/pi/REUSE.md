# Pi AU003 reuse decision

Reviewed source in this worktree (not Internet version claims):

* `adapters/acp-adapter/internal/pi/client.go` implements native JSONL behind
  ACP and translates Pi events into Codex-shaped TurnEvent (lines 51 onwards).
  `setModel` sends `provider` / `modelId`; `setThinkingLevel` sends `level`
  (lines 835–847). Reuse these native field facts; avoid imposing that event
  translation on the native entry. Go bridge remains useful for ACP consumers,
  but is not independently packageable here without its shared adapter and
  deployment binary. No additional Go binary is built or shipped by this slice.
* `packaging/pi-profile/configuration-operation.mjs` has mature bounded native
  attempt/readback evidence and per-session exclusion. Reuse its distinction
  between ACK, observed readback and retained original attempt; do not copy its
  separate in-memory operation map into a second Python journal. Deployment must
  supply original confirmation receipts in the existing owner journal.
* `src/ordessa_harness/pi/configuration/live_model.py` compiles verified ACP
  catalog selections. Its credential/endpoint checks are useful; this package
  deliberately offers only native provider/model selection, not provider secret
  installation or endpoint rewriting. No Profile fills missing actual state.
* `src/ordessa_harness/pi/provider.py` depends on `pacthold_runtime_compat` and
  reports terminal success from process status. Do not revive this route.
* Former product `native_clients/pi.py` already preserves 0.86.1 raw JSONL,
  unknown records, receipt versus settled, unknown-send fencing and exact UI
  dialog reply guards. These protocol mechanics migrate into `client.py`; public
  framing/process primitives import the common `ordessa_harness_transport`.
  The tests migrate with their source. This migration alone is not provider
  completion: new `provider.py` implements actual native configuration reads,
  write-before-readback, scoped attempt confirmations and typed absence.

Selected route: native Pi RPC 0.86.1. No implicit ACP fallback, startup,
installation, model call or login access. Preparation/start/connect/stop/release/
recover remain absent from supportedMethods until trusted Unit composition is
implemented. Configuration effects require both a current Unit owner and an
existing-journal confirmation port. Native ACK without readback/receipt remains
unknown. Owner ports must verify the actual installation/session, current
activation/directory/epoch, and channel writer lease on every dispatch. Package
imports/registration do not start anything; package `pi` keeps provider/family ID
`pi`. Unit identity and persistent data are untouched.

Evidence levels: migrated Python tests and new provider fixtures are C; existing
fixture subprocess tests are C with real Python peers, not Pi P. No Pi P or M was
run by this executor. Cost/model calls: 0.
