# ordessa_infrastructure.database

Implementation: `options.py`, `sqlite.py` and caller-configured `migrations.py`.

## Public entry

* `SQLiteOptions` — the explicit connection contract (location, `uri`,
  `timeout`, `check_same_thread`, `row_factory`, `foreign_keys`,
  `busy_timeout`, and the `isolation_level`/`autocommit` pair guarded by
  `UNSET`).
* `create_connection(options) -> sqlite3.Connection` — a native connection.
* `database.migrations` provides `MigrationSource`, caller-owned
  `MigrationRegistry`, registration and apply functions. It owns no schema or
  default sources; the caller selects them and retains database authority.

## Contract and ownership

* On initialisation failure the freshly opened connection is closed; on success
  it belongs to the caller. A `with connection:` block is a transaction scope,
  not a close.
* `isolation_level` and `autocommit` are only forwarded to `sqlite3.connect`
  when set, so Python 3.12 transaction-control behaviour cannot change silently
  when a caller omits them. An unset pair reproduces plain `sqlite3.connect`:
  `isolation_level=""` and `autocommit=LEGACY_TRANSACTION_CONTROL`.
* `foreign_keys` and `busy_timeout` are explicit opt-ins (`None` = leave the
  connection default).
* **`busy_timeout` wins over `timeout`.** `sqlite3.connect(timeout=N)` seeds
  `PRAGMA busy_timeout` with `N*1000` ms; an explicit `busy_timeout` PRAGMA is
  applied afterwards, so the effective busy handler is the explicit value. In
  `product_database.Database` that is 5000 ms regardless of the configured
  `timeout`.
* **Busy timeout is verified.** The explicit PRAGMA value is read back; a
  mismatch raises `SQLiteConfigurationError` and closes the new connection.
  SQLite silently maps negative or overflowing values to zero, so requesting
  those values now refuses instead of returning an incorrectly configured
  connection. Valid values, zero, and omitted settings retain their behavior.
* **Foreign keys are verified, not assumed.** After applying
  `PRAGMA foreign_keys`, `create_connection` reads the value back; a mismatch
  raises `SQLiteConfigurationError` and closes the connection. This is required
  because `autocommit=False` starts the connection inside a transaction, where
  `PRAGMA foreign_keys` is a silent no-op — so `autocommit=False` combined with
  `foreign_keys=True` is refused rather than returning an unprotected handle.
  Legacy transaction control (the default) and `autocommit=True` enable foreign
  keys normally.

## What is not here

Business schemas, migration source selection/content, repositories,
transaction units of work, commit/rollback policy and WAL timing stay with
their owners. The generic registry/runner retains native SQLite script and
per-file commit behavior: a failed script can leave partial effects without
recording its version. It is not an atomic migration batch or a second UoW.

## Current consumers

`apps/server/src/ordessa_server/bootstrap/storage/product_database.py`
(`Database._connect`) builds a `SQLiteOptions`
and calls `create_connection`; behaviour is unchanged (`sqlite3.Row`,
`foreign_keys=ON`, `busy_timeout=5000`, default transaction control).

Engineering's `adapters/persistence/sqlite/engineering_library.py` and
`migrations.py` use the same native connection mechanism. Server selects
generic migration sources explicitly. The old kernel path is absent; overall
consumer migration and product qualification remain their owners' work.
