# Independent xAI Grok Build AgentUnit provider

Distribution `ordessa-harness-grok-build`, import `ordessa_harness_grok_build`,
provider/family ID `grok-build` (identical to the `harnesses.toml`
driver/harness_type, profile id and launch id — no rename anywhere; the
product identity is the repo/doc name **Grok Build**, while the mechanical
binary name `grok` stays only in argv/installation positions). Import has no
registration or process effects and no dependency on sibling providers, old
Harness internals, Server, or Agent Tools. Authority:
`docs/implementation/agent-tools/grok-build-registration-draft.md` (draft
2026-10-07, three-source verified) plus the dsh package freeze precedent
(`docs/implementation/agent-tools/dsh-package-freeze-v1.md`, semantics
mirrored verbatim where applicable).

## Channel

Chosen native channel: **ACP stdio subprocess**, `grok agent stdio` — the
same subprocess channel shape as codex/pi/dsh. The frozen argv plan is
`grok_acp_argv(executable) -> (executable, "agent", "stdio")`. The wire is
ACP JSON-RPC 2.0 over stdio (one JSON object per LF line); every frame THIS
client emits carries `jsonrpc: "2.0"`. The provider label for this channel is
`grok-build-acp/1` (`PROTOCOL` in `client.py`) — this package's own wire
label, not a claim of upstream version negotiation.

The documented first-hand method surface (docs.x.ai/build/cli/headless-scripting,
2026-10-07) is `initialize` / `authenticate` / `session/new` /
`session/prompt` / `session/update`; this package additionally pins
`session/cancel`. `kill_task` / `get_task_output` and the ACP reopen methods
(`session/load` | `session/resume`) are **absent by honest registration** —
no documentary evidence, no declaration, no inference.

`GrokBuildRuntimeProvider` consumes host-supplied definition ref/digest and
explicit original UnitRecords plus trusted projection, InvocationVerifier,
native channel factory, and authority lease ports. It publishes an
`agent-runtime/2` descriptor for the sole CoreRegistry; it has no provider
registry, daemon, database, or actual configuration cache. The host remains
activation/owner authority.

## Version pin

Pinned **Grok Build CLI `1.0.46`** — the changelog static pin
(x.ai/changelog/build entry v1.0.46 dated 2026-09-30, verified 2026-10-07;
newer entries beyond it do not exist as of that verification). There is NO
npm/PyPI package for this CLI (install-script/source route only), so there is
no lock file to pin here; the packaging-script route is uncompiled
(registration draft §7.7, NOT_RUN). `harnesses.toml` registration belongs to
the separate registration round and is untouched by this package. The pin is
a **CLI/channel pin**, never a model-configuration fact.

## Descriptor and digest rules (zero forgery)

`RuntimeProviderDescriptor("grok-build", RUNTIME_PROVIDER_VERSION, definition_ref,
implementation_digest, tuple(methods))`. `implementation_digest` is a
**required keyword-only parameter with no default**: this package never
generates or guesses it; an empty/non-string digest is refused outright.
Production digests are injected by the deployment fingerprint gate. **Until
that gate is backfilled, the grok-build provider must not appear in any
production assembly** (draft §6/§7, dsh freeze descriptor rule precedent).
Test digests (`sha256:` + `a`*64) are explicit non-real fixtures.

`supported_methods` starts with the four discovery methods and grows only with
explicit ports (same gating as codex/dsh). The four configuration methods
(`describe_configuration`, `inspect_configuration`, `apply_configuration`,
`query_change`) are **absent in this version** — no configuration evidence
port is pinned for grok-build in this tree; calling any of them raises a
typed refusal (`GROKBUILD_PROVIDER_REFUSED` family code
`GROKBUILD_PROVIDER_REFUSED`, capability refusals
`GrokBuildCapabilityUnsupported`).

## authenticate extension: gated, typed-refused

`authenticate` on this face is an **xAI non-standard extension**,
client-initiated: `{methodId, _meta: {headless: true}}` with `methodId` ∈
`xai.api_key` | `cached_token` — different from the standard ACP
server→client authenticate direction. This adapter has NOT implemented it:
`GrokBuildAcpClient.authenticate` is typed-refused
(`GROKBUILD_AUTHENTICATION_REFUSED`) **before any write**, and the standard
ACP authentication chain must never be inferred in its place. Credential
flows (`grok` login / `XAI_API_KEY`) are unverified (NOT_RUN); probes must
stay zero/fake credential.

## Recovery: permanently absent

ACP reopen (`session/load` | `session/resume`) has NO documentary evidence on
the grok-build ACP face — the headless CLI `-r`/`-c` flags are NOT ACP paths
and are never inferred as continuation. Therefore:

- the client has **no resume method, no load method, no reopen constant and
  no reopen fallback**;
- `describe_definition` reports `"recovery": "unsupported"`;
- `provider.recover(...)` is permanently typed-refused, with the reason
  naming the bridge continuation contract `agent-box.grok-continuation@1`
  (target provider `grok-build-continuation`);
- `kill_task` / `get_task_output` are likewise absent registrations
  (undocumented on the first-hand face; changelog mentions `kill_task` over
  ACP only as a historical note) — never declared, never inferred.

## Fences

- **No retry, ever** (G11): a lost receipt keeps its original id; the outcome
  stays unknown; a late receipt is recovered read-only (`recover_request`);
  nothing is ever resent automatically.
- **Receipt ≠ completion**: `session/prompt` responses are accepted as turn
  outcomes only when structurally terminal (`end_turn` / `error` /
  `cancelled` — this repository's pinned ACP fence; a structural fence, NOT a
  claim about grok's native stopReason vocabulary, unverified until the
  gate). `error`/`cancelled` raise typed `PromptTurnFailed` with the raw
  response kept; malformed/non-terminal/unknown responses stay `LostReceipt`
  (unknown), never a success.
- **Unknown preserved** (G4): unknown methods and events surface verbatim in
  `events()`.
- **Unknown keeps its hold**: provider unknown outcomes retain the original
  ticket/hold; a concurrently confirmed original binding is never downgraded.
- **Zero real process in tests**: package tests launch a controlled fake grok
  peer (a generated Python script standing in for `grok agent stdio`) through
  the REAL factory (real isolation, managed writer fence, real reap path).
  The real grok binary is never executed by this package (rules 6/9);
  real-process verification is registered NOT_RUN in
  `tests/runtime-process-evidence.md`.

## Status: PARTIAL

This is a partial provider implementation. Verified here (C level, controlled
fixtures/fake peer): descriptor shape and zero-forge digest rule, ACP framing
and correlation, no-retry/unknown/receipt fences, absent-method registrations
(kill_task/get_task_output/session reopen), authenticate extension gating,
isolated launch plan, lease cut, termination evidence logic. NOT verified /
NOT_RUN: real Grok Build `1.0.46` process behaviour (initialize /
`session/new` / prompt terminal vocabulary / authenticate extension /
reopen absence against the real binary), production assembly inclusion
(blocked on the fingerprint gate), `harnesses.toml` registration round,
deployment templates, packaging script route. Real production
evidence/continuation ports remain the deployment's responsibility; no native
atomic configuration guarantee is asserted anywhere.

## Optional Server host binding

`ordessa_harness_grok_build.server_plugin.GrokBuildServerPlugin(provider_factory)`
is an explicit optional binding to the existing `pacthold.contributions`
point. The factory receives the host's unique `EnvironmentId` and returns
this package's provider with matching definition namespace and explicit
implementation digest/ports. The host supplies owner activation; the wrapper
does not install, activate, issue authority, create a store or launch a
native process. Owner ID remains `grok-build`. Server API imports are lazy
and the dependency is in the `server` extra; base provider imports and wheel
conversion need no Server API.

## Upgrade revalidation

CLI bumps follow the frozen six-item set in `REUSE.md` (pin re-verification,
fake-endpoint full-chain gate rerun including authenticate-still-gated /
reopen-still-absent / kill-task-still-absent, toml update per gate evidence,
capability_declarations sync, settings re-verification, evidence
registration). `observed` may only be backfilled from gate evidence — never
inferred.
