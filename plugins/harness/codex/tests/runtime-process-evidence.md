# Runtime process evidence — real codex app-server (P, zero model)

2026-10-05 · slice `plugins/harness/codex/**` (AU003 codex family real-process
adapter + P sequence). Authorisation scope: slice-only isolated harness
processes, zero model. No user login/config/credentials read; every child
runs under a temporary unit-private root (HOME/XDG_* under it, CODEX_HOME
pinned inside it, credential-shaped environment keys dropped).

## Binary observed

- executable: `/usr/lib/chatgpt/resources/codex` (absolute, static ELF)
- SHA-256: `d2752c52353401f7f6efbfcea68796f4f7a3d3e4769f5d1da53fa49d4856b72f`
- `--version` (isolated env): `codex-cli 0.159.0` (matches
  `codex-local-version-probe.json`; package protocol source stays pinned at
  **0.157.1**)
- `app-server` subcommand exists (`--help`); default transport `stdio://`.

## What was launched / observed (zero model: initialize + thread/start + thread/read only, never turn/start)

- `initialize` (clientInfo/capabilities, no `jsonrpc` header on the wire) —
  accepted; result named `platformFamily/platformOs/codexHome/userAgent`,
  and `codexHome` equals the unit-private CODEX_HOME (isolation confirmed
  from the child process argument env `/proc/<pid>/environ` as well).
- `thread/start {cwd}` — receipt `thread.id` present (UUID-shaped),
  receipt also carries `turns: []`.
- `thread/read {threadId, includeTurns:false}` — readback `thread.id`
  matches the receipt exactly; `turns` empty; no `turn/*` events ever.
- Round-latency measured on this machine: initialize ≈ 129 ms
  (first), thread/start ≈ 8 ms, thread/read ≈ 0.5–1 ms.
- Managed writer fence (transport writer lease): after `fence_all()` every
  write raises the typed transport refusal; the process stays ALIVE after
  revoke (disconnect is not stop); `close()` exits with code 0, reaped.
- Unknown/foreign methods answer typed JSON-RPC errors verbatim (kept as
  `CodexRpcError`), no auto-retry anywhere; a timed-out request keeps its
  original pending id and a late receipt is recovered read-only
  (`recover_request`) — exactly once on the wire.

## Compatibility verdict

- The exercised protocol edges (wire shape, `initialize`,
  `thread/start`, `thread/read`, error objects, fence semantics) are
  **verified compatible against the observed 0.159.0 binary**. The package
  source remains pinned to the 0.157.1 protocol documents; compatibility on
  other edges (turns, config writes, stop) is NOT claimed here.
- Recorded difference (not faked, not patched): `thread/list` with a
  params-less frame (client's pinned shape) is rejected by 0.159.0 with
  typed `-32600 "Invalid request: missing field `params`"`. The pinned
  client declares `thread/list` in `knownMethods` but the provider sequence
  in this slice never needs it.

## Test accounting

- P (real process, zero model): `plugins/harness/codex/tests/
  test_runtime_process.py` — 17 tests.
- Full package command (exit 0, 227 passed, 0 skipped):
  `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src:
  plugins/harness/records/src <.venv-ordessa-py312 python> -m pytest
  -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q
  --tb=short`

## Addendum 2026-10-06 — unified termination face on the real process (P)

Slice `plugins/harness/codex/**` (Codex family termination consumption).
Same authorisation scope and zero-model boundary as above; the exercised
native edges stay initialize / thread/start / thread/read plus the factory
reap — never turn/start, never a model call.

- `stop` runs the REAL effect through the factory's reap (stdin close →
  terminate → kill, awaited by identity): observed exit code 0 on 0.159.0,
  `/proc/<pid>` gone after the reap, and the confirmed
  `harness_unit_terminations` row stores only the
  `CodexTerminationEvidencePort`-verified provenance refs
  (`codex-process/<pid>`, `exit/<code>`, `codex-termination/<sha256>`).
- `release` after stop frees the owned channel record and revokes the lease
  port grants; `release` on a live owned unit is refused BEFORE any claim
  and never kills (A14); unknown outcomes keep the attempt, its hold and
  its ticket; cold reconciliation via `reconcile_termination` along the
  ORIGINAL correlation concludes a retained attempt read-only.
- Factory seam: `close` (single) now KEEPS the channel record so the
  termination evidence can be verified against the actual exited handle;
  `release` performs the record release (refusing a live process);
  `close_all` (teardown) closes and releases every record — the existing
  teardown-only assertions are unchanged.

- Registered observed difference (not faked, not patched): on startup the
  0.159.0 app-server spawns its OWN short-lived `git` children (plugins
  `ls-remote`/`fetch` against `github.com/openai/plugins.git`) under the
  isolated unit CODEX_HOME, inheriting the isolated environment; they
  outlive a stop by at most a few seconds (observed ~2 s) and exit on their
  own. The private-root liveness scan in the P tests therefore awaits a
  clean scan within a bounded deadline (60 s) and FAILS on any residue past
  it; the pinned-binary identity (the reaped app-server pid) is asserted
  gone immediately.

### Test accounting (this addendum)

- P (real process, zero model): `test_runtime_process.py` — 22 tests
  (17 existing + 5 termination-face).
- C (controlled stub handle, real journal/records/port logic):
  `test_termination_records.py` — 19 tests.
- Full package command (exit 0, 251 passed, 0 skipped):
  `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src:
  plugins/harness/records/src <.venv-ordessa-py312 python> -m pytest
  -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q
  --tb=short`

