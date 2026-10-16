# Independent DeepSeek dsh AgentUnit provider

Distribution `ordessa-harness-dsh`, import `ordessa_harness_dsh`,
provider/family ID `dsh` (identical to the `harnesses.toml`
driver/harness_type, profile id and launch id — no rename anywhere). Import
has no registration or process effects and no dependency on sibling
providers, old Harness internals, Server, or Agent Tools. Authority:
`docs/implementation/agent-tools/dsh-package-freeze-v1.md` (frozen 2026-10-07).

## Channel

Chosen native channel: **ACP stdio subprocess**, `dsh --profile acp` — the
same subprocess channel shape as codex/pi. The frozen argv plan is
`dsh_acp_argv(executable) -> (executable, "--profile", "acp")`. The wire is
ACP JSON-RPC 2.0 over stdio (one JSON object per LF line); every frame THIS
client emits carries `jsonrpc: "2.0"`. The provider label for this channel is
`dsh-acp/1` (`PROTOCOL` in `client.py`) — this package's own wire label, not a
claim of upstream version negotiation.

`DshRuntimeProvider` consumes host-supplied definition ref/digest and explicit
original UnitRecords plus trusted projection, InvocationVerifier, native
channel factory, and authority lease ports. It publishes an
`agent-runtime/2` descriptor for the sole CoreRegistry; it has no provider
registry, daemon, database, or actual configuration cache. The host remains
activation/owner authority.

## Version pin

Pinned **npm `@deepseek-ai/dsh` `0.1.5-rc.1`** — the locked repository value:
`tooling/npm/package-lock.json` resolves
`https://registry.npmmirror.com/@deepseek-ai/dsh/-/dsh-0.1.5-rc.1.tgz` with
integrity
`sha512-rmNmzQCg3oIc1z8xH7izRSOuy1TNzq+/NILyfM+7e8DKOyV+yBtg47WEsqR2SiIe1ATec3L/rUa1YhIcfQ2XEg==`.
The npm **latest `0.2.0-rc.2` is deliberately NOT chased**: its ACP face has
zero in-repo evidence. The `harnesses.toml` `version` field stays untouched
this round (static registration, comment already declares its nature). The
PyPI SDK `deepseek-harness-sdk==0.1.5rc1` is an INDEPENDENT version track and
is NOT a dependency of this package (no `sdk` extra); see `REUSE.md`.

## Descriptor and digest rules (zero forgery)

`RuntimeProviderDescriptor("dsh", RUNTIME_PROVIDER_VERSION, definition_ref,
implementation_digest, tuple(methods))`. `implementation_digest` is a
**required keyword-only parameter with no default**: this package never
generates or guesses it; an empty/non-string digest is refused outright.
Production digests are injected by the deployment fingerprint gate. **Until
that gate is backfilled, the dsh provider must not appear in any production
assembly** (freeze §3/§5). Test digests (`sha256:` + `a`*64) are explicit
non-real fixtures.

`supported_methods` starts with the four discovery methods and grows only with
explicit ports (same gating as codex). The four configuration methods
(`describe_configuration`, `inspect_configuration`, `apply_configuration`,
`query_change`) are **absent in this version** — no configuration evidence
port is pinned for dsh in this tree; calling any of them raises a typed
refusal.

## Recovery: permanently absent

dsh rejects `session/load`. Therefore:

- the client has **no load method, no load constant and no load fallback**;
- `describe_definition` reports `"recovery": "unsupported"`;
- `provider.recover(...)` is permanently typed-refused, with the reason
  naming the bridge continuation contract `agent-box.dsh-continuation@1`;
- `session/resume` exists as a CLIENT frame only; it never enters provider
  supported methods, and resume is never a recovery fallback (dsh resume does
  not replay history — that fact belongs to the bridge continuation gate).

## Fences

- **No retry, ever** (G11): a lost receipt keeps its original id; the outcome
  stays unknown; a late receipt is recovered read-only (`recover_request`);
  nothing is ever resent automatically.
- **Receipt ≠ completion**: `session/prompt` responses are accepted as turn
  outcomes only when structurally terminal (`end_turn` / `error` /
  `cancelled` — the vocabulary pinned by this repository's ACP bridge
  evidence). `error`/`cancelled` raise typed `PromptTurnFailed` with the raw
  response kept; malformed/non-terminal/unknown responses stay `LostReceipt`
  (unknown), never a success.
- **Unknown preserved** (G4): unknown methods and events surface verbatim in
  `events()`.
- **Unknown keeps its hold**: provider unknown outcomes retain the original
  ticket/hold; a concurrently confirmed original binding is never downgraded.
- **Zero real process in tests**: package tests launch a controlled fake dsh
  peer (a generated Python script standing in for `dsh --profile acp`) through
  the REAL factory (real isolation, managed writer fence, real reap path).
  The real dsh binary is never executed by this package (rules 6/9);
  real-process verification is registered NOT_RUN in
  `tests/runtime-process-evidence.md`.

## Status: PARTIAL

This is a partial provider implementation. Verified here (C level, controlled
fixtures/fake peer): descriptor shape and zero-forge digest rule, ACP framing
and correlation, no-retry/unknown/receipt fences, session/load absence in all
three mechanisms, isolated launch plan, lease cut, termination evidence logic.
NOT verified / NOT_RUN: real dsh `0.1.5-rc.1` process behaviour (initialize /
`session/new` / `session/load` rejection / resume-no-replay against the real
binary), production assembly inclusion (blocked on the fingerprint gate),
`harnesses.toml` registration round, deployment templates, SDK extra. Real
production evidence/continuation ports remain the deployment's responsibility;
no native atomic configuration guarantee is asserted anywhere.

## Optional Server host binding

`ordessa_harness_dsh.server_plugin.DshServerPlugin(provider_factory)` is an
explicit optional binding to the existing `pacthold.contributions` point. The
factory receives the host's unique `EnvironmentId` and returns this package's
provider with matching definition namespace and explicit implementation
digest/ports. The host supplies owner activation; the wrapper does not
install, activate, issue authority, create a store or launch a native
process. Owner ID remains `dsh`. Server API imports are lazy and the
dependency is in the `server` extra; base provider imports and wheel
conversion need no Server API.

## Upgrade revalidation

CLI bumps and any future SDK adoption follow the frozen six-item set in
`REUSE.md` (lock hash, fake-endpoint full-chain gate rerun including
load-still-rejected/resume-still-no-replay, toml update per gate evidence,
capability_declarations sync, settings re-verification, evidence registration).
`observed` may only be backfilled from gate evidence — never inferred.
