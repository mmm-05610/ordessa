# Ordessa infrastructure

Business-neutral technical mechanisms shared by Ordessa owners. The package owns no business schema, repositories, transaction units of work, authorization policy, or concrete plugin imports. It includes an explicitly caller-configured generic SQL migration mechanism; owners select migration sources and own schema policy. Importing its modules performs no runtime I/O.

## Public entries and current consumers

| Capability | Public API | Current in-repository consumers |
| --- | --- | --- |
| `encoding` | Python `canonical_bytes`, `decode_json`, `sha256` and explicit profiles; JavaScript `stableJSON`, `jsonDigest` | Engineering, Server, system-access bindings, Execution Agents, Harness plugins and ACP configuration resources. |
| `identifiers` | `now`, `opaque_id`, immutable `RequestKey` | Execution Agents Profiles and Execution Units use the shared request identity; the former c1 API re-exports the same Infrastructure type. `ordessa_workspace.directory_binding` still imports `RequestKey` from c1. |
| `database` / `database.migrations` | `SQLiteOptions`, `UNSET`, `create_connection`, `SQLiteConfigurationError`; migrations submodule: `MigrationSource`, caller-owned `MigrationRegistry`, registration and apply functions | Server product database and explicitly selected migration sources; Engineering SQLite Library and migration adapters. |
| `database.records` | `DomainWrite`, runtime-checkable `DomainStorePort`, `DomainRevisionConflict` (`code = "DOMAIN_REVISION_CONFLICT"`), `DOMAIN_STORE_VERSION` | Execution Agents Profiles and Execution Units import the technical contract in their store-facing services and persistence. `ordessa_workspace.directory_binding` still imports the former c1 contract. |
| `filesystem` / `filesystem.blobs` | Directory-relative opens, regular-file reads, exclusive creation and sync; blobs submodule: `ObjectStore`; staged `publish_file`; neutral errors | Engineering `adapters/filesystem/package_writer.py` uses dirfd primitives. Server runtime uses `ObjectStore`. `publish_file` currently has no in-repository non-test caller. |
| `security.secrets` / `security.windows_dpapi` | `SecretStore`, `MAX_SECRET_BYTES`, `SecretLocatorUnavailable`, `WindowsDpapiSecretStore` | Server Secret Service adapter and platform-selected Windows DPAPI store. Linux platform policy and backend selection remain Server-owned. |
| `process` | `FrameReader`, `Message`, `ChannelFailure`, `SubprocessHandle`, `spawn_process` | Execution Agents harness transport uses framing; Local Environment starts and owns one process through `spawn_process`. |
| `discovery` | `enumerate_entry_points`, `entry_point_source`, `load_entry_point` | Execution Agents sandbox provider resolution. Enumeration and loading are separate explicit actions. |

The Python distribution is declared in `python-workspace.json` and has no runtime dependencies. The root `ordessa_infrastructure/__init__.py` is documentation-only; submodule import performs no runtime I/O. The `security` directory has no concrete backend selected during import.

## Ownership and behavior

Infrastructure owns reusable mechanisms, not their product decisions:

* `RequestKey` is an immutable, opaque idempotency key; it does not authenticate a principal, verify an Environment lifecycle, or grant permission. `DomainWrite` declares a namespace/key/revision/value update. `DomainStorePort` requires its existing store implementation to perform compare-and-swap and request/result writes in the same existing transaction. Infrastructure adds no store, schema, UoW, lifecycle or authorization authority. The type migration is incomplete while `ordessa_workspace.directory_binding` still imports the c1 contract; current direct Infrastructure imports by Profiles and Units do not imply c1 retirement.

* Database schema, migration source selection/content, repositories, transaction units of work, commit/rollback policy and WAL timing stay with the database owners. The generic SQL migration registry and runner live here, with explicit caller-owned source selection and connection lifecycle.
* Filesystem business validation, complete-directory publication, identity-change cleanup, `wal`/`shm` cleanup and record-format-specific commit policy stay with callers. Callers provide permission bits and trusted directory descriptors where required.
* Process executable resolution, directory provisioning, timeout/cancellation policy, output draining, process-tree supervision and execution receipts stay with the environment/transport owners. `spawn_process` starts one process; its handle does not supervise descendants.
* Entry-point matching, admission, provider construction and trust decisions stay with the caller. Loading an entry point imports executable code and is explicit.
* Canonical encoding owners choose payloads, field inclusion, ordering and digest prefixes. Python and JavaScript behavior is not byte-equivalent for every possible value; see [`encoding/README.md`](src/ordessa_infrastructure/encoding/README.md).

`filesystem.publication.publish_file` is an available tested mechanism without a current in-repository non-test caller. Its presence and tests do not constitute a completed consumer migration. No new behavior is inferred from a package import or a passing isolated test.

The former `packages/execution/kernel` path is absent from the current tree. This README does not describe a historical kernel direction test as a current blocker or infer overall product retirement from consumers already using Infrastructure. Current migration completion and remaining owners are recorded in the applicable implementation status and evidence.

## Qualification evidence

Latest Infrastructure source tests and noneditable-wheel tests each pass 206 tests with zero skips; these are overlapping scopes and are not additive. The earlier 175-pass source/wheel qualification predates the generic records contract and remains historical evidence. Three unchanged Server database consumer assertions pass against actual Server source and the installed Infrastructure wheel. These scoped checks are not a full product distribution or overall retirement claim. Current integration status is summarized in [foundation](../../docs/implementation/packages-convergence-20261012/foundation/README.md).
