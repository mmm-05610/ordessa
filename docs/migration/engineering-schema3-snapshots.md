# Engineering schema 3 snapshot storage and explicit migration

`EngineeringLibrary.create` still creates schema 2 by default. Opening a
schema 2 library leaves its bytes and version unchanged. `SQLiteSnapshotStore`
requires schema 3 and refuses schema 2 with `SNAPSHOT_SCHEMA_REQUIRED`; it does
not upgrade a library on behalf of its caller.

Schema 3 is additive. It adds exactly four tables:

- `eng_method_blobs`
- `eng_method_snapshots`
- `eng_method_releases`
- `eng_schema_migrations`

The original six schema 2 tables and their identifiers remain unchanged:
`library_meta`, `materials`, `heads`, `runs`, `step_log` and `idempotency`.
Their original schema 2 DDL is retained. A newly created library may opt into
schema 3 with `schema_version=3`; that is direct creation, not a schema 2
migration, and it has no migration receipt.

## Explicit migration contract

To upgrade an existing library, the caller must open the specific owned
`EngineeringLibrary` and explicitly call
`migrate_schema2(owned_library, backup_path=absolute_path)`. The backup path
must be absolute, distinct from the source file, and in a validated directory.
No product path is implied here. This is not an instruction to migrate a user
database.

The migration writes a complete schema 2 backup without overwriting an
existing file. It rejects source-file aliases even when expressed through a
path such as `child/../library.sqlite`, as well as symlink paths. An existing
backup is accepted only when it is a valid schema 2 library with the same
logical source contents. The receipt records both the canonical logical source
digest and the SHA-256 of the backup bytes. Backup validation holds a SQLite
read transaction while hashing through a bounded no-follow file descriptor.

The backup file and its parent directory are synced before the source write transaction; a sync failure leaves schema2 unchanged. After publishing and checking the backup, migration releases its read snapshot,
holds a read lock on the backup through the source commit, revalidates both backup digests, obtains a write transaction on the original connection, and rechecks the full
schema 2 source state before applying the four additive tables. It updates the
schema version and records the source digest, backup hash and backup path in
`eng_schema_migrations`. Legacy material rows, generated-head flags, runs,
steps and idempotency rows are retained. Migration does not create a second
library authority or replace the caller's connection.

If the same library is already schema 3, the same backup path and matching
backup receipt make a repeat call return `applied=False` without changing the
library or backup. A different backup path, changed backup, foreign/conflicting
backup or changed source is refused.

## Synthetic API example

This example creates an isolated schema 2 library in a temporary directory,
then explicitly migrates it. `TemporaryDirectory` supplies an absolute local
path; the example does not discover or access product or user data.

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
    EngineeringLibrary,
)
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema2
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore

with TemporaryDirectory(prefix="engineering-schema3-") as temporary:
    root = Path(temporary).resolve()
    source_path = (root / "library.sqlite").resolve()
    backup_path = (root / "library-schema2-backup.sqlite").resolve()

    schema2 = EngineeringLibrary.create(source_path, library_id="synthetic:snapshot")
    schema2.import_material(
        kind="source-fact", stable_id="fact:one", body={"text": "synthetic"}
    )
    schema2.close()

    owned_library = EngineeringLibrary.open(
        source_path, library_id="synthetic:snapshot"
    )
    try:
        receipt = migrate_schema2(owned_library, backup_path=backup_path)
        assert receipt.applied is True
        store = SQLiteSnapshotStore(owned_library)
        # Use `store` only through its explicit snapshot API.
    finally:
        owned_library.close()
```

For a new, empty library that does not need a schema 2 migration, the caller
can instead pass `schema_version=3` directly to `EngineeringLibrary.create`
before constructing `SQLiteSnapshotStore`.

## Failure and recovery behavior

Backup, source-recheck or DDL failures do not authorize a blind retry. A DDL
failure is rolled back on the original connection; the migration closes that
connection, and the library remains schema 2 when rollback is confirmed. If
rollback itself fails, the library is closed and the rollback error is
reported while retaining the primary failure as its cause.

A `COMMIT` exception or post-commit bound-check failure has an unknown result
from the caller's perspective: the connection is closed and the commit may
already be durable. Do not retry with a new backup or mutate the source. Reopen
the same explicit library path, inspect the version and `eng_schema_migrations`
receipt, and compare its recorded backup path/hash before deciding whether the
migration committed. Calling the migration again with the same validated
backup is an explicit reconciliation query: if the durable receipt and backup
match, it returns `applied=False`.

## Acceptance limits

`SQLiteSnapshotStore` and the explicit schema migration are implemented and
covered by synthetic Engineering tests. This does not complete production
capability-catalog integration, application UoW, journal/outbox, the CLI loop,
or real method quality/acceptance. Opening still refuses WAL and recovery
sidecars; path checks do not prove safety against OS-level ABA replacement.
No automatic schema upgrade, product startup migration command, or user
database migration is provided. W04 remains PARTIAL; current test and safety
evidence is recorded in the [nightly status](../implementation/nightly/status.md)
and [W04 evidence directory](../implementation/nightly/evidence/W04/).
