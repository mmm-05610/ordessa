"""Work Order 121 v2: Work Core SQL-file migrations equivalence gate (permanent).

The auditors (AUD-B-009, manual W1-W4) found the Work Core migration runner had
no standing "upgrade == fresh install" check, and that reusing a reserved version
number (005 is a comment-only no-op precisely because a reused number made the
runner SILENTLY SKIP new schema) is a real, once-bitten trap. This codifies both.

Invariants:
* a fresh install and a legacy-data root upgraded to the same head end at the
  SAME ledger ([1..9]) and the SAME live structure (columns + indexes, every
  table) - the upgrade never diverges from greenfield;
* the 006 rebuild maps the legacy 'started' state to 'accepted', keeps unrelated
  terminal states, parks the original row in `core_dispatches_pre_v006_archive`,
  and MUST leave `inputs_digest` NULL (an old submission digest is never passed
  off as a frozen inputs digest);
* the whole chain is idempotent;
* a structural comparator witness proves the equality check actually sees a
  column drift (the gate is not vacuous).
"""
from __future__ import annotations

import re
import sqlite3

from pacthold_runtime_compat.legacy_migrations import MIGRATIONS_DIR
from pacthold_runtime_compat.legacy_migrations import db as wc
from pacthold_runtime_compat.legacy_migrations import register_legacy_migrations

# Post-T009 the historical chain is PRODUCT-ASSEMBLED (specs/010 plan §43:
# 「B 默认产品显式装配旧迁移集」) and SEALED inside the compat distribution:
# the SQL files this gate walks moved from the kernel tree to
# `pacthold_runtime_compat.legacy_migrations.MIGRATIONS_DIR` (byte-for-byte
# unchanged). Re-pointing the walk is an honest adaptation to a moved path:
# the same invariants (full ledger [1..9], upgrade == greenfield structure,
# 006 state mapping, idempotence, the 005 no-op) are asserted about the
# same files, at their new location. The kernel runner applies registered
# namespaces assembly-first, core-last, so this gate assembles the legacy
# namespace before every `_run_migrations` — `register_legacy_migrations()`
# is idempotent. Without it the legacy namespace is simply absent, which is
# exactly the OperationalError family T022b closes.
register_legacy_migrations()

_MIG = re.compile(r"^(\d{3})_.*\.sql$")


def _files():
    return sorted(
        (f for f in MIGRATIONS_DIR.iterdir() if _MIG.match(f.name)),
        key=lambda f: f.name)


def _max_version():
    return max(int(_MIG.match(f.name).group(1)) for f in _files())


def _ledger(conn):
    return sorted(r[0] for r in conn.execute(
        "SELECT version FROM schema_versions").fetchall())


def _signature(conn):
    sig = {}
    for name in [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name").fetchall()]:
        cols = tuple((c[1], c[2], c[3], c[4], c[5]) for c in
                     conn.execute(f"PRAGMA table_info({name})").fetchall())
        idx = tuple(sorted((c[1], c[2]) for c in conn.execute(
            f"PRAGMA index_list({name})").fetchall()))
        sig[name] = (cols, idx)
    return sig


def _fresh():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    wc._run_migrations(conn)
    return conn


def _seed_legacy_core(conn):
    conn.execute("PRAGMA foreign_keys = OFF")   # partial-shape seed, like a real old db
    conn.execute("INSERT INTO core_works(id,objective,lifecycle,metadata_json,created_at,"
                 "updated_at,version) VALUES ('w1','o','open','{}','t','t',0)")
    conn.execute("INSERT INTO core_executions(id,work_id,provider_id,phase,freshness,"
                 "observed_at,provenance_json,created_at,version) "
                 "VALUES ('e1','w1','p','running','observed','t','{}','t',0)")


def test_fresh_install_ledger_is_full_and_idempotent():
    conn = _fresh()
    assert _ledger(conn) == list(range(1, _max_version() + 1))
    before = _signature(conn)
    wc._run_migrations(conn)                       # re-run: no-op, no error
    assert _ledger(conn) == list(range(1, _max_version() + 1))
    assert _signature(conn) == before


def test_upgrade_with_legacy_data_equals_fresh_structure_and_maps_state():
    # build a "004-era" shape with a legacy dispatch row, then upgrade to head.
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY, "
                 "applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    for path in _files():
        version = int(_MIG.match(path.name).group(1))
        if version > 4:
            break
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_versions(version) VALUES (?)", (version,))
    # core_dispatches exists only from 004; seed a legacy 'started' dispatch.
    _seed_legacy_core(conn)
    conn.execute("INSERT INTO core_dispatches(id,execution_id,idempotency_key,state,"
                 "provider_correlation_ref,created_at,updated_at) "
                 "VALUES ('d1','e1','k1','started','ref','t','t')")
    conn.commit()
    wc._run_migrations(conn)                        # applies 005..009

    assert _ledger(conn) == list(range(1, _max_version() + 1))
    row = conn.execute("SELECT state,inputs_digest FROM core_dispatches WHERE id='d1'").fetchone()
    assert row[0] == "accepted"                    # 006 maps started -> accepted
    assert row[1] is None                          # inputs_digest NOT faked from old digest
    archived = conn.execute("SELECT state FROM core_dispatches_pre_v006_archive "
                            "WHERE id='d1'").fetchone()
    assert archived is not None and archived[0] == "started"   # legacy value preserved

    # structural equivalence to a fresh install (live schema converged).
    assert _signature(conn) == _signature(_fresh())


def test_reserved_version_005_is_recorded_not_silently_skipped():
    # the trap AUD-B-009 warns about: reusing 005 made the runner skip. The runner
    # must still record every version file it walks, including the no-op 005.
    conn = _fresh()
    assert 5 in _ledger(conn)


def test_counterexample_comparator_sees_a_column_drift():
    # prove the equivalence check is not vacuous: two same-name tables differing
    # only by one column's NOT NULL must produce different signatures.
    def build(nullable: bool):
        c = sqlite3.connect(":memory:")
        nn = "" if nullable else " NOT NULL"
        c.execute(f"CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT{nn})")
        return c
    assert _signature(build(True)) != _signature(build(False))
