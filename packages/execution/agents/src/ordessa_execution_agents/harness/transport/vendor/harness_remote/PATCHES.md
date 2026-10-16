# PATCHES — harness-remote v3.0.2 (commit 21ce6db49af708c4c7c3f96ef6a50f62dced8dab)

Apache-2.0 notice: this directory contains unmodified source from the upstream
repository listed in `SOURCE.json` except for the changes recorded here.
Upstream copyright and the Apache License 2.0 text in `LICENSE` apply; the
AgentBox modifications below are marked in-file with `PATCH (AgentBox ...)`.

## 1. `bridge/src/acp-client.js` — asynchronous permission resolver

Upstream `#respondPermission` answers `session/request_permission` immediately:
with `permissionMode: "allow"` it statically picks `allow_once` (falling back to
`allow_always` and any `allow*`), otherwise it answers `cancelled`. That
shortcut cannot preserve a Core/user approval policy, so approval-requiring
tools could never be enabled safely.

The patch adds two constructor options and keeps the static path unchanged when
they are absent:

- `permissionResolver`: an async function `({ toolCall, options }) => optionId | null | undefined`.
  Its awaited decision owns the answer. Returning an `optionId` present in
  `options` selects it; returning `null`/`undefined`, throwing, or timing out
  denies (`{ outcome: "cancelled" }`). Unanswered requests therefore default to
  deny, never allow.
- `permissionTimeoutMs`: optional bound; expiry denies.

After the await the patch re-checks child identity and stdin writability, so a
decision that arrives after a disconnect or reconnect is never written to the
wrong child.

## 2. `bridge/src/acp-registration.js` — new file, mechanical factory export

Upstream builds one profile's ACP registration inline inside `daemon-cli.js`
(one user-facing `AcpClient`, one prompt-less `AcpAgentModelCatalog`
connection, the capability contract, and `AcpService` options). Harness
Remote's embedders must not adopt `daemon-cli.js`/`machine-daemon.js` as a
second product authority, so this block was moved into an exported,
upstream-namespace factory `createAcpRegistration()` with identical
construction. The only behavioral addition is forwarding the Section 1
permission options into the user-facing client.

Adopted as allowed by the Work Order 38 reuse boundary ("a production
extraction may move that block into an exported upstream-owned factory as a
mechanical patch").

## 3. `bridge/src/acp-service.js` — grouped config options in model selection

An ACP `select` config option may arrive grouped: each top-level entry carries
a `group`/`name` header plus its own nested `options` array of the real
candidates. DeepSeek dsh 0.1.5-rc.1 ships its `model` picker in exactly this
shape (observed first-hand over `session/new`; see
`docs/server-round1/fullstack/dsh-production-packaging.md`). Upstream
`setModel()` matched only the top level, where group headers carry no `value`,
so every model selection against a grouped picker failed with "Harness model
is not available" - the harness could never be driven to the model the product
selected.

The patch flattens exactly one level of nested `options` before the existing
match chain (exact value, value after the synthesized provider separator,
then the Claude `[1m]` selectable-value rule). Nothing else changes: the
selection is still sent as `session/set_config_option` with the harness's own
opaque value, non-grouped pickers flatten to themselves, and no harness name
appears in the patch. Provenance is recorded in `SOURCE.json`
(`patched_sha256`).

## 4. `bridge/src/acp-service.js` — the turn's own `stopReason` is kept

Upstream fires the ACP `session/prompt` request for a turn and drops its response
(`void this.#acp.request(...)`), while `promptAndWait`'s success path called
`resolve()` with no value. The harness's machine-readable terminal statement —
`{ stopReason }` on the JSON-RPC result — was therefore lost at the bridge, and
every completion leg above it could only ever see "done". A field added further
up cannot recover a value that was already discarded here.

The patch keeps the response and hands it back, bound to the turn that produced
it:

- `#turnResponses` stores the response under `${sessionID}:${generation}`, using
  the same generation guard the failure and `finally` paths already use. A turn
  whose generation has moved on (cancelled, superseded) stores nothing, so one
  turn's reason can never be handed to another — including two Sessions at once.
- `promptAndWait` resolves with the **finished** generation's response, taken
  once (`#takeTurnResponse`). It is `undefined` when there is none, which leaves
  the caller's existing absent/unknown semantics untouched.
- `#startTurn` drops responses left behind by an earlier generation, so nothing
  accumulates.

The upstream value is preserved verbatim: no `stopReason` is synthesised, no
absent field is filled in, and a missing field stays missing. What the real
harnesses report is still a later verification question — the fake peer is what
this seam is exercised with.

## 5. `bridge/src/acp-client.js` — the stdout line buffer is per-process, and flushed on the way out

Upstream `#start` resets `#stderr` and `#stderrPartial` for every attempt — the in-file comment
records why: carrying that buffer across restarts made each exit message repeat all the previous
ones. `#buffer`, the stdout side of the same boundary problem, was never reset. A process that died
mid-frame therefore left its tail bytes in the buffer, and the next process's first message arrived
prefixed with them. Measured on this snapshot: the response to the new process's `initialize` was
consumed as part of the stale line, so a restart never completed the handshake and hung until
`ACP adapter request timed out: initialize`.

The same `#buffer` also made the *last* frame of a run disappear. `#consume` only dispatches text up
to a newline, so a final frame written without one stays in the buffer, and neither `close()` nor
the `exit` handler looked at it. Because a `session/prompt` response is frequently the last frame an
adapter writes before exiting, a turn could end with no answer reaching the caller and no trace of
why.

This patch keeps the frame rules untouched and fixes only the buffer's lifetime:

- `#start` clears `#buffer` alongside the two stderr fields, so a restart begins clean.
- New `#flushBuffer()` hands whatever is left to the existing `#consumeMessage`, called from the
  `exit` handler (before the exit is reported and pending work is rejected, while the child
  identity is still this one) and from `close()` (before the child is dropped). `#consume` never
  leaves more than one newline-free fragment in the buffer, so this is at most one frame.
- Unparseable residue takes the existing `protocol-error` channel. No new event type, no change to
  what the bridge projects outward: this is the internal frame lifecycle only.

Deliberately **not** in this patch: an orphan response (`id` absent from `#pending`) and a
well-formed JSON message carrying neither `id` nor `method` still produce no event. Making those
visible adds an observable on the bridge's internal event bus and belongs to the frame-layer
replacement, where it can be checked against the six-row baseline invariant at the same time
(AgentBox H, central ruling `H-increment1b-framebuffer.md` §3).

> Numbering note: the central approval for the truncation-visibility work (`H-increment1-truncation.md`)
> called the `acp-service.js` change "补丁#5", but `acp-client.js` above claimed §5 first — both
> increments were approved in the same window. Patch #4 is this file's `acp-service.js` stopReason
> retention; the truncation-visibility change that follows is §6. The section number carries no
> meaning beyond order of writing; the `PATCH (AgentBox 增量1)` markers in the source are the
> authority for what belongs to this patch.

## 6. `bridge/src/acp-service.js` — a turn's silent tail and its missing stopReason become facts

Patch #4 stopped discarding the `session/prompt` response, but it left two things unreadable on the
completion leg, both measured against this snapshot before the change (AgentBox H, `H2-current-state-map.md`
§6b X1–X3):

- A turn whose response carried no `stopReason` resolved exactly like a turn that ended cleanly.
  Nothing upstream could distinguish "the harness said `end_turn`" from "the harness said nothing",
  so a truncated answer was reported as a finished one.
- Once the drain window closed, `#handleNotification` returned early for a late assistant chunk.
  The chunk and the fact that it had been rejected both disappeared. With `promptSettleMs = 0`
  (every AgentBox profile until this round) the window never closed at all and the session stayed
  in `#promptedSessions` for its lifetime, so a *later* turn's chunks were folded into the earlier
  one — the "session still rewritten after completion" behaviour X1 measured.

This patch changes the reporting, not the accept/reject decision:

- `responseRecorded` distinguishes "answered without a stopReason" from "never answered". A turn
  that answered but did not report a reason now emits `session.stop_reason_not_reported` with the
  raw value (`null` when absent). It is deliberately **not** mapped to `end_turn`; a turn that
  errored is covered by `session.error` and cannot produce both.
- When a session's own drain window closes, that session enters `#tailWindowClosed`, and every
  assistant chunk rejected after that point emits `session.tail_dropped` with a running count and
  the character length of the text that was dropped. The pre-existing rejection is unchanged:
  this makes the loss visible, it does not widen the window or rescue the chunk.
- A new turn clears both records, so a count never bleeds from one turn into the next.
- Sessions with `promptSettleMs = 0` are never added to `#tailWindowClosed`. Their permissive
  historical behaviour (chunks after the response are accepted) is preserved verbatim; making a
  zero-drain profile opt into a real window is a per-profile value decision, and the five AgentBox
  profiles now declare one (see `runtime/profile_extensions.mjs`), which is what turns X1's
  unbounded rewrite into a bounded, reported window for them.

The events are emitted on the bridge's internal `AcpService` bus with the existing
`session.*`/`#emit(type, sessionId, extra)` convention. They are **not** part of the public wire:
projecting them into the execution surface is Server's call, and the envelope shape stays frozen
(central ruling R3, `message.final` → IFR-06).

## 7. `bridge/src/acp-client.js` — preserve adapter error causes

The Go acp-adapter returns a failed prompt as `message: "turn/start failed"`
with its cause in the string `data.error`. The existing formatter only read
`data.details` and `data.message`, discarding the cause before Worker error
classification. Add `data.error` as the last fallback, preserving the existing
precedence, string-only handling, and duplicate-detail suppression. Regression
coverage in `snapshot_seams.test.mjs` uses an actual AcpClient with a fake peer;
no Agent or model request is needed.

**Coverage note (HD-002).** `snapshot_seams.test.mjs` retired with the envelope
that owned it, so §7 no longer has a test. That is not an oversight to paper
over: in the transport-only mode the plugin now uses, `#consumeMessage` returns
before any error formatting (§8), so an adapter's `error` object reaches the
client untouched and there is nothing left to preserve. §7 remains in the source
only so that the default mode keeps matching upstream-plus-patch on an upgrade
rebase.

## 8. `bridge/src/acp-client.js` — transport-only mode

The plugin's access layer must hand a caller an ACP **transport**: spawn the
Adapter, relay frames both ways, and decide nothing. The client could not do
that, and no option or listener added from outside would let it, because the
decisions are structural:

* `#child` is assigned inside `#start()`, so there is no way to have a process
  without also having the handshake `#start()` performs — `initialize` with the
  bridge's own `clientInfo`, then an `authenticate` chosen from the Agent's
  advertised methods.
* `#consumeMessage()` routes by what the bridge itself asked for. A reply to an
  id it did not mint is dropped, and a client-bound request is answered from the
  bridge's own `permissionMode` / an "does not implement" `-32601`.
* `request()` mints its own ids and turns an Agent `error` into a JS `Error`.

Add one opt-in flag, `transportOnly`, and two caller-owned writes. With the flag
set, `#start()` returns after the pipes are wired — before the handshake — and
`#consumeMessage()` emits every parsed line as `frame` with its original text
and returns, bypassing routing, the watchdog and every auto-answer. `write()`
sends a frame the caller composed; `writeLine()` sends text verbatim, which is
what a byte-transparent relay needs (re-serialising would change the bytes the
Agent's peer signed). `cwd` is added for the same reason `spawn` is injectable:
the connection's working directory is the caller's, not this file's default.

The default path is untouched: `transportOnly` is `false` in the constructor and
every original statement still runs, so upstream behaviour — and the tests that
pin it (`acp_channel_behavior`, `frame_buffer_lifecycle`) — are unchanged. This
is the **minimal** bridge change, declared as required: the alternative of
leaving the bridge alone forces a second ACP client implementation in
`runtime/`, which is exactly the re-implementation this reuse boundary forbids.

Source record: `SOURCE.json` `bridge/src/acp-client.js` `current_sha256` is the
post-§8 hash, and each edit carries a `PATCH (AgentBox HD-002)` marker.

## 9. Snapshot narrowed to the transport closure

Eleven previously-vendored bridge files are removed with the runtime they
served — the Worker envelope, its session/turn/snapshot management, its model
catalogue bundling and its HTTP/task-routing helpers: `acp-registration.js`,
`acp-service.js`, `acp-prompt-echo-filter.js`, `agent-model-catalog.js`,
`agent-router.js`, `bounded-lru.js`, `harness-capability-contract.js`,
`http-policy.js`, `managed-event-fanout.js`, `task-model.js`,
`transcript-cache.js`. The snapshot is now the ten files the ACP transport
actually reaches, and `SOURCE.json` lists exactly those ten. The license is
unaffected: `LICENSE` covers the ten remaining files, all of which are upstream
work under the same terms at the same commit.

## Not adopted

`machine-daemon.js`, `daemon-cli.js`, `machine-registry.js`, `task-*`,
`worktree-*`, `work-thread-*`, `session-link-store`,
`session-operation-ledger`, `task-run-store`, `server.js`, `cli.js`,
`config.js`, `project-catalog.js`, `session-claim-server.js`,
`agent-model-server.js` and remaining bridge files stay out of this snapshot:
they own product tasks, worktrees, links, snapshots, and recovery, which are
Server/Core authority in AgentBox.

## Upgrade procedure

Never float a branch, npm range, or native binary. Clone the new tag into an
owned research root, regenerate `SOURCE.json` hashes, rebase these patches,
re-run the fake seams (`plugins/agent-box-harnesses/tests/harness_remote/`),
and require a new explicit authorization before any real provider test.
