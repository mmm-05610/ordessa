# Engineering schema6 materials — explicit, partial product integration

`EngineeringLibrary` remains the sole database authority. Default creation stays schema2; `open` never upgrades. New material commands use interface2 and ArtifactRevision schema2, requiring explicit database schema6. Schema1 revisions remain readable with their exact old bytes and digests; new schema6 writes refuse schema1. A record version is not a database version.

The original schema4 DDL is unchanged. Schema6 rebuilds only `eng_artifact_revisions`, broadening its record-version constraint, copying its original seven columns unchanged, and recreating its two immutable triggers. Heads, parent edges, native identifiers, old tables and prior migration receipts remain. Fresh schema6 replays the same rebuild as an upgrade so the exact schema signature agrees, including SQLite's quoted renamed table name.

For an explicitly selected, owned synthetic/offline Library already at schema5:

```python
from pathlib import Path
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema5
receipt = migrate_schema5(library, backup_path=Path('/absolute/owned/backup-schema5.sqlite'))
```

The caller must select its own backup. The migration refuses aliases and overwrite, verifies and fsyncs the backup before writing, and keeps its read lock through source commit. Under the original Library lock it disables foreign keys outside a transaction and confirms the setting, then starts `BEGIN IMMEDIATE`, rechecks the original schema/data, rebuilds, checks all foreign keys, verifies exact schema6 and unchanged history, and commits. It restores and confirms foreign keys before reusing the connection. This follows [SQLite's documented rebuild procedure](https://www.sqlite.org/lang_altertable.html); the [foreign_keys pragma](https://www.sqlite.org/pragma.html#pragma_foreign_keys) does not change inside an active transaction.

Any write-phase failure closes the original authority. `migration_commit_unknown` means COMMIT or its following confirmation lost a definite result: reopen the same Library, inspect the target6 receipt and selected backup, and reconcile. Do not interpret it as confirmed rollback or blindly resend. Repeating an explicitly reconciled migration validates the same durable receipt and backup. No user database was migrated by this work.

Material bytes use the existing `eng_method_blobs` and original Library locator. Blob payload claims resolve real content. An excerpt's selector identifies the captured excerpt within those bytes; `EvidenceLink.source_selector` uses coordinates within the selected excerpt and cannot cite uncaptured context. Selectors verify exact selected bytes, using canonical JSON bytes for JSON Pointer values. Blob existence and readable links do not prove upstream authenticity, semantic support, or human consent. Immutable-version sources, artifact-owner sources and generation traces/executions currently refuse explicitly pending their actual owners.

MethodContent binds published MethodRef plus resource ID, path and digest. The same UoW loads the real frozen source bundle, verifies its compiled projection, requires `document_schema`, and validates the value against its actual schema. The [jsonschema Registry API](https://python-jsonschema.readthedocs.io/en/stable/referencing/) uses only that captured bundle; its retrieval callback refuses missing resources without network access. `referencing==0.36.2` is now a direct dependency. Method identity/source integrity does not prove current production trust or adoption.

The private resolution budget combines distinct blob bytes and snapshot canonical bytes up to64MiB; one snapshot is individually bounded at16MiB. Per-resolution selectors separately cap byte/hash work at64MiB, caching repeated selections while checking every expected digest. Parent closure retains its node/edge/canonical-byte budgets. These are refusal bounds, not claims that total process memory is64MiB. Storage/reconcile errors propagate and roll back reservations; only explicit finite business refusals become journaled rejected results.

See [current evidence](../implementation/nightly/evidence/W04/material-checkpoint.md) and [nightly status](../implementation/nightly/status.md). Production auth/catalog/trust, full source owners, Proposal/Consent/outbox, Server/CLI, WAL/hot-journal/native-FD/ABA and whole-product acceptance remain incomplete.
