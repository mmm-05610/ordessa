# Independent Claude Code provider

Distribution `ordessa-harness-claude-code`, import `ordessa_harness_claude_code`.
Runtime provider id remains **`claude`**, while command catalog id remains
**`claude-code`**. Package separation does not rename existing persisted ids.

Import and contribution registration launch nothing. This package imports
Pacthold's published Agent contracts and protocol-neutral Harness transport;
it does not import the large Harness implementation or Agent Tools product.

`ClaudeCodeRuntimeProvider` defaults to four planning/inspection methods only.
Without composed existing UnitRecords, fixed-operation preparation authority,
trusted owner projection, invocation
verifier and authorized connection, `prepare/start/connect/configuration` and
lifecycle methods explicitly refuse and are absent from supportedMethods.
Method presence never means production readiness. The package is **PARTIAL**.

The official Claude Agent SDK at source pin
`9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b` / version `0.2.163` is the preferred
channel. The optional dependency expresses that pin; no dependency was installed
for this change. Existing SDK installations are checked exactly, with no install
or update. SDK component MIT does not replace runtime/authentication terms.

`ClaudeSdkSession` adapts the SDK's public client in one async task/context. It
requires a deployment supplied `FencedSdkTransport` and explicit permission
callback. SDK default subprocess transport is disabled here because it merges
the inherited environment. A deployment must supply isolated transport, roots,
installation admission and a native dispatch authority covering all writes.
Provider-side transport must not escape through a raw consumer connection.

`stream_json.ClaudeCodeClient` is the previously reviewed limited native
stream-json alternative. It is retained with its safety tests and only imports
the shared transport. **It is not an automatic fallback** or a second startup
route. Product assembly must explicitly select one channel for a Unit. The SDK
owns its control protocol, reading, hooks and asynchronous lifecycle; the
limited consumer does not claim the SDK's full capabilities.

SDK set_model returns control acknowledgment. This adapter returns unknown;
the SDK's initialization-info cache is not fresh configuration readback.
Production configuration requires owner-confirmed sourceRevision, scope,
original operation/request digest and receipt evidence. An independently read
current value matching desired is insufficient to settle the original attempt.

Disconnect, interrupt, stop and release are distinct. SDK interrupt receipt does
not clear a pending turn. A native human ResultMessage ends a turn; background
ResultMessage does not. SDK disconnect is a transport event and makes no Unit
stop claim. Borrowed/unknown lifecycle resources are never destroyed by the
provider's stop/release helper.

See [reuse-comparison.md](reuse-comparison.md) and
[owner-ports.md](owner-ports.md) for exact evidence and remaining production gaps.

## Preserved ACP attachment utility

`ordessa_harness_claude_code.acp_attachments` now owns the previously reviewed
pure conversion of prepared attachment references into ACP prompt content blocks.
The original implementation bytes and six behavior tests are preserved; the
legacy catalogue declaration is tested separately. The old
`ordessa_harness.claude.attachments` module and its package exports are removed,
with no import shim. Continuation identifiers remain unchanged.

The evidence is historical ACP adapter `0.81.2`, not the preferred SDK channel.
Images require held bytes matching byteLength and SHA256; only image/png has the
historical end-to-end probe. Count/size limits are channel policy. Non-image files
become URI link text, not uploaded bytes; audio is explicitly refused. The helper
does not acquire material, authorize input, choose a channel, open a process or
send a prompt. It does not add any default provider supported method.

Current SDK/native owner attachment delivery is unimplemented. Calling this
utility or preserving an old catalogue `attach=true` does not establish a usable
product attachment entry. Historical reports retain their dated evidence and
old source locations; current ownership and migration evidence are in
`docs/implementation/agent-tools/evidence/agent-unit-model/claude-acp-attachments.md`.
