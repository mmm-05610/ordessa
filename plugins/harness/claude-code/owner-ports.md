# Current owner seam and gaps

This is a deployment composition record, not a new core or persistence contract.
The frozen core `agent-runtime/2` methods are unchanged. The provider's generic
unit_port is an explicit hook for the existing journal/native owner, not an
implemented second runtime. Its missing methods are unsupported today.

| Existing object / port | Used public method | Current behavior |
| --- | --- | --- |
| Core RuntimeProviderDescriptor / AgentContributionSet | fixed definition + `supported_methods`; contribution | Same CoreRegistry admission. No author activation identity or side registry. |
| Existing UnitRecords | `reserve_unit(context, provider_ref=..., node_ref=..., input_digest=..., private_root_facts=...)` | Provider prepare reserves the existing owner scope and returns the original reservation's immutable `public_ref` as `unitRef`. No private reservation object escapes, no process/session is started, no Node readiness is claimed. |
| Trusted original core-operation preparation projection | `verify_preparation(plan, invocation_facts)` -> exact bool | Must verify every supplied root/native/material/profile/correlation against the fixed original operation context and claim digest in the same store. Without this port or the exact same UnitRecords verifier, prepare is not advertised. Copied valid inputDigest does not authorize a new plan. |
| Existing UnitRecords | `begin_unit`, `record_unit`, `read_unit_confirmation`, `reconcile_unit_confirmation` | Sessionless original Unit start/query coordination uses frozen `harness-unit-confirmation/1`. Confirmation requires the original NativeUnitEvidencePort proof, never SDK ACK/cache or invented Session id. Real owner composition remains absent. |
| Core InvocationVerifier | `verify_and_consume(context, action, provider_ref, target_ref, input_digest)` | Config and destructive lifecycle helpers consume original authority, compare owner/epoch and target. Query helpers verify current query context. |
| Existing owner projection | `inspect_unit(unit_ref)` -> UnitInspection | Typed current provider/unit/configurationTarget/directory/epoch/ownership provenance required. No Profile-derived actual state. Production projection not supplied in this slice. |
| Existing configuration owner | `inspect_configuration(unit_ref)` -> ConfigurationSnapshot | Fresh actual source revision and comparison guarantee required; provider refuses missing/stale revision before claim. Atomic owner serialization/recheck must occur at dispatch. |
| Existing configuration owner | `apply_configuration(unit_ref, request, consumed_context)` -> ConfigurationChangeResult; `query_change(unit_ref, operation_ref, query_context)` -> same | Needs existing original-operation durable native evidence. SDK set_model ACK alone stays unknown. No new configuration ledger is added here. Production owner not supplied. |
| Existing unit entrance owner | `describe_access(unit_ref)`, `connect(unit_ref, authorized_lease)` | Needs identity-bound currently authorized connection; no raw SDK client escape. Lease issuer/deployment not composed by this slice. |
| SDK custom transport | `connect/write/read_messages/close/is_ready/end_input`; `authority.dispatch_guard(raw_payload)` async context manager | FencedSdkTransport gates every write. Authority must cover activation/epoch/lease/full native effects through dispatch. Isolated native transport and authority are deployment injections, no ambient default. |
| Existing owner lifecycle | `stop/release/recover` frozen RuntimeProvider signatures | Stop receipt, ownership-sensitive release, and original native binding recovery remain missing production seams. They are never marked supported by default. |

Source revisions are opaque owner facts. There is no receive-order latest-state
cache, Profile fill-in, new native session id selection, automatic config rollback,
unknown resend or latest-session recovery. A failed/unknown creation retains its
existing journal reservation; this adapter never clears it to create a replacement.

The plan supplied to prepare is private provider data derived by the core's
future complete preparation composition. It cannot be accepted as an invocation
authority; the explicit preparation projection verifies it against the original
operation and UnitRecords consumes the issued context. The plan itself does not
publish a public Unit binding or Node.

Shared reference freeze `3826f18204` supplies `UnitReservation.public_ref` with
exact environmentNamespace/unitId/ownerProviderRef/sourceRevision. This package
consumes that owner property unchanged; it never derives or repairs these fields.
The trusted production unit projection still needs authorized reads from the
original journal and whole-reference comparison for every instance entrance.
Missing production projection remains unsupported; returning a correct prepared
Unit reference does not prove native creation or session readiness.

The pinned SDK's `SystemMessage(subtype="init")` carries the native raw frame in
`.data`. This package now consumes that actual session_id, refuses missing,
empty, `default`, malformed or mismatched identities, and preserves the typed
message/raw fields. An init receipt neither completes a pending turn nor grants
permission to resend. Unit creation without a session uses the separate original owner confirmation
contract; connect alone does not fabricate nativeSessionRefs.

Before production method declaration, the main composition must prove: same
journal/provider/unit/operation identity; native creation evidence; actual config
source/serialized scope; write fence under revocation/retirement; and owned stop/
release evidence. Merely implementing an object with method names is insufficient.

No real Claude runtime or SDK exists in the tested baseline. Installation and
model task verification need separate user authorization; missing resources keep
P/M unverified and the family PARTIAL. C tests do not authorize these operations.

## Original Unit coordination at shared freeze 9e1a6db19b

`unit_lifecycle.ClaudeUnitCoordinator` only coordinates the existing journal and
opaque InvocationContext. Deployment must supply the same records/verifier/native
evidence objects on every port. `projection.read_unit(ref, context)` performs
authorized original reads; `resolve_original_start(correlation, context)` resolves
the original start, never a latest-session lookup. `effects.dispatch_guard(unit,
context, phase)` holds a native dispatch fence; `open_owned(unit, context)` retains
the original handle and `initialize_owned(unit, handle, context)` returns actual
owner evidence. The coordinator rechecks `verify_continuation` before and inside
each effect. The owned FencedSdkTransport must gate every SDK-generated write.

`observations.query_original_unit(unit, correlation, query_context)` observes
original evidence or returns None. Cold query uses the original start binding,
digest and revision; it issues no ticket, opens no handle, sends no input and
never closes or kills unknown handles. Missing owner/effect ports omit start;
missing original observation ports omit query_step. No async execution bridge is
created here. A production bridge must preserve the real SDK client's original
async lifetime, transport, process and current authority; no such bridge or
production ports are composed in this package.

Prepare receipt-loss recovery is an explicit remaining gap: UnitRecords publishes
whole-reference reads, but no public original preparation-correlation lookup.
The current query coordinator supports original Unit start only. Deployment must
not resolve preparation correlation as a start or synthesize a new correlation.
A same-journal authorized preparation lookup and separate result semantics are
required before advertising preparation recovery. First input/session association
is separate main-owned work and is not implemented by this slice.
