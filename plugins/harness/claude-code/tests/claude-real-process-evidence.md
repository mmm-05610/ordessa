# Real-process evidence — real claude stream-json (P, zero model)

2026-10-06 · slice `plugins/harness/claude-code/**` (Claude family real-process
P-level adapter: runtime channel + termination-face consumption on the real
process). Authorisation scope: slice-only isolated harness processes, zero
model (user-ruled). No user login/config/credentials read: every child runs
under a temporary unit-private root (`HOME`/`XDG_*`/`TMPDIR` under it,
`CLAUDE_CONFIG_DIR` pinned inside it, every credential-shaped environment key
dropped by the frozen transport, documented no-traffic/no-update env
assertions re-asserted). Nothing installed or updated; the pinned managed
installation was only validated in place.

## Binary observed

- launcher: `/home/maoqh/.local/bin/claude` (symlink) →
  `/home/maoqh/.local/share/claude/versions/2.1.291` — native ELF x86-64
  executable (Bun single-binary, not a node/shell wrapper),
  SHA-256 `078fad28d0297c9a25d306b635b2d8816c6839347520f29eb54ffea5d56142fb`
  (same digest via launcher path and resolved path).
- `claude --version` (isolated child, captured): exit 0, stdout
  `2.1.291 (Claude Code)`, empty stderr; the probe child wrote nothing
  anywhere under its scratch root.
- the child's own boot record (`<config>/.claude.json`, written inside the
  unit-private config dir) carries `firstStartVersion: "2.1.291"` — a second,
  child-written version fact.
- the factory pins all of this at construction: absolute path + regular
  runnable file check, optional `expected_sha256` re-hashed and enforced
  (mismatch → typed refusal), resolved realpath recorded.

## What was launched / observed (zero model: one control handshake, real
stop/release; never a user message or any model turn)

- Launch `claude -p --output-format stream-json --input-format stream-json
  --verbose --permission-prompt-tool stdio` under the unit private root — the
  exact explicit bidirectional plan `native_channel.plan_launch` publishes and
  the exact subprocess shape the pinned Claude Agent SDK source
  (`subprocess_cli.py`) spawns for its own transport. `/proc/<pid>/cmdline`
  verified equal to the pinned argv.
- Native control handshake WITHOUT login: `{"type": "control_request",
  "request_id": ..., "request": {"subtype": "initialize", "hooks": null}}` →
  matching `control_response` (subtype success). Receipt facts (observed,
  pinned only loosely to resist version drift): `account.tokenSource: "none"`
  and `apiProvider: "firstParty"` (the process's OWN no-login fact),
  receipt `pid` equal to the spawned child pid, `session_state: "idle"`,
  slash-command and model-catalog arrays present. This is the only native
  request/receipt edge exercised; the consumer's no-resend guard was proven
  (a second `initialize_control` is refused; exactly one control frame ever
  reached the wire).
- Isolation, verified from `/proc/<pid>/environ` of the REAL child: `HOME`,
  all `XDG_*`, `TMPDIR` and `CLAUDE_CONFIG_DIR` pinned inside the unit-private
  root; `DISABLE_TELEMETRY=1`, `DISABLE_AUTOUPDATER=1`,
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`; every transport token key
  (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`,
  `GITHUB_TOKEN`, … — the full `_TOKEN_ENV_KEYS` set) absent; no environment
  value anywhere equals the user's real HOME. Every file the child ever
  created stays inside the unit private root (`<config>/.claude.json`,
  `backups/`, `sessions/<pid>.json` registry entry, peer socket under
  `<home>/tmp/cc-socks`).
- Managed stdin fence: raw un-leased writes are refused by the managed
  channel; a second writer cannot be acquired while the factory lease is
  active; after `fence_all()` every subsequent write through the old bound
  view (including framed control writes) raises the typed transport refusal
  while the process stays ALIVE — a fence is never a stop.
- Real stop: owner `close` → stdin close → the child exits by itself with
  code 0 (terminate/kill never needed in these runs), awaited by identity;
  exit code evidence is the subprocess's own `returncode`; /proc rescan over
  the private root shows zero residual processes; teardown re-scan clean in
  every test.
- Release semantics: `release` of a LIVE owned process is refused ("stop the
  unit first") and never kills; `release` after the real exit frees the
  record and returns the observed `{pid, exitCode}`; a second release is
  refused.
- Honest nuance recorded: without any user message the child still maintains
  its own IDLE process-registry entry `config/sessions/<pid>.json`
  (internally generated UUID `sessionId`, `kind: "interactive"`,
  `entrypoint: "sdk-cli"`, `status: "idle"`, peer socket path inside the
  private root) plus an ephemeral peer `.key` file — process bookkeeping for
  the never-messaged session, no message content, no transcript, and the
  child removes them itself at close. The zero-model boundary is therefore
  asserted on the wire records and absence of transcripts (no `*.jsonl`
  under the config dir), not on the presence of the registry entry.

## termination-face consumption on the REAL process (this slice)

- The existing production `ClaudeTerminationEffects` +
  `ClaudeTerminationCoordinator` consume the real handle through the frozen
  `ClaudeOwnedChannels` registry (`RealProcessHandle` exposes the
  registry-facing `is_alive`/`close(timeout=...)` surface bound by identity
  to the factory's actual `ProcessChannel`).
- `stop` over the real journal/records/issuer (temporary SQLite, C-level
  fixture): confirmed, the REAL process reaped, and the
  `ClaudeTerminationEvidence` birth record re-verifies ONLY against the
  real observed exit code (`{"outcome": "confirmed",
  "exitCode": <real code>, "reaped": "1"}`); a forged exit code is refused
  ("differs from the observed effect"). The stored refs stay the port's own
  provenance refs (`claude-termination/<sha256>`).
- `release` refuses the live real process before any claim (nothing
  consumed, no ledger row), and confirms after the real stop, freeing only
  the owned registry entry.
- unknown path on the real process: a broken close leaves the attempt
  `unknown`, the real process ALIVE and untouched, the hold in place; a late
  owner probe cannot conclude while it runs; the owner's explicit factory
  reap then lets cold `reconcile` conclude from the late observation —
  nothing re-arms, re-kills or auto-releases.

## Configuration facts (P decision)

- No native configuration-write readback edge exists without a turn: the
  C-level typed refusal (SDK `mutate_configuration` → ackOnly/unknown;
  configuration face keeps typed refusal) stands unchanged. NOT exercised on
  the real process: no `set_model`/`set_permission_mode` frame was ever sent
  (no readback to confirm with; sending an ack-only write would add protocol
  traffic outside the pinned consumer surface without any confirmation
  gain). The `initialize` receipt's `models`/`commands`/permission-mode
  fields are launch-time catalog facts, not write readbacks.

## ABSENT / not exercised (no login state; never mocked, never borrowed)

- Session initialize (`system/init`) and ANY model turn: the isolated child
  has no credentials (isolated `CLAUDE_CONFIG_DIR`, no token keys in the
  child environment, `tokenSource: "none"` observed natively), so no model
  call is even possible. `system/init`, `can_use_tool` permission callbacks,
  `result` completion, `stream_event`, `system/api_retry`, resume/continue,
  SDK hooks/SDK MCP: UNVERIFIED (ABSENT) — they all require a first user
  message, which is exactly the login-blocked edge. Recorded, not worked
  around.
- Official SDK path (`ClaudeSdkSession`/`FencedSdkTransport`): the
  `claude-agent-sdk` package is NOT installed in this environment (the
  C-level `installed_sdk_factory` refuses typed) — it was not installed. The
  exercised direct stdio channel is the same subprocess the SDK itself
  spawns; the SDK adapter's launch/isolation/reclaim evidence transfers via
  this seam, but the SDK client object itself remains UNVERIFIED (ABSENT).
- Lost control receipt (deadline-induced) on the real channel: not exercised
  (the C-level transport semantics — LostReceipt/unknown, never re-send —
  cover the contract; a real-process variant would only add timing
  flakiness, and the no-resend refusal was proven deterministically).

## Test accounting

- `plugins/harness/claude-code/tests/test_real_process.py` — 13 P tests, all
  real binary, zero model, no skip, no mock of native behavior (the only
  test double is the broken-close subclass used for the unknown-outcome
  path, which never substitutes for a real effect: the process is a REAL
  claude child and the broken close is the controlled effect-refusal
  fixture, same style as the C-level `ControlledChannel.break_close`).
- Full slice suite after this slice:
  `PYTHONPATH=plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src <venv>/bin/python -m pytest -c plugins/harness/claude-code/pyproject.toml plugins/harness/claude-code/tests -q --tb=short`
  → 255 passed / 0 failed (242 C-level baseline + 13 new P), no baseline
  regression.
- Evidence levels: C = 242 pre-existing tests (assembly/projection/
  termination/configuration/owner view, controlled processes only); P = the
  13 tests in this file (real binary, real process, real exit evidence);
  M = none added (no multi-unit/durable-restart scenario exercised here).
