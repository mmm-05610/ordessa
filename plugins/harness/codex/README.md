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

Configuration support additionally requires the deployment-injected evidence owner to be the **same object** as original UnitRecords.configuration_evidence and explicit projection.revalidate_configuration. Every native RPC boundary rechecks the original consumed claim/current scope/epoch/activation/directory grant. command_once allocates and freezes the actual RPC before invoking the original journal bind/revalidation hook inside the transport actual write-lock/lease barrier; the detached hook payload cannot alter the written bytes. Missing barrier/ACK/fence ports refuse before allocating an ID or binding. Hook failure performs no write and retains the transport unknown cut; a later receipt cannot reopen it. A lost receipt retains original id and UnitRecords unknown fence. Only a live retained original ticket can settle a later original receipt; cold reads do not reconstruct tickets or infer original completion from equal actual values.

The evidence port captures only sanitized original defaults request/receipt, bounded native layer revision, filtered readback and per-declaration outcome summary. It must persist and independently verify original native identity/readback provenance in its existing owner evidence store. It reconstructs ConfigurationChangeResult from the original attempt, never from current matching values or a second actual-state cache. Production port implementation is not completed by the controlled tests.

The local desktop Codex binary was later probed by the main session in isolation as version **0.159.0**, digest `d2752c52353401f7f6efbfcea68796f4f7a3d3e4769f5d1da53fa49d4856b72f`. This differs from the pinned 0.157.1 contract; it is not automatically compatible or selected. The old truncated npm artifact evidence remains a separate historical installation fact.

## Canonical Unit source reference

Prepare returns the original UnitReservation.public_ref unchanged: exactly environmentNamespace/unitId/ownerProviderRef/sourceRevision. The independent provider never generates that source hash or removes owner fields. Every supported Unit-consuming entry compares the complete caller reference against the object returned by the trusted original-journal projection; old two-field, forged activation/owner/source/environment and extra fields refuse before native/configuration writes.

Unit inspection also requires publication_facts to identify the same canonical Unit, owner provider, canonical configuration target and management epoch. The supplied DirectoryBindingRef and current observation sourceRevision remain their owners' facts; the immutable Unit source hash is not substituted for the current native observation or configuration revision. These controlled fixtures do not provide production authorization/native proof.

Configuration target references now consume the authorized original UnitReservation.configuration_target_ref unchanged, including ownerProviderRef/sourceRevision plus physical environment/scopeId/revision. Snapshot, Invocation target, journal receipt, item confirmation and query target share that exact reference; publication compares complete JSON identities including type-sensitive owner generation. Description.scope remains the contract's `instance` enum; it does not invent another target identity. Target source identity stays fixed independently of fresh native configuration versions.

## Prepared native requests

`CodexAppServerClient.prepare_request(method, params)` allocates the actual native
request ID and freezes its complete UTF-8 JSONL bytes before capture/admission.
It does not send, register a pending RPC, or grant effect permission. The shared
`PreparedFramePool` owns each opaque client-local handle; copied, foreign,
tampered, spent and closed handles cannot dispatch. Ordinary commands and
prepared requests use the same ID allocator.

`dispatch_prepared(frame, before_write=guard)` consumes that original handle once,
registers its original method/thread correlation, and sends its exact frozen
bytes through the transport's actual write-lock/lease barrier. The trusted
owner supplies `guard(actual_wire_bytes)` and checks those immutable bytes
against the original capture digest, native ID and opaque Core context. Guard failure also spends the
handle. Missing confirmation retains the original pending ID and fences input;
`recover_request(original_id)` can read a late receipt without sending again.
Receiving a late receipt does not reopen the uncertain transport for new input.
Native RPC errors retain their original error and are never automatically retried.
Only a structurally accepted original receipt acknowledges live transport IO
metadata; it does not publish Core input/effect facts. Revocation while awaiting
that receipt latches unknown even before the waiting caller notices. A late
receipt never clears that latch. The ACK and bare channel stay inside the
trusted family owner, never a public consumer handle.
Reverse requests retain native IDs and still require explicit caller replies.

This is a framing primitive, not a managed input writer or a production authority
port. Provider capability declarations do not expand. Capture, original claim,
durable native receipt/effect evidence, first Session association and production
lease composition remain separate, incomplete work. Tests use controlled
channels and temporary Python peers, without executing Codex or a model.

## Optional Server host binding

`ordessa_harness_codex.server_plugin.CodexServerPlugin(provider_factory)` is an explicit
optional binding to the existing `pacthold.contributions` point. The factory
receives the host's unique `EnvironmentId` and returns this package's provider
with matching definition namespace and explicit implementation digest/ports.
The host supplies owner activation; the wrapper does not install, activate,
issue authority, create a store or launch a native process. Owner ID remains
`codex`. Server API imports are lazy and the dependency is in the `server`
extra; base provider imports and wheel conversion need no Server API.

This proves contribution wiring only. In the optional Agent Tools deployment,
select wrappers through `AgentToolsDeployment(..., agent_contract_version=
"agent-assembly/2", provider_plugins=(... ,))`; the default tuple is empty.
Current deployment refuses provider publication on an existing root because
durable cold activation generations are not yet composed. Native production
ports, task readiness and successful cold recovery remain unverified.
