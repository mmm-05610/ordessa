# Independent Codex AgentUnit provider

Distribution `ordessa-harness-codex`, import `ordessa_harness_codex`, family/provider ID `codex` (preserved). Import has no registration/process effects and no dependency on sibling providers, old Harness internals, Server, or Agent Tools.

Chosen native channel: Codex app-server JSONL stdin/stdout, compatibility source pin `@openai/codex` 0.157.1. This is a source contract pin, not verification of a local executable. No installation, update, login, model invocation, or native Codex startup has been performed by AU003.

`CodexRuntimeProvider` consumes host-supplied definition ref/digest and explicit original UnitRecords plus trusted projection, InvocationVerifier, native channel factory, and authority lease ports. It publishes an `agent-runtime/2` descriptor for the sole CoreRegistry; it has no provider registry, daemon, database, or actual configuration cache. The host remains activation/owner authority.

The preparation path reserves the Unit in the existing journal. Start fixes its opening correlation before initialize and thread/start, then confirms exact thread/read identity via the native evidence owner before recording confirmed. A receipt loss retains unknown; a fresh process cannot reopen that Unit through start. query_step only asks the original journal/native evidence owner about the same correlation. It cannot restart.

Configuration inspection always calls native config/read on the live confirmed owner, filters nonsecret model/effort/approval/sandbox facts, and labels comparison unavailable. The hash identifies this limited readback; it is not a native revision or atomic CAS. Unknown provider credentials/session override fields remain explicit. Generic config/write has no verified native version comparison or durable original-attempt receipt, so apply_configuration/query_change are typed unsupported and absent from supportedMethods. Stop/release/recover are also typed unsupported pending native ownership and journal cleanup integration; neither disconnect nor channel loss claims stop.

Access ports must bind a trusted full-side-effect lease and recheck every raw native write, including replies and unknown future methods. They must not hand callers the raw client/channel. Missing ports omit corresponding methods and refuse. The public client is an internal family adapter and grants no authorization by itself.

Current status: partial provider implementation; C test candidates exist, actual P/M and production host composition remain unverified. `tests/test_client.py` preserves all original client assertions, but moving tests is not new evidence.
