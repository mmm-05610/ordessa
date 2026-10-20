# Runtime process evidence — real pi rpc (P, zero model)

2026-10-06 · slice `plugins/harness/pi/**` (AU003 pi family real-process
adapter + termination-face consumption + configuration journal confirmation).
Authorisation scope: slice-only isolated harness processes, zero model
(user-ruled). No user login/config/credentials read; every child runs under a
temporary unit-private root (HOME/XDG_* under it, PI_CODING_AGENT_DIR pinned
inside it, credential-shaped environment keys dropped, `--offline` +
`PI_OFFLINE=1` re-asserted on the real child). Nothing installed or updated;
the pinned managed installation was only validated in place.

## Binary observed

- launcher: `/home/maoqh/.local/bin/pi` (symlink) →
  `/home/maoqh/.pi/agent/bin/pi` (POSIX sh launcher,
  SHA-256 `99142ef3d4cd5ce154cc568c6e915930632808dd7010666e514551c1430ffd3d`),
  which resolves `PI_MANAGED_INSTALL_ROOT=/home/maoqh/.pi/agent/install`,
  `current-version=0.86.1`, release bin
  `install/releases/0.86.1/node_modules/.bin/pi`
  (→ `@earendil-works/pi-coding-agent/dist/bundle/cli.js`, node 22.22.1).
- `pi --version` (isolated env): `0.86.1` — matches the package protocol pin
  N003 (pi 0.86.1 official rpc docs, frozen 2026-10-04).
- the launcher resolves its installation relative to the binary path, not
  HOME, so unit-private `PI_CODING_AGENT_DIR` + HOME fully isolate the child.

## What was launched / observed (zero model: get_state round trips, one
set_thinking_level write, real stop; never prompt/steer/follow_up)

- Launch `pi --mode rpc --no-session --offline --no-extensions --no-skills
  --no-context-files --no-prompt-templates --no-approve` under the unit
  private root; startup ≈ 0.6 s; strict JSONL records as pinned (no JSON-RPC
  2.0 envelope on this wire by design).
- `get_state` round trips — stable `sessionId`
  (UUID-shaped), offline default model `unknown/unknown`, thinkingLevel `off`,
  `userAgent`-free pure state; isolation confirmed from
  `/proc/<pid>/environ` (HOME/PI_CODING_AGENT_DIR/PI_OFFLINE pinned,
  OPENAI_API_KEY/ANTHROPIC_API_KEY/GITHUB_TOKEN/DEEPSEEK_API_KEY absent).
- `set_thinking_level` — the documented offline level space is exactly
  `{"off"}`; a non-`off` value is answered `success:true` (ACK) but the
  readback stays `off`. This is a REAL protocol restriction recorded, not
  patched: the provider keeps readback-decided confirmation, so such a write
  correctly lands `unknown` rather than `applied` (P-test asserts this).
- Managed writer fence: after `fence_all()`/`revoke` every write raises the
  typed transport refusal; the process stays ALIVE after lease disconnect
  (disconnect ≠ stop); explicit owner close → stdin-EOF → pi exited with
  code 0 (reaped, terminal sigterm path never needed); teardown `ps`/
  `/proc` rescan over the private root shows zero residual processes.
- Lost configuration receipt (0.001 s deadline): the write is handled
  immediately by pi, so EITHER the late receipt is recovered into the
  original dispatch ledger and the readback confirms, or the journal keeps
  `unknown` with the original requestId held — both branches asserted,
  never re-sent (`pi-rpc` client has no recovery/re-send path; recorded
  honestly as a no-recovery client seam difference vs codex).

## termination-face-freeze consumption (production, this slice)

- `UnitRecords(..., termination_evidence=PiTerminationEvidencePort(factory))`
  + new `termination.py`: the ONE owner both the provider and the journal
  consume (`termination_ready` requires `records.termination_evidence IS
  evidence`). `stop` closes the real owned subprocess (stdin close/terminate/
  kill, awaited by identity) and records confirmed ONLY from process-level
  facts the port re-verifies against the bound channel record: pinned argv[0],
  sealed unit roots equality, real pid, real return code, `/proc` absence,
  record-held for stop / record-removed for release. Refs stored by the
  journal are the port's versioned provenance refs (`pi-rpc/1`, `pi-process/…`,
  `exit/…`, `pi-termination/<sha256>`) — caller strings are never proof.
- unknown keeps the attempt, its hold and its ticket; no auto-release; cold
  `reconcile_termination` re-observes the REAL exited handle read-only along
  the original correlation (C-level, stub handle + real port logic).
- release never kills: a live owned unit is refused before any release claim
  (A14); release frees factory records + live handles + lease grants and
  requires the record already released (the owner verifies exit+released).

## Configuration journal confirmation (same NativeConfigurationAttempt seam)

- `begin_configuration_change` consumes the original applyConfiguration claim
  before any native write; `bind_configuration_dispatch` fixes the exact
  native request id + sha256 digest INSIDE the transport pre-send guard
  (prepared-frame one-shot; a guard failure fences and claims nothing);
  `record_configuration_change` confirms only via the owner evidence port,
  whose proof must re-match the stored dispatch identity/digest — the ACK is
  never the proof, the `get_state` readback is. expectedConfigurationRevision
  comparison retained; pi has no native CAS and none is fabricated. Missing/
  foreign evidence port keeps `apply_configuration` unadvertised + typed
  refused (no ready claim).

## Test accounting

- P (real process, zero model): `plugins/harness/pi/tests/test_runtime_process.py`
  — 20 tests (launch+identity, /proc isolation, owner-read-only projection,
  forged refs, root/argv counter-examples, lease grant/bind/revoke/rebind,
  disconnect-vs-stop, reaped shutdown + /proc rescan, descriptor honesty,
  config write confirmed from native readback through the real journal,
  ACK-without-effect stays unknown, multi-setter refuse, receipt-loss
  double-branch, real stop exit-evidence, release-after-stop, release
  refuses live unit, second-stop single-attempt, epoch-move mid-effect).
- C (controlled): test_termination_records.py 18 (real temp SQLite journal +
  port logic on stub handle), test_configuration_journal.py 9 (begin/bind/
  record/query seam), plus the pre-existing 271.
- Full package command (exit 0, 318 passed, 0 skipped):
  `PYTHONPATH=plugins/harness/pi/src:packages/backend/harness-transport/src:
  plugins/harness/records/src <.venv-ordessa-py312 python> -m pytest
  -c plugins/harness/pi/pyproject.toml plugins/harness/pi/tests -q --tb=short`
- M: 0 (real model is the later independent M slice; no model call was ever
  issued and the zero-model boundary is asserted per P test).

## Compatibility verdict / limitations (recorded, not faked)

- Exercised edges verified compatible against the observed 0.86.1 binary:
  managed launch, get_state, set_thinking_level (level space {"off"}),
  writer fence, stdin-EOF exit 0, absent command typed `success:false`.
- Not exercised, not claimed: prompt/steer/follow_up turn edges, session
  resume, `set_model` against a real provider (offline models.json had no
  model; a real model call is the independent M slice), `new_session`.
- The pi client's pending-ledger recovery is a manual read-only replay
  (`recover_request`) in codex; the pi client documents no equivalent —
  lost receipts keep `unknown` and the pending id; P tests assert no re-send.
- The `PiUnitProjection` publication facts expect the core publication
  owner composition (DirectoryBindingRef + evidence map); publication wiring
  is performed by the assembly slice, same registered limitation family as
  codex.
