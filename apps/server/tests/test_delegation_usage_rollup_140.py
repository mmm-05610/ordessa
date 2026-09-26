"""Work Order 140: a delegated child's usage must roll up to the parent turn.

`UsageAggregator` used to sum a session's completed turns only. A child turn runs
inside its parent's tool call but is recorded in a *different* session, so a
conversation that delegated spent tokens the parent's bill never showed (AUD-B-022:
parent 110 vs child 9500 at the same moment). ops takes the read-side fix: attribute
each completed turn to the session of its topmost `parent_turn_id` ancestor (root =
parent), multi-level, with no turn counted twice.

These gates build real sessions with real completed turns (not a hand-fed aggregate)
and assert:
* the parent's aggregate contains the child's and the grandchild's tokens;
* querying parent + child + grand together does not double-count;
* a non-delegating session is unchanged.
"""
from __future__ import annotations

from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.profiles import ProfileRecords
from ordessa_server_compat.sessions import SessionRecords
from ordessa_server_compat.usage_aggregate import UsageAggregator
from ordessa_workspace import WorkspaceRecords
from pacthold.storage import Database


def _turn(conn, *, turn_id, session_id, profile_id, usage, parent=None):
    conn.execute(
        "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
        "native_generation,state,capture_state,cleanup_state,input_object_digest,"
        "usage_input_tokens,usage_output_tokens,usage_total_tokens,usage_source,"
        "parent_turn_id,created_at,updated_at) "
        "VALUES (?,?,?,1,0,'completed','done','none','x',?,?,?, 'fake',?,'t','t')",
        (turn_id, session_id, profile_id, usage[0], usage[1], usage[2], parent))


def _ledger(tmp_path):
    db = Database(tmp_path / "data")
    db.initialize()
    idem = IdempotentRecords(db)
    profiles = ProfileRecords(db, idem)
    workspaces = WorkspaceRecords(db, idem)
    ws = workspaces.create(key="w", request_digest="w", distribution="Ubuntu",
                           remote_user="t", remote_path="/w", connection_id="w")[1]["workspace_id"]

    def prof(name):
        return profiles.create(key=name, request_digest=name, name=name, harness_type="codex",
                               config_digest="sha256:" + "0" * 64, credential_id=None)[1]["profile_id"]

    alpha, beta, gamma, delta = prof("alpha"), prof("beta"), prof("gamma"), prof("delta")
    session_of = {}
    with db.transaction() as conn:
        for key, profile_id in (("sa", alpha), ("sb", beta), ("sg", gamma), ("sd", delta)):
            conn.execute(
                "INSERT INTO server_sessions(id,workspace_id,profile_id,status,version,"
                "created_at,updated_at) VALUES (?,?,?, 'ready',1,'t','t')",
                (key, ws, profile_id))
            session_of[key] = key
        # parent -> child -> grandchild delegation chain (each in its own session).
        _turn(conn, turn_id="pt", session_id="sa", profile_id=alpha, usage=(50, 60, 110))
        _turn(conn, turn_id="ct", session_id="sb", profile_id=beta, usage=(5000, 4500, 9500), parent="pt")
        _turn(conn, turn_id="gt", session_id="sg", profile_id=gamma, usage=(50, 50, 100), parent="ct")
        # a session that never delegates.
        _turn(conn, turn_id="dt", session_id="sd", profile_id=delta, usage=(25, 25, 50))
    return db, {"alpha": "sa", "beta": "sb", "gamma": "sg", "delta": "sd"}



def test_parent_aggregate_includes_the_whole_delegation_chain(tmp_path):
    db, s = _ledger(tmp_path)
    agg = UsageAggregator(db).aggregate_by_session([s["alpha"]])
    # root at alpha = pt(110) + ct(9500) + gt(100) = 9710 (G1 one level, G2 multi).
    assert agg[s["alpha"]]["totalTokens"] == 9710
    assert agg[s["alpha"]]["turnsReported"] == 3


def test_querying_root_and_leaves_never_double_counts(tmp_path):
    db, s = _ledger(tmp_path)
    both = UsageAggregator(db).aggregate_by_session([s["alpha"], s["beta"], s["gamma"]])
    # Every child/grandchild turn belongs to exactly one root (alpha); querying the
    # leaf sessions too must not add a second copy.
    assert both[s["alpha"]]["totalTokens"] == 9710
    grand_total = sum((agg["totalTokens"] or 0) for agg in both.values())
    assert grand_total == 9710  # not 110 + 9500 + 100 + 9600 ...


def test_a_session_that_never_delegates_is_unchanged(tmp_path):
    db, s = _ledger(tmp_path)
    agg = UsageAggregator(db).aggregate_by_session([s["delta"]])
    assert agg[s["delta"]]["totalTokens"] == 50
    assert agg[s["delta"]]["turnsReported"] == 1
