"""Work Order 146: the delegated child turn must pass the existing chain's gates,
fail with typed results, and read the newest content - all on the real delegation path.

Five reviewer findings, one code region (`delegation.run` / `_create_child_turn` /
`_await_terminal` / roster availability):
* AUD-B-031 - a `recovery_pending` child was delegable though the existing chain refuses it;
* AUD-B-034 - an exclusive-home child could be given two active turns across sessions;
* AUD-B-035 - a same-session `task_id` retry leaked a raw `IntegrityError` (table/column
  names) instead of a product code;
* AUD-B-032 - the roster's `available` was a decorative constant (never fed);
* AUD-B-029 - the child's summary was read from the session snapshot's first 200 rows, so
  long answers were silently truncated and continuations returned "".

Each gate drives the real `DelegationService.run` (or `list_for`); the counterexamples are
verified by reverting the fix (see the order's evidence doc).
"""
from __future__ import annotations

import pytest

from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.errors import ServerError
from ordessa_server_compat.execution import CancelOutcome
from ordessa_server_compat.execution.delegation import DelegationService
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.profiles import ProfileRecords
from ordessa_server_compat.profiles.subagents import DelegationError
from ordessa_server_compat.sessions import SessionRecords, SessionService
from ordessa_workspace import WorkspaceRecords
from pacthold.storage import Database, ObjectStore


class _StallThenActive:
    """accept() leaves the child turn running; cancel() finishes it."""

    def __init__(self, records) -> None:
        self.records = records
        self.accepted: list[str] = []

    def accept(self, turn_id) -> None:
        self.accepted.append(turn_id)
        self.records.set_turn_dispatch(turn_id, work_id="w", execution_id="e",
                                       dispatch_id="d", state="running")

    def cancel(self, turn_id):
        self.records.finish_cancelled(turn_id)
        return True

    def cancel_execution(self, turn_id):
        return (CancelOutcome.CONFIRMED_STOPPED if self.cancel(turn_id)
                else CancelOutcome.REFUSED_NO_ACTIVE_RUN)


def _env(tmp_path, *, home_concurrency=None):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    profiles = ProfileRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    records = SessionRecords(database, idempotency, home_concurrency=home_concurrency or {})
    objects = ObjectStore(tmp_path / "data")
    execution = _StallThenActive(records)
    harnesses = HarnessRegistry()
    harnesses.register(HarnessDescriptor(
        "codex", credential_kind=None,
        configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
        capability_claims={"stream": True},
    ))
    sessions = SessionService(records, idempotency, objects, harnesses=harnesses,
                              profiles=profiles, credentials=None, execution=execution)
    service = DelegationService(records=records, profiles=profiles, sessions=sessions,
                                execution=execution, objects=objects)
    cfg = objects.publish(b'{"schema_version":1,"harness_type":"codex","configuration":{}}').digest

    def profile(name):
        return profiles.create(key=name, request_digest=name, name=name, harness_type="codex",
                               config_digest=cfg, credential_id=None)[1]

    parent = profile("alpha")
    child = profile("beta")
    ws = workspaces.create(key="w", request_digest="w", distribution="Ubuntu",
                           remote_user="t", remote_path="/w", connection_id="w")[1]["workspace_id"]
    parent_session = sessions.create_session("ps", {
        "workspace_id": ws, "profile_id": parent["profile_id"]})[1]
    child_seed = sessions.create_session("child-seed", {
        "workspace_id": ws, "profile_id": child["profile_id"]})[1]
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])
    # a-3 A-family rebuild (C ruling 06:19Z): the live parent Turn arrives via
    # the acceptance route so its frozen effective object carries the
    # permissions section delegation narrows from, as in production.
    _, parent_turn = sessions.create_turn(parent_session["session_id"], "parent-key", {
        "text": "parent task",
        "expected_profile_revision": int(profiles.get(parent["profile_id"])["config_revision"]),
    })
    return dict(database=database, profiles=profiles, records=records, sessions=sessions,
                service=service, execution=execution, parent=parent, child=child, ws=ws,
                parent_turn_id=parent_turn["turn_id"],
                child_seed=child_seed["session_id"])


def _turn_count(db):
    with db.read() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM server_turns").fetchone()[0])


def test_recovery_pending_child_is_refused_and_no_turn_is_created(tmp_path):
    env = _env(tmp_path)
    with env["database"].transaction() as conn:
        conn.execute("UPDATE server_profiles SET recovery_pending=1 WHERE id=?",
                     (env["child"]["profile_id"],))
    before = _turn_count(env["database"])
    with pytest.raises(DelegationError) as refused:
        env["service"].run(parent_turn_id=env["parent_turn_id"],
                           parent_profile_id=env["parent"]["profile_id"],
                           arguments={"subagent": "beta", "description": "do some work",
                                      "prompt": "x", "timeout": 1})
    assert refused.value.code == "SUBAGENT_UNAVAILABLE"
    assert _turn_count(env["database"]) == before  # rejected before any child turn insert


def test_roster_marks_recovery_pending_child_unavailable_with_a_code(tmp_path):
    env = _env(tmp_path)
    with env["database"].transaction() as conn:
        conn.execute("UPDATE server_profiles SET recovery_pending=1 WHERE id=?",
                     (env["child"]["profile_id"],))
    roster = env["service"].list_for(parent_profile_id=env["parent"]["profile_id"])["roster"]
    entry = next(e for e in roster if e["name"] == "beta")
    assert entry["available"] is False
    assert entry["reason"] == "PROFILE_RECOVERY_REQUIRED"   # a type code, not a decorative True


def test_exclusive_home_child_cannot_get_a_second_active_turn(tmp_path):
    # The existing chain declares codex exclusive-home; one active turn already
    # exists for the child, so a delegated run must be refused with the same code
    # the chain uses (AUD-B-034: the delegation path used to skip this gate).
    env = _env(tmp_path, home_concurrency={"codex": "exclusive"})
    with env["database"].transaction() as conn:
        conn.execute(
            "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
            "native_generation,state,capture_state,cleanup_state,input_object_digest,"
            "created_at,updated_at) VALUES ('seed-active',?,?,1,0,'running','pending',"
            "'pending','x','t','t')",
            (env["child_seed"], env["child"]["profile_id"]))
    with pytest.raises(ServerError) as conflict:
        env["service"].run(parent_turn_id=env["parent_turn_id"],
                           parent_profile_id=env["parent"]["profile_id"],
                           arguments={"subagent": "beta", "description": "do some work",
                                      "prompt": "x", "timeout": 1})
    assert conflict.value.code == "TURN_CONCURRENCY_CONFLICT"


def test_same_session_retry_task_id_exits_typed_not_raw_integrity_error(tmp_path):
    # A child session already has an active turn; continuing it with that session's
    # task_id double-inserts on the per-session unique index. The delegation must
    # translate the raw IntegrityError into the product code, not leak table/column
    # names to the exit (AUD-B-035, 65:36 "failure is a typed result").
    env = _env(tmp_path)
    with env["database"].transaction() as conn:
        conn.execute("UPDATE server_sessions SET checkpoint_native_id='native-child' WHERE id=?",
                     (env["child_seed"],))
        conn.execute(
            "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
            "native_generation,state,capture_state,cleanup_state,input_object_digest,"
            "created_at,updated_at) VALUES ('active-child',?,?,1,0,'running','pending',"
            "'pending','x','t','t')",
            (env["child_seed"], env["child"]["profile_id"]))
    with pytest.raises(ServerError) as conflict:
        env["service"].run(parent_turn_id=env["parent_turn_id"],
                           parent_profile_id=env["parent"]["profile_id"],
                           arguments={"subagent": "beta", "description": "do some work",
                                      "prompt": "y", "task_id": "native-child"})
    assert conflict.value.code == "TURN_CONCURRENCY_CONFLICT"
    assert "server_" not in conflict.value.message   # no table/column leaked to the exit


class _CompletesWithDeltas:
    """accept() answers the child turn outright: it streams `count` deltas and
    completes, which is what a real execution port does before `run` reads the
    summary back."""

    def __init__(self, records, *, count: int, text: str, native_id: str) -> None:
        self.records = records
        self.count = count
        self.text = text
        self.native_id = native_id
        self.completed: list[str] = []

    def accept(self, turn_id) -> None:
        self.records.set_turn_dispatch(turn_id, work_id="w", execution_id="e",
                                       dispatch_id="d", state="running")
        for _ in range(self.count):
            self.records.append_turn_event(turn_id, "message.delta", {"text": self.text})
        self.records.complete_turn(
            turn_id, checkpoint_object_digest="x", checkpoint_native_id=self.native_id,
            result_object_digest="r")
        self.completed.append(turn_id)

    def cancel(self, turn_id):
        return True

    def cancel_execution(self, turn_id):
        return (CancelOutcome.CONFIRMED_STOPPED if self.cancel(turn_id)
                else CancelOutcome.REFUSED_NO_ACTIVE_RUN)


def _delta_env(tmp_path, *, count: int, text: str, native_id: str):
    env = _env(tmp_path)
    env["service"].execution = _CompletesWithDeltas(
        env["records"], count=count, text=text, native_id=native_id)
    return env


def test_continuation_summary_is_the_new_turns_text_not_empty(tmp_path):
    # AUD-B-029, gates G4/G5 on the real path: after a long first child turn the
    # session snapshot holds more events than its window. A `task_id` continuation
    # must return *this* turn's answer - the old read returned "" silently.
    env = _delta_env(tmp_path, count=260, text="a", native_id="native-kid")
    first = env["service"].run(
        parent_turn_id=env["parent_turn_id"], parent_profile_id=env["parent"]["profile_id"],
        arguments={"subagent": "beta", "description": "first the work", "prompt": "x",
                   "timeout": 5})
    assert first["summary"] == "a" * 260          # complete, not silently head-cut
    assert first["state"] == "completed"

    second = env["service"].run(
        parent_turn_id=env["parent_turn_id"], parent_profile_id=env["parent"]["profile_id"],
        arguments={"subagent": "beta", "description": "continue the work", "prompt": "y",
                   "task_id": first["task_id"], "timeout": 5})
    assert second["resumed"] is True
    assert second["summary"] == "a" * 260         # was "" before 146 (oldest-window read)
    assert second["sessionId"] == first["sessionId"]


def test_over_window_summary_is_marked_never_silent(tmp_path):
    # The contract's bound is MAX_SUMMARY_CHARS on the *summary*; exceeding it must
    # carry the declared marker instead of dropping the tail without a word.
    from ordessa_server_compat.execution.delegation import MAX_SUMMARY_CHARS
    env = _delta_env(tmp_path, count=400, text="z" * 40, native_id="native-long")
    result = env["service"].run(
        parent_turn_id=env["parent_turn_id"], parent_profile_id=env["parent"]["profile_id"],
        arguments={"subagent": "beta", "description": "answer very long", "prompt": "x",
                   "timeout": 5})
    assert len(result["summary"]) == MAX_SUMMARY_CHARS + 1
    assert result["summary"].endswith("…")


def test_get_session_window_is_documented_as_oldest_snapshot(tmp_path):
    # G6: the snapshot's lists are an *oldest-N head*, and the code says so, so the
    # next consumer cannot mistake it for the whole session again.
    env = _delta_env(tmp_path, count=3, text="q", native_id="native-doc")
    with env["database"].transaction() as conn:
        conn.execute(
            "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
            "native_generation,state,capture_state,cleanup_state,input_object_digest,"
            "created_at,updated_at) VALUES ('doc-turn',?,?,1,0,'running','pending',"
            "'pending','x','t','t')",
            (env["child_seed"], env["child"]["profile_id"]))
    for _ in range(300):
        env["records"].append_turn_event("doc-turn", "message.delta", {"text": "w"})
    doc = env["records"].get_session.__doc__ or ""
    assert "oldest" in doc.lower() and "not the whole" in doc.lower()
    snapshot = env["records"].get_session(env["child_seed"], event_limit=200)
    assert len(snapshot["events"]) == 200
    assert [event["seq"] for event in snapshot["events"]] == list(range(1, 201))


def test_turn_message_deltas_reads_all_of_the_turns_events(tmp_path):
    # AUD-B-029: the summary is read from the turn's OWN events (unbounded by the
    # session snapshot's 200-row window). A turn with 300 deltas yields 300 pieces.
    env = _env(tmp_path)
    records = env["records"]
    with env["database"].transaction() as conn:
        conn.execute(
            "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
            "native_generation,state,capture_state,cleanup_state,input_object_digest,"
            "created_at,updated_at) VALUES ('big-turn',?,?,1,0,'running','pending',"
            "'pending','x','t','t')",
            (env["child_seed"], env["child"]["profile_id"]))
    for _ in range(300):
        records.append_turn_event("big-turn", "message.delta", {"text": "x" * 40})
    pieces = records.turn_message_deltas("big-turn")
    assert len(pieces) == 300
    assert "".join(pieces) == "x" * 40 * 300
    # And other turns' deltas never leak into this turn's read.
    assert records.turn_message_deltas("does-not-exist") == []
