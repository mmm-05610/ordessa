"""Short-lived SQLite units of work for the local AgentBox data root."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
from typing import Iterator


PRODUCT_SCHEMA_VERSION = 21


class FutureSchemaError(RuntimeError):
    """The data root was written by a newer, unsupported Server."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agentbox_product_schema (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_workspaces (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL UNIQUE,
    distribution TEXT NOT NULL,
    remote_user TEXT,
    remote_path TEXT NOT NULL,
    connection_state TEXT NOT NULL,
    display_name TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    archived_at TEXT,
    env_kind TEXT NOT NULL DEFAULT 'wsl',
    env_host TEXT,
    normalized_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_profiles (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    harness_type TEXT NOT NULL,
    config_revision INTEGER NOT NULL CHECK (config_revision >= 1),
    native_generation INTEGER NOT NULL DEFAULT 0 CHECK (native_generation >= 0),
    config_object_digest TEXT NOT NULL,
    credential_id TEXT,
    account_id TEXT,
    permission_preset TEXT,
    permission_rules_json TEXT,
    origin_profile_id TEXT,
    cloned_at TEXT,
    run_state TEXT NOT NULL DEFAULT 'idle',
    recovery_pending INTEGER NOT NULL DEFAULT 0,
    display_name TEXT,
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_credentials (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    secret_locator TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_provider_models (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 1,
    display_name TEXT NOT NULL,
    harness_type TEXT,
    provider_type TEXT NOT NULL,
    credential_id TEXT REFERENCES server_credentials(id),
    config_object_digest TEXT NOT NULL,
    models_object_digest TEXT NOT NULL,
    base_url TEXT,
    auth_style TEXT,
    wire_api TEXT,
    fields_source TEXT,
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES server_workspaces(id),
    profile_id TEXT NOT NULL REFERENCES server_profiles(id),
    checkpoint_object_digest TEXT,
    checkpoint_native_id TEXT,
    native_platform TEXT,
    home_locator TEXT,
    latest_usage TEXT,
    status TEXT NOT NULL DEFAULT 'ready',
    display_name TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES server_sessions(id),
    profile_id TEXT NOT NULL REFERENCES server_profiles(id),
    profile_revision INTEGER NOT NULL,
    native_generation INTEGER NOT NULL,
    state TEXT NOT NULL,
    capture_state TEXT NOT NULL,
    cleanup_state TEXT NOT NULL,
    input_object_digest TEXT NOT NULL,
    effective_config_object_digest TEXT,
    queue_item_id TEXT REFERENCES server_queue_items(id),
    work_id TEXT,
    execution_id TEXT,
    dispatch_id TEXT,
    execution_key TEXT,
    captured_profile_revision INTEGER,
    result_object_digest TEXT,
    error_code TEXT,
    change_set_object_digest TEXT,
    parent_turn_id TEXT,
    usage_input_tokens INTEGER,
    usage_output_tokens INTEGER,
    usage_total_tokens INTEGER,
    usage_source TEXT,
    stop_requested_at TEXT,
    terminal_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS server_one_active_turn_per_session
ON server_turns(session_id) WHERE state IN ('accepted', 'dispatching', 'running', 'capturing');
CREATE TABLE IF NOT EXISTS server_session_events (
    session_id TEXT NOT NULL REFERENCES server_sessions(id),
    seq INTEGER NOT NULL,
    wire_seq INTEGER,
    event_id TEXT NOT NULL UNIQUE,
    turn_id TEXT,
    kind TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);
CREATE UNIQUE INDEX IF NOT EXISTS server_session_wire_order
ON server_session_events(session_id, wire_seq) WHERE wire_seq IS NOT NULL;
CREATE TABLE IF NOT EXISTS server_idempotency (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);
CREATE TABLE IF NOT EXISTS server_queue_items (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES server_sessions(id),
    version INTEGER NOT NULL CHECK (version >= 1),
    state TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    config_version INTEGER NOT NULL,
    request_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    message_object_digest TEXT NOT NULL,
    effective_config_object_digest TEXT,
    public_message_json TEXT,
    pause_reason TEXT,
    submitted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS server_queue_order ON server_queue_items(session_id, submitted_at, id);
CREATE TABLE IF NOT EXISTS server_approvals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES server_sessions(id),
    execution_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    state TEXT NOT NULL,
    decision TEXT,
    scope_json TEXT,
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    settled_at TEXT
);
CREATE INDEX IF NOT EXISTS server_approvals_by_execution ON server_approvals(execution_id, created_at);
CREATE TABLE IF NOT EXISTS server_accounts (
    id TEXT PRIMARY KEY,
    harness_type TEXT NOT NULL,
    account_identifier TEXT NOT NULL,
    state TEXT NOT NULL,
    asset_locator TEXT,
    asset_digest TEXT,
    last_verified_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_assets (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    latest_revision INTEGER NOT NULL,
    digest TEXT NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_profile_assets (
    profile_id TEXT NOT NULL REFERENCES server_profiles(id),
    asset_id TEXT NOT NULL REFERENCES server_assets(id),
    revision INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, asset_id)
);
CREATE TABLE IF NOT EXISTS server_hooks (
    id TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    model_json TEXT NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_hook_triggers (
    id TEXT PRIMARY KEY,
    hook_id TEXT NOT NULL REFERENCES server_hooks(id),
    event TEXT NOT NULL,
    at TEXT NOT NULL,
    exit_code INTEGER NOT NULL,
    output_summary TEXT NOT NULL,
    summary_truncated INTEGER NOT NULL DEFAULT 0,
    blocking INTEGER NOT NULL DEFAULT 0,
    effect TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_subagent_grants (
    parent_profile_id TEXT NOT NULL REFERENCES server_profiles(id),
    child_profile_id TEXT NOT NULL REFERENCES server_profiles(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (parent_profile_id, child_profile_id)
);
CREATE TABLE IF NOT EXISTS server_bootstrap (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    server_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

def _migrate_1_to_2(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS server_credentials ("
        "id TEXT PRIMARY KEY,kind TEXT NOT NULL,secret_locator TEXT NOT NULL UNIQUE,"
        "created_at TEXT NOT NULL)"
    )
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(server_turns)").fetchall()
    }
    additions = {
        "profile_id": "TEXT REFERENCES server_profiles(id)",
        "work_id": "TEXT",
        "execution_id": "TEXT",
        "dispatch_id": "TEXT",
        "result_object_digest": "TEXT",
        "error_code": "TEXT",
    }
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE server_turns ADD COLUMN {name} {declaration}")
    conn.execute(
        "UPDATE server_turns SET profile_id=(SELECT profile_id FROM server_sessions "
        "WHERE server_sessions.id=server_turns.session_id) WHERE profile_id IS NULL"
    )


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _backfill(conn: sqlite3.Connection, table: str, target: str, source: str) -> None:
    """Copy a legacy column into a new one where the new column is still null."""
    if not _has_table(conn, table):
        return
    available = _columns(conn, table)
    if target not in available or source not in available:
        return
    conn.execute(
        f"UPDATE {table} SET {target}={source} WHERE {target} IS NULL"
    )


def _add_columns(conn: sqlite3.Connection, table: str, additions: dict[str, str]) -> None:
    """Add missing columns to an existing table.

    A table that does not exist yet is skipped: `_SCHEMA` creates every table
    with the full column set, so an older data root that never had the table
    does not need this migration to invent one.
    """
    if not _has_table(conn, table):
        return
    columns = _columns(conn, table)
    for name, declaration in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _migrate_17_to_18(conn: sqlite3.Connection) -> None:
    """Order 65 C: the sub-execution link.

    A delegated turn names the parent turn that started it, so attribution
    (usage roll-up, cancellation propagation, the parent's relay) is one join
    away - the child stays a normal execution in every other respect.
    """
    _add_columns(conn, "server_turns", {"parent_turn_id": "TEXT"})


def _migrate_18_to_19(conn: sqlite3.Connection) -> None:
    """Order 110: a paused queued item records *why* it paused.

    Order 67 keeps stop/fail -> `paused` (no auto-adopt); the visibility fix is
    that the pause reason (e.g. `cancelled`, or a failure code) must reach the
    UI so the item is explainable and the user can choose to withdraw and resend.
    Existing rows keep NULL - a pause before this build had no recorded reason,
    which is the honest absence, not a fabricated one.
    """
    _add_columns(conn, "server_queue_items", {"pause_reason": "TEXT"})


def _migrate_20_to_21(conn: sqlite3.Connection) -> None:
    """a-3 K1.1+K1.2: two turn columns, two separate semantics, one window.

    `execution_key` (K1.1) is minted by the Session side at acceptance
    (turn-id derived: idempotent, debuggable, no secret content) and consumed
    by the post-commit filing step as the Work Core idempotency key.
    `captured_profile_revision` (K1.2, ruling t39=甲) records the revision the
    c-1B delegation anchor was enforced against - its only writer is that
    anchored INSERT (E leg), so Session-side rows keep NULL: never written,
    honest absence. Both are pure DDL adds: zero backfill, zero rewrites;
    pre-existing rows expose raw NULL per the s-c1 discipline and object-plane
    shape (b), same wording precedent as pause_reason@18->19. The existing
    `profile_revision` column's semantics are untouched (micro-ruling alpha).
    """
    _add_columns(conn, "server_turns", {
        "execution_key": "TEXT",
        "captured_profile_revision": "INTEGER",
    })


def _migrate_19_to_20(conn: sqlite3.Connection) -> None:
    """Order 092 stage 2: a provider record may be harness-neutral (shared).

    `harness_type` goes from NOT NULL to nullable so one upstream can be
    referenced by any declaration-compatible harness (NULL = shared). SQLite
    cannot drop a column constraint in place, so the table is rebuilt. The copy
    names every column explicitly (not `SELECT *`) so it never depends on the old
    column order. Forward-only: a row that has become shared (NULL) cannot be
    re-promoted to the old NOT NULL invariant without inventing a harness for it,
    so "rollback" means "stay at 19, where no NULL row may exist" - documented,
    not executed, and safe because no NULL row exists until a shared record is
    first created. An existing tree whose column is already nullable is skipped
    (idempotent across a re-initialize).
    """
    if not _has_table(conn, "server_provider_models"):
        return
    column = next((row for row in conn.execute(
        "PRAGMA table_info(server_provider_models)").fetchall()
        if row[1] == "harness_type"), None)
    if column is None or column[3] == 0:  # already nullable - nothing to rebuild
        return
    conn.executescript(
        """
        PRAGMA foreign_keys = off;
        CREATE TABLE server_provider_models_v20 (
            id TEXT PRIMARY KEY,
            version INTEGER NOT NULL DEFAULT 1,
            display_name TEXT NOT NULL,
            harness_type TEXT,
            provider_type TEXT NOT NULL,
            credential_id TEXT REFERENCES server_credentials(id),
            config_object_digest TEXT NOT NULL,
            models_object_digest TEXT NOT NULL,
            base_url TEXT,
            auth_style TEXT,
            wire_api TEXT,
            fields_source TEXT,
            archived_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO server_provider_models_v20 (
            id, version, display_name, harness_type, provider_type, credential_id,
            config_object_digest, models_object_digest, base_url, auth_style,
            wire_api, fields_source, archived_at, created_at, updated_at)
        SELECT id, version, display_name, harness_type, provider_type, credential_id,
            config_object_digest, models_object_digest, base_url, auth_style,
            wire_api, fields_source, archived_at, created_at, updated_at
        FROM server_provider_models;
        DROP TABLE server_provider_models;
        ALTER TABLE server_provider_models_v20 RENAME TO server_provider_models;
        PRAGMA foreign_keys = on;
        """
    )


def _migrate_16_to_17(conn: sqlite3.Connection) -> None:
    """Order 65 A: explicit delegation edges (none by default).

    One row per granted edge: a parent Profile may call the child. Visibility
    and tool materialisation derive from these rows, and nothing else does.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS server_subagent_grants ("
        "parent_profile_id TEXT NOT NULL REFERENCES server_profiles(id), "
        "child_profile_id TEXT NOT NULL REFERENCES server_profiles(id), "
        "created_at TEXT NOT NULL, "
        "PRIMARY KEY (parent_profile_id, child_profile_id))"
    )


def _migrate_15_to_16(conn: sqlite3.Connection) -> None:
    """Order 60 A: the profile's permission posture and clone origin.

    `permission_preset` names the starting preset, `permission_rules_json` the
    ordered overrides (last match wins); `origin_profile_id`/`cloned_at` mark a
    clone and its source, so a clone never has to pretend it inherited native
    sessions.
    """
    _add_columns(conn, "server_profiles", {
        "permission_preset": "TEXT",
        "permission_rules_json": "TEXT",
        "origin_profile_id": "TEXT",
        "cloned_at": "TEXT",
    })


def _migrate_14_to_15(conn: sqlite3.Connection) -> None:
    """Order 59 G5: the hook trigger ledger.

    One row per observed hook execution: the bounded output summary, the exit
    code, and the effect the families' semantics give it (`blocked` for exit
    2, never folded into a plain success).
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS server_hook_triggers ("
        "id TEXT PRIMARY KEY, hook_id TEXT NOT NULL REFERENCES server_hooks(id), "
        "event TEXT NOT NULL, at TEXT NOT NULL, exit_code INTEGER NOT NULL, "
        "output_summary TEXT NOT NULL, summary_truncated INTEGER NOT NULL DEFAULT 0, "
        "blocking INTEGER NOT NULL DEFAULT 0, effect TEXT NOT NULL)"
    )


def _migrate_13_to_14(conn: sqlite3.Connection) -> None:
    """Order 59: the managed-hook ledger.

    One row per hook: its family, its name, whether the user enabled it, and
    the model (the family's own declarative shape, validated before storage).
    Disabled is the default: a hook only runs once a user enabled it.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS server_hooks ("
        "id TEXT PRIMARY KEY, family TEXT NOT NULL, name TEXT NOT NULL, "
        "enabled INTEGER NOT NULL DEFAULT 0, model_json TEXT NOT NULL, "
        "source TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )


def _migrate_12_to_13(conn: sqlite3.Connection) -> None:
    """Order 58: managed skill/MCP assets and their profile bindings.

    `server_assets` is the catalogue (kind, name, latest revision, digest,
    source); `server_profile_assets` is the binding (a Profile references an
    asset id and a revision, and can disable it without dropping the
    reference). Neither table carries asset *content* - that lives under the
    assets root, content-addressed.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS server_assets ("
        "id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, "
        "description TEXT, latest_revision INTEGER NOT NULL, digest TEXT NOT NULL, "
        "source TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS server_profile_assets ("
        "profile_id TEXT NOT NULL REFERENCES server_profiles(id), "
        "asset_id TEXT NOT NULL REFERENCES server_assets(id), "
        "revision INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY (profile_id, asset_id))"
    )


def _migrate_11_to_12(conn: sqlite3.Connection) -> None:
    """Order 56: the profile's bound subscription account.

    A binding, not a credential: the account row (server_accounts) owns the
    asset; the profile only names which account a turn materialises.
    """
    _add_columns(conn, "server_profiles", {"account_id": "TEXT"})


def _migrate_10_to_11(conn: sqlite3.Connection) -> None:
    """Order 56: managed subscription accounts.

    One row per account the control plane owns. The row holds the family, the
    account identifier, the observed state, and the *reference* to the asset
    in the secret store - never a token.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS server_accounts ("
        "id TEXT PRIMARY KEY, harness_type TEXT NOT NULL, "
        "account_identifier TEXT NOT NULL, state TEXT NOT NULL, "
        "asset_locator TEXT, asset_digest TEXT, last_verified_at TEXT, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )


def _migrate_9_to_10(conn: sqlite3.Connection) -> None:
    """Order 67: the uniqueness unit is the Session, not the Profile.

    The per-profile partial unique index enforced "one active Turn per
    Profile", which the 2026-09-18 ruling corrected: a Profile may run
    several different Sessions at once (the per-session index remains the
    real writer invariant). Dropping is idempotent and forward-only; the
    schema script no longer re-creates it, so no startup can bring it back.
    """
    conn.execute("DROP INDEX IF EXISTS server_one_active_turn_per_profile")


def _migrate_8_to_9(conn: sqlite3.Connection) -> None:
    """Order 54: the per-turn change set, published as a record object.

    `change_set_object_digest` references the diff document (added/modified/
    removed with honest line accounting and truncation facts). Optional: a
    turn without a workspace change set keeps NULL.
    """
    _add_columns(conn, "server_turns", {
        "change_set_object_digest": "TEXT",
    })


def _migrate_7_to_8(conn: sqlite3.Connection) -> None:
    """Order 55: provenance fields on the provider/model record.

    `base_url` / `auth_style` / `wire_api` name the endpoint facts the record
    carries, `fields_source` says where those fields came from
    (preset/pulled/manual). Every column is optional: an old record keeps
    working with all of them NULL, which the product renders as "unknown" —
    never a guessed default.
    """
    _add_columns(conn, "server_provider_models", {
        "base_url": "TEXT",
        "auth_style": "TEXT",
        "wire_api": "TEXT",
        "fields_source": "TEXT",
    })


def _migrate_6_to_7(conn: sqlite3.Connection) -> None:
    """Order 51: the usage fact, recorded as optional turn columns.

    Tokens only, straight from what a family's native store reported - no
    estimates, no per-char stand-ins, and a family that reports nothing keeps
    every column NULL. `usage_source` names the format that produced the
    numbers so the numbers stay auditable.
    """
    _add_columns(conn, "server_sessions", {
        "latest_usage": "TEXT",
    })
    _add_columns(conn, "server_turns", {
        "usage_input_tokens": "INTEGER",
        "usage_output_tokens": "INTEGER",
        "usage_total_tokens": "INTEGER",
        "usage_source": "TEXT",
    })


def _migrate_5_to_6(conn: sqlite3.Connection) -> None:
    """Reference the native home instead of storing its bytes.

    `native_platform` names the machine family that owns the Profile's home
    directory and `home_locator` locates it relative to that machine's home
    root - never an absolute host path. `checkpoint_object_digest` keeps its
    column and its name, but from this schema on it points at the audit
    manifest (a record), not at captured state bytes.
    """
    _add_columns(conn, "server_sessions", {
        "native_platform": "TEXT",
        "home_locator": "TEXT",
    })


def _migrate_2_to_3(conn: sqlite3.Connection) -> None:
    """Add the wire/1 record identity, version, and archive fields.

    Nothing is rewritten or dropped: existing rows keep their identity and the
    new columns receive the defaults that make them describe the same objects
    (version 1, display name derived from the existing path/name, not archived).
    """
    _add_columns(conn, "server_workspaces", {
        "display_name": "TEXT",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "archived_at": "TEXT",
        "env_kind": "TEXT NOT NULL DEFAULT 'wsl'",
        "env_host": "TEXT",
        "normalized_path": "TEXT",
    })
    _add_columns(conn, "server_sessions", {
        "display_name": "TEXT",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "archived_at": "TEXT",
    })
    _add_columns(conn, "server_profiles", {
        "display_name": "TEXT",
        "archived_at": "TEXT",
    })
    _add_columns(conn, "server_turns", {
        "stop_requested_at": "TEXT",
        "terminal_reason": "TEXT",
    })
    # Backfill from whatever columns this data root actually has. The identity
    # of every existing row is preserved and nothing is rewritten or dropped.
    _backfill(conn, "server_workspaces", "normalized_path", "remote_path")
    _backfill(conn, "server_workspaces", "env_host", "distribution")
    _backfill(conn, "server_workspaces", "display_name", "remote_path")
    _backfill(conn, "server_sessions", "display_name", "id")
    _backfill(conn, "server_profiles", "display_name", "name")


def _migrate_3_to_4(conn: sqlite3.Connection) -> None:
    """Freeze the effective configuration with accepted and queued work."""
    _add_columns(conn, "server_turns", {
        "effective_config_object_digest": "TEXT",
        "queue_item_id": "TEXT REFERENCES server_queue_items(id)",
    })
    _add_columns(conn, "server_queue_items", {
        "effective_config_object_digest": "TEXT",
    })
    _add_columns(conn, "server_profiles", {
        "version": "INTEGER NOT NULL DEFAULT 1",
    })
    conn.execute(
        "CREATE TABLE IF NOT EXISTS server_provider_models ("
        "id TEXT PRIMARY KEY,version INTEGER NOT NULL DEFAULT 1,display_name TEXT NOT NULL,"
        "harness_type TEXT NOT NULL,provider_type TEXT NOT NULL,"
        "credential_id TEXT REFERENCES server_credentials(id),"
        "config_object_digest TEXT NOT NULL,models_object_digest TEXT NOT NULL,"
        "archived_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
    )


def _migrate_4_to_5(conn: sqlite3.Connection) -> None:
    """Add shared Session metadata and a gap-free public event sequence."""
    _add_columns(conn, "server_sessions", {
        "pinned": "INTEGER NOT NULL DEFAULT 0",
    })
    _add_columns(conn, "server_queue_items", {
        "public_message_json": "TEXT",
    })
    _add_columns(conn, "server_session_events", {
        "wire_seq": "INTEGER",
    })
    if _has_table(conn, "server_session_events"):
        visible = (
            "'turn.accepted','turn.state','message.delta','message.final','tool.update',"
            "'approval.requested','approval.settled','config.changed','queue.updated',"
            "'workspace.connection'"
        )
        conn.execute(
            "UPDATE server_session_events AS target SET wire_seq=("
            "SELECT COUNT(*) FROM server_session_events AS prior "
            "WHERE prior.session_id=target.session_id AND prior.seq<=target.seq "
            f"AND prior.kind IN ({visible})) WHERE target.kind IN ({visible}) "
            "AND target.wire_seq IS NULL"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS server_session_wire_order "
            "ON server_session_events(session_id,wire_seq) WHERE wire_seq IS NOT NULL"
        )


class Database:
    """One local SQLite file with explicit, bounded transaction scopes."""

    def __init__(self, data_root: Path | str, *, timeout: float = 5.0) -> None:
        self.data_root = Path(data_root).resolve()
        self.path = self.data_root / "state" / "agentbox.sqlite"
        self.timeout = timeout
        self._write_lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agentbox_product_schema'"
            ).fetchone()
            current = 0
            if row is not None:
                version = conn.execute(
                    "SELECT version FROM agentbox_product_schema WHERE singleton=1"
                ).fetchone()
                if version is not None and int(version[0]) > PRODUCT_SCHEMA_VERSION:
                    raise FutureSchemaError(
                        f"data schema {version[0]} is newer than supported {PRODUCT_SCHEMA_VERSION}"
                    )
                current = int(version[0]) if version is not None else 0
            if current == 1:
                _migrate_1_to_2(conn)
            if current in (1, 2):
                _migrate_2_to_3(conn)
            if current in (1, 2, 3):
                _migrate_3_to_4(conn)
            if current in (1, 2, 3, 4):
                _migrate_4_to_5(conn)
            if current in (1, 2, 3, 4, 5):
                _migrate_5_to_6(conn)
            if current in (1, 2, 3, 4, 5, 6):
                _migrate_6_to_7(conn)
            if current in (1, 2, 3, 4, 5, 6, 7):
                _migrate_7_to_8(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8):
                _migrate_8_to_9(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                _migrate_9_to_10(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
                _migrate_10_to_11(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
                _migrate_11_to_12(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
                _migrate_12_to_13(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13):
                _migrate_13_to_14(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14):
                _migrate_14_to_15(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15):
                _migrate_15_to_16(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16):
                _migrate_16_to_17(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17):
                _migrate_17_to_18(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18):
                _migrate_18_to_19(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19):
                _migrate_19_to_20(conn)
            if current in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20):
                _migrate_20_to_21(conn)
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO agentbox_product_schema(singleton, version, applied_at) "
                "VALUES (1, ?, datetime('now'))",
                (PRODUCT_SCHEMA_VERSION,),
            )
            conn.execute(
                "UPDATE agentbox_product_schema SET version=?, applied_at=datetime('now') WHERE singleton=1",
                (PRODUCT_SCHEMA_VERSION,),
            )

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        with self._write_lock:
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
