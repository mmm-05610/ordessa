"""Work Order 134: the truncation consumer side (122's returned residual).

Two things must hold, and both are driven here:

* the extraction reads a machine-readable stop reason ONLY when the harness
  result actually carries one - absent / clean end_turn / malformed => None, so
  a normal turn behaves byte-identically to before (we never invent a reason);
* when there IS a non-clean reason, `complete_turn` persists it into
  `server_turns.terminal_reason`, which the wire projection already exposes as
  `reason` - so truncation becomes visible on the leg users read.

The Worker still has to EMIT `stopReason` (a separate, approval-gated protocol
change); this order is only the safe consumer that turns it on when it arrives.
"""
from __future__ import annotations

from ordessa_server_compat.execution.sidecar_backend import _terminal_reason_from_result
from ordessa_server_compat.wire_projection import execution_state
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.sessions import SessionRecords
from pacthold_runtime_compat.storage import Database


# ---------------------------------------------------------------- extraction (pure)

def test_absent_or_clean_stop_reason_is_none():
    assert _terminal_reason_from_result(None) is None
    assert _terminal_reason_from_result({}) is None                     # field absent
    assert _terminal_reason_from_result({"stopReason": "end_turn"}) is None
    assert _terminal_reason_from_result("not a dict") is None


def test_non_clean_stop_reason_is_surfaced():
    assert _terminal_reason_from_result({"stopReason": "max_tokens"}) == "max_tokens"
    assert _terminal_reason_from_result({"stopReason": "refusal"}) == "refusal"
    assert _terminal_reason_from_result({"stopReason": "stop"}) == "stop"
    assert _terminal_reason_from_result({"stop_reason": "max_turn_requests"}) == "max_turn_requests"


# ---------------------------------------------------------------- write leg (repo)

def _seed(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    database = Database(root / "db.sqlite3")
    database.initialize()
    # Seed the FK chain (profile -> workspace -> session -> running turn) so the
    # real complete_turn path runs; it only UPDATEs, so FK stays satisfied.
    with database.transaction() as conn:
        conn.execute("INSERT INTO server_profiles(id,name,harness_type,version,"
                     "config_revision,native_generation,config_object_digest,run_state,"
                     "recovery_pending,created_at,updated_at) "
                     "VALUES ('p1','n','codex',1,1,0,'cf','idle',0,'t','t')")
        conn.execute("INSERT INTO server_workspaces(id,connection_id,distribution,"
                     "remote_path,connection_state,version,env_kind,created_at,updated_at) "
                     "VALUES ('ws1','c1','local','/x','ok',1,'wsl','t','t')")
        conn.execute("INSERT INTO server_sessions(id,workspace_id,profile_id,status,"
                     "pinned,version,created_at,updated_at) VALUES ('s1','ws1','p1','ready',0,1,'t','t')")
        conn.execute("INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
                     "native_generation,state,capture_state,cleanup_state,input_object_digest,"
                     "created_at,updated_at) VALUES "
                     "('t1','s1','p1',1,0,'running','not_started','not_started','sha256:in','t','t')")
    return SessionRecords(database, IdempotentRecords(database)), database


def _terminal(database, turn_id):
    with database.read() as conn:
        return conn.execute("SELECT terminal_reason, state FROM server_turns WHERE id=?",
                            (turn_id,)).fetchone()


def test_complete_turn_persists_a_non_clean_reason(tmp_path):
    records, database = _seed(tmp_path)
    records.complete_turn("t1", checkpoint_object_digest="cp", checkpoint_native_id="n",
                          result_object_digest="res", terminal_reason="max_tokens")
    row = _terminal(database, "t1")
    assert row["state"] == "completed"
    assert row["terminal_reason"] == "max_tokens"      # 134: reason reaches the leg


def test_complete_turn_without_reason_leaves_it_null(tmp_path):
    # Absent stop reason -> terminal_reason stays NULL, exactly as before 134.
    records, database = _seed(tmp_path)
    records.complete_turn("t1", checkpoint_object_digest="cp", checkpoint_native_id="n",
                          result_object_digest="res")
    assert _terminal(database, "t1")["terminal_reason"] is None


# ------------------------------------------- the wire reason (LNX-002)

# I's `control/LNX-003-review.md` item 2 asked for this channel (ACP result -> JS
# pass-through -> the Python dual-spelling read) to be verified on the **wire**
# half as well. The docstring above claims the projection "already exposes [it]
# as `reason`" and nothing drove that claim. These cases close the loop from the
# persisted row through the projection, and they add assertions only: they reuse
# `_seed` / `_terminal` and change no shared fixture, so no other case's meaning
# moves. Scope (item 5): this verifies the *consumer* on the local leg. It does
# not claim real-harness truncation is solved, and an undeclared remote-Worker
# schema is not evidence that this local channel cannot carry the reason.

def test_the_persisted_max_tokens_reason_reaches_the_wire_projection(tmp_path):
    """DB -> projection, end to end: `terminal_reason` becomes the wire `reason`."""
    records, database = _seed(tmp_path)
    records.complete_turn("t1", checkpoint_object_digest="cp", checkpoint_native_id="n",
                          result_object_digest="res", terminal_reason="max_tokens")
    row = _terminal(database, "t1")
    assert row["terminal_reason"] == "max_tokens"        # persisted (134)

    body = execution_state(dict(row))
    assert body["state"] == "completed"
    assert body["reason"] == "max_tokens"                # and visible to the leg


def test_the_end_turn_control_carries_no_reason_on_the_wire(tmp_path):
    """The `end_turn` control, kept at the wire layer: a clean turn claims nothing.

    Without this half, "the reason is exposed" would also be satisfied by a
    projection that invented one for every turn.
    """
    records, database = _seed(tmp_path)
    records.complete_turn("t1", checkpoint_object_digest="cp", checkpoint_native_id="n",
                          result_object_digest="res")
    row = _terminal(database, "t1")

    assert row["terminal_reason"] is None
    assert "reason" not in execution_state(dict(row))


def test_a_cancelled_turn_keeps_its_projected_state_and_gains_no_reason(tmp_path):
    """The existing cancel behaviour, preserved at the projection layer.

    `cancelled` projects as `stopped` - the contract's word - and the truncation
    channel adds no key to it, so switching truncation on cannot retell a user's
    stop as a truncation.
    """
    records, database = _seed(tmp_path)
    records.complete_turn("t1", checkpoint_object_digest="cp", checkpoint_native_id="n",
                          result_object_digest="res")
    with database.transaction() as conn:
        conn.execute("UPDATE server_turns SET state='cancelled' WHERE id='t1'")

    body = execution_state(dict(_terminal(database, "t1")))
    assert body["state"] == "stopped"
    assert "reason" not in body


# ---------------- the ACP prompt leg, end to end (LNX-002 ruling, decision 2)

# The earlier case here pinned "the JS boundary drops the reason" as a
# characterisation. I's ruling refused to settle for that, and the loss is now
# fixed in the vendored bridge (`third_party/harness_remote/bridge/src/acp-service.js`,
# registered as PATCHES.md §4): the turn's own `session/prompt` response is kept
# per generation and handed back by `promptAndWait`. These are the
# target-behaviour regressions that replace it.
#
# Scope, stated plainly: the fake peer is what this seam is exercised with. What
# the *real* harnesses report is still a later verification question, and a
# missing field keeps its absent/unknown meaning here — nothing is invented.

import os  # noqa: E402
import pathlib  # noqa: E402

import pytest  # noqa: E402

from ordessa_server_compat.execution.sidecar import (  # noqa: E402
    LocalProcessLauncher,
    SidecarHarnessPort,
)

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins"  / "harness"
SIDECAR_ENTRY = PLUGIN / "runtime" / "native-driver.mjs"  # worker-entry.mjs 随退役旧链移除
FAKE_PEER = PLUGIN / "tests" / "harness_remote" / "fake_acp_peer.mjs"


def _isolated_environment(tmp_path, stop_reason=None):
    """The minimal child environment the sidecar tests use, plus the knob."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "xdg"),
        "XDG_CACHE_HOME": str(home / "xdg"),
        "XDG_DATA_HOME": str(home / "xdg"),
        "AGENTBOX_SIDECAR_ISOLATED": "1",
    }
    if stop_reason is not None:
        env["AGENTBOX_FIXTURE_STOP_REASON"] = stop_reason
    return env


@pytest.fixture
def fixture_port(tmp_path):
    """A factory for real ports on the real JS entry and the fixture peer."""
    ports = []

    def start(stop_reason=None):
        port = SidecarHarnessPort(
            LocalProcessLauncher(["node", str(SIDECAR_ENTRY)], cwd=str(PLUGIN)),
            environment=_isolated_environment(tmp_path, stop_reason),
            profile="pi",
            adapter={"command": os.environ.get("NODE_BIN", "node"), "args": [str(FAKE_PEER)]},
            state_directory=str(tmp_path / "state"),
            directory=str(tmp_path),
            on_event=lambda *_args: None,
        )
        ports.append(port)
        return port

    try:
        yield start
    finally:
        for port in ports:
            port.stop()


def _persist_and_project(tmp_path, result, *, turn="t1"):
    """Run the real completion path for a result and return the projected body."""
    records, database = _seed(tmp_path)
    records.complete_turn(turn, checkpoint_object_digest="cp", checkpoint_native_id="n",
                          result_object_digest="res",
                          terminal_reason=_terminal_reason_from_result(result))
    return _terminal(database, turn)


@pytest.mark.skipif(not SIDECAR_ENTRY.is_file(), reason="sidecar entry not built")
def test_max_tokens_travels_from_the_acp_peer_to_the_wire_reason(tmp_path, fixture_port):
    """The whole leg I's ruling asked for: ACP fixture -> bridge -> worker-entry ->
    Python completion -> DB -> wire reason."""
    port = fixture_port("max_tokens")
    port.open_execution("execution-1")
    result = port.prompt("execution-1", "component gate")

    # the bridge now hands the turn's own ACP response back, verbatim
    assert result == {"stopReason": "max_tokens"}, result
    assert _terminal_reason_from_result(result) == "max_tokens"

    row = _persist_and_project(tmp_path, result)
    assert row["terminal_reason"] == "max_tokens"
    assert execution_state(dict(row))["reason"] == "max_tokens"


@pytest.mark.skipif(not SIDECAR_ENTRY.is_file(), reason="sidecar entry not built")
def test_end_turn_through_the_same_leg_claims_nothing(tmp_path, fixture_port):
    """The clean control on the same leg: `end_turn` is not a truncation, so
    nothing is persisted and the projection carries no reason key."""
    port = fixture_port(None)  # the peer's own default
    port.open_execution("execution-1")
    result = port.prompt("execution-1", "component gate")

    assert result == {"stopReason": "end_turn"}, result
    assert _terminal_reason_from_result(result) is None

    row = _persist_and_project(tmp_path, result)
    assert row["terminal_reason"] is None
    assert "reason" not in execution_state(dict(row))


@pytest.mark.skipif(not SIDECAR_ENTRY.is_file(), reason="sidecar entry not built")
def test_two_consecutive_turns_each_keep_their_own_reason(tmp_path, fixture_port):
    """Attribution across consecutive turns on one session.

    The knob gives the first turn `max_tokens` and the second `end_turn`. If a
    reason were cached, shared or taken from the wrong generation, the second turn
    would inherit the first one's truncation — this is the case that would catch it.
    """
    port = fixture_port("max_tokens,end_turn")
    port.open_execution("execution-1")

    first = port.prompt("execution-1", "first turn")
    assert first == {"stopReason": "max_tokens"}, first
    second = port.prompt("execution-1", "second turn")
    assert second == {"stopReason": "end_turn"}, second

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir(exist_ok=True)
    second_root.mkdir(exist_ok=True)
    # each seed is its own database, so both use its own `t1`
    first_row = _persist_and_project(first_root, first)
    second_row = _persist_and_project(second_root, second)

    assert execution_state(dict(first_row))["reason"] == "max_tokens"
    assert second_row["terminal_reason"] is None
    assert "reason" not in execution_state(dict(second_row))


def test_the_knob_cannot_move_the_cancel_or_special_paths():
    """The fixture knob's blast radius, asserted against the peer source.

    Only the ordinary completion reads the sequence: the cancel, abort,
    silent-success and permission paths keep their own reasons, so selecting
    `max_tokens` cannot retell a user's stop as a truncation.
    """
    source = FAKE_PEER.read_text(encoding="utf-8")

    assert 'process.env.AGENTBOX_FIXTURE_STOP_REASON || "end_turn"' in source
    assert 'pendingCancel ? "cancelled" : nextStopReason()' in source
    assert source.count('stopReason: "end_turn"') == 4, "a special path moved"
    assert source.count('stopReason: "cancelled"') == 1, "the cancel path moved"
