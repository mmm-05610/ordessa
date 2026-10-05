# Independent Codex AgentUnit provider

Distribution `ordessa-harness-codex`, import `ordessa_harness_codex`, family/provider ID `codex` (preserved). Import has no registration/process effects and no dependency on sibling providers, old Harness internals, Server, or Agent Tools.

Chosen native channel: Codex app-server JSONL stdin/stdout, compatibility source pin `@openai/codex` 0.157.1. This is a source contract pin, not verification of a local executable. No installation, update, login, model invocation, or native Codex startup has been performed by AU003.

`CodexRuntimeProvider` consumes host-supplied definition ref/digest and explicit original UnitRecords plus trusted projection, InvocationVerifier, native channel factory, and authority lease ports. It publishes an `agent-runtime/2` descriptor for the sole CoreRegistry; it has no provider registry, daemon, database, or actual configuration cache. The host remains activation/owner authority.

The preparation path reserves the Unit in the existing journal. Start fixes its opening correlation before initialize and thread/start, then confirms exact thread/read identity via the native evidence owner before recording confirmed. A receipt loss retains unknown; a fresh process cannot reopen that Unit through start. query_step only asks the original journal/native evidence owner about the same correlation. It cannot restart.

Configuration inspection queries the live native owner and distinguishes instance defaults from current thread facts. Configuration support is conditional on the original journal/evidence/continuation ports documented below; missing ports omit apply_configuration/query_change and refuse. Stop/release/recover remain typed unsupported pending native ownership and journal cleanup integration; neither disconnect nor channel loss claims stop.

Access ports must bind a trusted full-side-effect lease and recheck every raw native write, including replies and unknown future methods. They must not hand callers the raw client/channel. Missing ports omit corresponding methods and refuse. The public client is an internal family adapter and grants no authorization by itself.

Current status: partial provider implementation; C test candidates exist, actual P/M and production host composition remain unverified. `tests/test_client.py` preserves all original client assertions, but moving tests is not new evidence.

## Incremental configuration batch implementation

The fixed upstream source is now resolved to commit `36650394c5b38c2990ccf2a3457165ca3e9d9726` (`rust-v0.157.1` tag). `config/read(includeLayers=true)` exposes native user-layer version; `config/batchWrite` accepts `expectedVersion`. The implementation uses native precondition plus one provider lock and labels **ownerSerialized**, never nativeAtomic or external-process atomicity.

The native kind `codex.defaults`, schema `0.157.1`, controls only model and model_reasoning_effort in the explicitly verified isolated CODEX_HOME/config.toml. Value payload is strictly limited to those native keys; reset has no payload and removes both defaults through native null edits. Disabled, unknown required schemas and resources are rejected. Optional unsupported declarations are explicitly rejected. Profile catalog is never modified.

Snapshots contain separate `defaults` (native user layer), `effectiveDefaults` (native merged defaults), and `thread` (exact original thread/read model/effort). Unknown thread fields remain unknown. Defaults writes deliberately set reloadUserConfig=false; applied means confirmed defaults persistence and does **not** claim the existing thread's model changed. Session model mutations, automatic restart and complete model-provider materials remain unavailable.

Configuration support additionally requires the deployment-injected evidence owner to be the **same object** as original UnitRecords.configuration_evidence and explicit projection.revalidate_configuration. Every native RPC boundary rechecks the original consumed claim/current scope/epoch/activation/directory grant. command_once allocates the actual RPC id before invoking the journal bind hook and writing; hook failure performs no write. A lost receipt retains original id and UnitRecords unknown fence. Only a live retained original ticket can settle a later original receipt; cold reads do not reconstruct tickets or infer original completion from equal actual values.

The evidence port captures only sanitized original defaults request/receipt, bounded native layer revision, filtered readback and per-declaration outcome summary. It must persist and independently verify original native identity/readback provenance in its existing owner evidence store. It reconstructs ConfigurationChangeResult from the original attempt, never from current matching values or a second actual-state cache. Production port implementation is not completed by the controlled tests.

The local desktop Codex binary was later probed by the main session in isolation as version **0.159.0**, digest `d2752c52353401f7f6efbfcea68796f4f7a3d3e4769f5d1da53fa49d4856b72f`. This differs from the pinned 0.157.1 contract; it is not automatically compatible or selected. The old truncated npm artifact evidence remains a separate historical installation fact.
