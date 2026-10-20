# Claude Code SDK provider

Distribution `ordessa-harness-claude-code`, import `ordessa_harness_claude_code`.
The persisted provider id remains `claude`, command catalog id `claude-code`, and
native protocol id `claude-stream-json/1`.

`factory.build({"definition_ref": pinned_ref, "implementation_digest": digest})`
returns `ClaudeHarnessProvider`. Its pure `validate_profile` and `prepare` consume
fixed Profile content and explicit `PrepareContext`, returning an immutable
`LaunchPlan`. The only package dependency is `ordessa-execution-agents`' public SDK.
Entry point: `ordessa.harness_providers:claude`.

The native command is bidirectional stream-json with explicit permission callbacks;
it is not ACP. Original native bootstrap is **unavailable**: `open_session` raises
`NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE`, never calls ACP or an old client. The Agent
Manager rejects this protocol before launching. No native runtime/model was called
or tested in this migration.

Profiles accept `claude.configuration/1` value declarations. Model, explicit default
permission mode and system-prompt options use the preserved native compiler.
Continuation, non-default permission modes, allowed-tools overrides, raw MCP file
paths, unbound credentials and configuration kinds are explicitly unsupported.
Prepared configuration/material references remain exact in the plan. Composition
must supply approved command prefix, roots and environment, including
`CLAUDE_CONFIG_DIR`; no process environment is inherited or credentials discovered.

The former Unit runtime/provider, direct official SDK session, synchronous native
stream-json client, server plugin, owner projection, lifecycle coordinator,
registration/declaration and old configuration execution paths are physically
removed. There are no old-name exports, forwarding modules or runtime fallbacks.
Existing tests and assertions are retained; tests importing removed APIs require
consumer/assertion migration and must not be presented as green.

Pure `native_channel` planning/compilation, `acp_attachments` data checks, native
model/dialect facts, historical continuation identifier, captured artifact JSON/
JavaScript, packaging tooling/locks and deployment resource bytes remain. They do
not register an ACP provider or admit execution. `production` retains settings and
artifact facts only; legacy deployment assembly/emission is removed.

See [owner-ports.md](owner-ports.md) for exact retirement and remaining consumers.
