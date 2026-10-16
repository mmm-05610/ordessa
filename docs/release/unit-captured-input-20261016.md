# Captured input on the original fresh Unit owner

This follow-up replaces the unsupported native-provider managed-input coordinator with the explicitly selected `ManagedUnitInputs` capability on the original fresh Unit ACP path. The selection is programmatic. It does not advertise lifecycle readiness through Harness metadata, start a Unit, issue a Grant, or supply a default Workspace authority.

## Public selection and authority

Create the existing local Unit owner with ACP durable-record opt-in and deferred effect-write finalization, assemble its original journal/issuer/records/manager, then bind `ManagedUnitInputs(owner, capture_content=..., workspace_execution=...)` before creating any Unit. The existing manager enforces one-time finalization. Use the `local-owner` optional dependency for this host-bound composition; pure Harness compilation keeps its existing portable import closure.

The capture port returns immutable `UnitTextCapture` facts for the exact captured reference and Unit. The new `unit-captured-text/1` format preserves text bytes through canonical UTF-8 JSON, refuses attachments/configuration it cannot represent, and applies a conservative bound within the original ACP evidence capacity. Historical `managed-codex-text/1` captures retain their codec and identifiers. No historical capture is rewritten.

The Workspace port must be a trusted application selection of the real Workspace authority. It authorizes the exact request, Unit, operation and capture, then provides a cooperative asynchronous guard sharing its real revoke writer's synchronization. A DTO or callable shape is not authentication. There is no empty production adapter or fallback; a product without this explicit port remains unavailable. The original Unit run permission, owner identity, lease and native client are independently rechecked.

## Single dispatch and query

The original SQLite operation store atomically reserves the request and a capture-attempt CAS fence in its existing domain table. The new namespace is `units.captured-input-attempts`; no SQL schema migration or changes to historical namespaces are required. After one durable claim the existing UnitInstance sends the original ACP `session/prompt`, using the original fixed guard and UnitRecords ACP journal. Core stores the capture association and stable acceptance projection; UnitRecords remains the native request/response authority.

The Workspace guard covers the actual bounded byte write and current source/permission checks. Other-thread Host revocation waits for the admitted write. If a trusted same-SDK-thread callback reenters a synchronous host guard and revokes after bytes have gone out, the post-write check refuses acceptance and preserves unknown. Already transmitted bytes are never represented as undone.

Same-request replay never prompts again. Another key cannot evade an unresolved capture fence. Claim-before-ACP and receipt-publication failures remain query-only. A specifically authorized optional absent-receipt read returns unknown; normal ACP queries retain their default missing-row refusal, all identity checks and integrity validation. Query reads the original UnitRecords using the existing read-only issuer path, including after Unit release, and publishes Core only from an original terminal receipt. No cold native handle is reconstructed and no process is relaunched.

## Retirement and verification scope

`ManagedCodexInputService` and its native-provider lookup/dispatch/query coordinator are removed. Its former acceptance, exact-owner, one-write, replay, unresolved-new-key and terminal-query positive case is retained under the fresh Unit owner tests, with a real controlled ACP peer and original host access/store/issuer/records/verifier. The historical capture-codec assertions stay in the Codex leaf. The lower-level Codex provider and unrelated native APIs are outside this coordinator cut; this is not full brand-runtime retirement.

Tests cover real byte-write counting and guard lifetime, copied Unit and principal rejection, capture digest/loss checks, write-time Workspace revocation, permission expiry, Host access revocation, partial commits, missing ACP receipts, query after release, binding replacement refusal, unrelated direct prompts, and concurrent request keys at the capture fence. All native peers are controlled local fixtures; no real model, existing user service or user database is used. Real product Workspace/capture selection and whole-product execution remain separate, explicit assembly work.

Exact-source validation: 85 passed (19 captured-input cases, 21 original local-owner query cases, 4 metadata-retirement cases, 36 pure-read cases and 5 historical codec/missing-port cases). The Unit wheel builds offline, carries the new modules byte-for-byte, and declares the host composition dependency only under its explicit extra. Three historical Codex skips remain unchanged.


The blocking CI also runs the existing original-owner selection checks (9 passed)
and public fresh Unit factory checks (2 passed). These exercise the actual
records/verifier identities, refusal of a cold records clone and substituted
selected ports, and two real Units retaining the exact original records/verifier
while their own process bindings run the original start gate. Harness declaration
DTO rejection tests cover metadata shape only; they do not stand in for these
native owner checks. The fresh Unit positive case is the corresponding owner
requirement after the retired provider factory is removed.
