# Model-provider API Key entry: implementation contract

Scope: product keyring and model-provider only; no Profile/Harness/host/Pacthold changes.
Shared TS shapes: `plugins/assets/model-provider/contracts/service.ts`.

- `modelProvider.importApiKey {requestId,harnessId,apiKey}`; `queryApiKeyImport {requestId,harnessId}`.
- Closed reply `{operationId,state,credentialId?,kind?}`; operationId is exactly `key-import:<requestId>`. State imported carries credentialId and kind=api-key; unknown/not-found/refused carry neither. Query never imports or reads keys.
- Validate actual composed Harness credential_kind=api-key; nonempty bounded UTF-8 key with no control characters; never echo secret, store request body/fingerprint in receipts, or put it into provider/Profile JSON.
- Persist operation reservation in domain-owned SQLite under data-root/plugins/model-provider **before** store effects, unique requestId and original harness. Same requestId import never invokes store twice: reject already-started and direct caller to query. Query/restart retain unknown honestly. Wrong harness is conflict. No automatic retry.
- Store optional import_bytes avoids plaintext files; mandatory SecretStore protocol stays unchanged. Missing capability is typed refusal. Import creates a credential then registers existing CredentialRecords; only exact new locator may be cleaned if registration fails. Completed operation persisted for query. Ambiguous effects remain unknown, not failed/not-found; no crash atomicity is claimed across keyring/SQLite.
- Before-effect validation/storage availability refusal may mark refused. Timeout/ambiguous store operation stays unknown. Never erase an unknown operation to retry it. UI preserves its id for explicit query, never automatically reimports.
- Settings transient password input cleared after attempt/cancel/unmount. Result only updates credentialId of same draft generation; late results cannot attach to another provider/Harness. Double-click causes one import/save. Save only opaque credentialId.
- Fix provider save requestId and new config empty models in same UI unit. Explicit manual model IDs supported; no automatic model/network probe. Provider/protocol fields must produce a valid existing resolver choice; existing semantics and edit CAS retained.
- `providerModels.create/update` admit optional `protocols` and `endpoints`, forwarded unchanged into existing catalogue validators/persistence/projection. Omitted old requests stay unchanged; edit omission preserves prior facts. Never infer these capability facts merely from provenance. UI explicitly chooses canonical protocol and Base URL, sends protocols=[choice], endpoints={choice:URL}; readback carries optional protocol/endpoint facts. Codex/Claude/Pi differences remain validated by Harness catalogue/resolver, not an invented frontend support table.
- Unknown save retains frozen save request identity and prohibits generating another request blindly. No exception/key/backend text in user-visible messages.

Ownership: parent contracts/docs/product store+tests/packaging/git. Backend agent only model-provider server implementation/tests. Frontend agent only model-provider desktop implementation/tests. Controlled tests and actual synthetic keyring proof remain distinct; no real model calls, existing key reads or global config changes.
