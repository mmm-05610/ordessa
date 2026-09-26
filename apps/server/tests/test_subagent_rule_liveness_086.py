"""Order 086 stage 3: are 65's four rules **live**, or only written down?

Order 65 states four rules in its own module docstrings - usage attribution, the
bounded summary, the approval mirror and cancellation that propagates - plus a
cycle refusal that R-0016 keeps while revoking the depth ceiling. Every one of
them has a unit test. This file asks the different question: does the rule fire
when the act comes through the **entry point the product uses**, with the child
turn as the ledger really records it?

That distinction already cost two orders here: 099 (a `home.put` implementation
no dispatch arm ever routed) and 103 (the same shape across the 64 wire
methods). Two of the checks below were exactly that - the cancellation cascade
and the cycle refusal - and both are red at the commit that first wrote them
(`3d19218`); each one names the entry point it was driven from, so the claim can
be re-checked.

Counterexamples are inside the assertions, not implied: the usage check completes
the parent with its own numbers so a copy-onto-parent implementation would show
up as 14/9 instead of 3/2, and the summary check runs both sides of the bound.
"""
from __future__ import annotations

import pytest

from ordessa_server.errors import ServerError
from ordessa_server_compat.execution import CancelOutcome
from ordessa_server_compat.execution.delegation import (
    MAX_SUMMARY_CHARS,
    DelegationError,
    DelegationService,
)

from test_delegation import FakeExecution, _setup


def _delegating_parent(tmp_path, *, grandchild: bool = False):
    """alpha -> beta (and beta -> gamma), with a parent turn in the ledger."""
    (database, profiles, records, sessions, execution, service, parent, child,
     other, parent_turn_id) = _setup(tmp_path)
    # The shared fixture's fake port completes what it accepts; these tests
    # observe a LIVE parent mid-flight (stops, late completions, usage of
    # their own), so the parent row is set back to running here - the frozen
    # effective object from the acceptance route stays, which is what the
    # narrowed posture reads.
    with records.database.transaction() as conn:
        conn.execute(
            "UPDATE server_turns SET state='running', result_object_digest=NULL,"
            "usage_input_tokens=NULL, usage_output_tokens=NULL,"
            "usage_total_tokens=NULL, usage_source=NULL WHERE id=?",
            (parent_turn_id,))
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])
    if grandchild:
        profiles.grant_subagent(parent_id=child["profile_id"], child_id=other["profile_id"])
    return dict(database=database, profiles=profiles, records=records, sessions=sessions,
                execution=execution, service=service, parent=parent, child=child,
                other=other, parent_turn_id=parent_turn_id)


def _start_a_running_child(env, *, turn_id: str = "kid-turn") -> str:
    """Put a live child turn in the ledger, linked to `parent-turn`.

    Order 141 made the delegation *time-out* itself a stop path (it now cancels the
    child), so `run(timeout=1)` can no longer be used to obtain a child that is still
    running. These two tests are about the two *stop* doors reaching a live child - a
    rule 141 must not regress - so the running child is created directly here instead.
    """
    records, child = env["records"], env["child"]
    with records.database.transaction() as conn:
        session_row = conn.execute(
            "SELECT id FROM server_sessions WHERE profile_id=? ORDER BY rowid LIMIT 1",
            (child["profile_id"],),
        ).fetchone()
        conn.execute(
            "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
            "native_generation,state,capture_state,cleanup_state,input_object_digest,"
            "parent_turn_id,created_at,updated_at) "
            "VALUES (?,?,?,1,0,'running','pending','pending','x',?,'t','t')",
            (turn_id, str(session_row["id"]), child["profile_id"], env["parent_turn_id"]),
        )
    return turn_id


class _NeverFinishes(FakeExecution):
    """A child turn that is still running when its parent is stopped.

    `cancel` answers the way a real stop does: the process is gone, so the turn
    reaches its terminal state.
    """

    def __init__(self, records) -> None:
        super().__init__(records)
        self.cancelled: list[str] = []

    def accept(self, turn_id: str) -> None:
        self.accepted.append(turn_id)
        self.records.set_turn_dispatch(turn_id, work_id="w", execution_id="e",
                                       dispatch_id="d", state="running")

    def cancel(self, turn_id: str) -> bool:
        self.cancelled.append(turn_id)
        self.records.finish_cancelled(turn_id)
        return True

    def cancel_execution(self, turn_id: str):
        return (CancelOutcome.CONFIRMED_STOPPED if self.cancel(turn_id)
                else CancelOutcome.REFUSED_NO_ACTIVE_RUN)


def test_the_child_s_usage_stays_on_its_own_turn_and_reaches_the_parent_as_a_fact(tmp_path):
    """归属: the link is the attribution; nothing is copied between turns."""
    env = _delegating_parent(tmp_path)
    service, records, parent = env["service"], env["records"], env["parent"]

    result = service.run(parent_turn_id=env["parent_turn_id"],
                         parent_profile_id=parent["profile_id"],
                         arguments={"subagent": "beta", "description": "do some work",
                                    "prompt": "x"})
    # The parent then finishes with usage of its own - smaller than the child's,
    # so a roll-up that wrote the child's numbers onto the parent is visible.
    records.complete_turn(env["parent_turn_id"], checkpoint_object_digest="sha256:p",
                          checkpoint_native_id="native-parent", result_object_digest="sha256:pr",
                          usage={"inputTokens": 3, "outputTokens": 2, "totalTokens": 5},
                          usage_source="fake-parent")

    with env["database"].read() as conn:
        rows = {row["id"]: dict(row) for row in conn.execute(
            "SELECT id, profile_id, parent_turn_id, usage_input_tokens, usage_output_tokens, "
            "usage_total_tokens, usage_source FROM server_turns "
            "WHERE id IN (:p, :c)", {"p": env["parent_turn_id"],
                                     "c": result["turnId"]})}
    child_row = rows[result["turnId"]]

    assert child_row["parent_turn_id"] == env["parent_turn_id"], child_row
    assert child_row["profile_id"] == env["child"]["profile_id"], (
        "the delegated turn ran under the wrong Profile")
    assert (child_row["usage_input_tokens"], child_row["usage_output_tokens"],
            child_row["usage_total_tokens"]) == (11, 7, 18), child_row
    # The counterexample: a copy-onto-parent roll-up would read 14/9/23 here.
    parent_row = rows[env["parent_turn_id"]]
    assert (parent_row["usage_input_tokens"], parent_row["usage_output_tokens"],
            parent_row["usage_total_tokens"]) == (3, 2, 5), parent_row
    # The parent still learns the child's cost, as a fact in the result it asked for.
    assert result["usage"] == {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18,
                               "usageSource": "fake"}, result["usage"]


def test_the_summary_is_the_child_s_final_message_bounded_not_its_transcript(tmp_path):
    """摘要: the bound is on the returned text, and inside it nothing is invented."""
    env = _delegating_parent(tmp_path)
    records = env["records"]

    class _LongSummary(FakeExecution):
        def accept(self, turn_id: str) -> None:
            self.accepted.append(turn_id)
            records.set_turn_dispatch(turn_id, work_id="w", execution_id="e", dispatch_id="d",
                                      state="running")
            records.append_turn_event(turn_id, "message.delta",
                                      {"text": "x" * (MAX_SUMMARY_CHARS + 900)})
            records.complete_turn(
                turn_id, checkpoint_object_digest="sha256:a",
                checkpoint_native_id=f"native-{turn_id}", result_object_digest="sha256:r",
                usage={"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                usage_source="fake")

    env["service"].execution = _LongSummary(records)
    wide = env["service"].run(parent_turn_id=env["parent_turn_id"],
                              parent_profile_id=env["parent"]["profile_id"],
                              arguments={"subagent": "beta", "description": "do some work",
                                         "prompt": "x"})
    assert len(wide["summary"]) == MAX_SUMMARY_CHARS + 1, len(wide["summary"])
    assert wide["summary"].startswith("x" * 100) and wide["summary"].endswith("…"), (
        "the bound must cut the child's own text, not replace it with a placeholder")

    # Inside the bound the summary is verbatim: a truncator that mangled short
    # answers would fail here, not on the long side alone.
    narrow = _delegating_parent(tmp_path / "narrow")
    short = narrow["service"].run(parent_turn_id=narrow["parent_turn_id"],
                                 parent_profile_id=narrow["parent"]["profile_id"],
                                 arguments={"subagent": "beta", "description": "do some work",
                                            "prompt": "x"})
    assert short["summary"] == f"summary of {short['turnId']}", short["summary"]


def test_cancelling_the_parent_reaches_the_child_turn_that_is_still_running(tmp_path):
    """取消: 65 promises propagation; this drives the real cancel entry point."""
    env = _delegating_parent(tmp_path)
    service, records, sessions, parent = (
        env["service"], env["records"], env["sessions"], env["parent"])

    stalled = _NeverFinishes(records)
    service.execution = stalled
    sessions.execution = stalled
    # A live child turn (order 141 made the delegation time-out itself a stop path,
    # so the running child is placed in the ledger directly rather than via a timeout).
    _start_a_running_child(env)
    with records.database.read() as conn:
        kids = [str(row["id"]) for row in conn.execute(
            "SELECT id FROM server_turns WHERE parent_turn_id=?",
            (env["parent_turn_id"],)).fetchall()]
    assert kids, "the ledger has a live child turn to stop"
    assert records.get_turn_context(kids[0])["state"] == "running"

    sessions.cancel_turn(env["parent_turn_id"], "cancel-parent-1")

    states = {kid: records.get_turn_context(kid)["state"] for kid in kids}
    assert states == {kids[0]: "cancelled"}, (
        f"cancelling the parent left the child running: {states} - the ledger says "
        "the parent is cancelled and nothing asks the child to stop")
    assert kids[0] in stalled.cancelled, (
        "the child must be stopped through the execution port, not only in the ledger")


def test_the_wire_stop_applies_the_same_rule(tmp_path):
    """两个入口: the desktop stops with `runs.stop`, not with the REST cancel.

    `WireService.runs_stop` is bound to this env's own sessions and execution
    (the same borrowing `test_delegation.py` uses for `_native_event`), so the
    second door is the real one. A rule wired at one door only is how 103's
    finding stays found.
    """
    from ordessa_server_compat.core_wire import CoreWireHandlers

    env = _delegating_parent(tmp_path / "wire")
    service, records, sessions, parent = (
        env["service"], env["records"], env["sessions"], env["parent"])
    stalled = _NeverFinishes(records)
    service.execution = stalled
    sessions.execution = stalled
    _start_a_running_child(env)   # see 141 note in the sibling test above
    with records.database.read() as conn:
        kids = [str(row["id"]) for row in conn.execute(
            "SELECT id FROM server_turns WHERE parent_turn_id=?",
            (env["parent_turn_id"],)).fetchall()]
    assert kids and records.get_turn_context(kids[0])["state"] == "running"

    from types import SimpleNamespace

    outcome = CoreWireHandlers.runs_stop(
        SimpleNamespace(sessions=sessions, execution=stalled), {
            "requestId": "stop-1",
            "sessionId": records.get_turn_context(env["parent_turn_id"])["session_id"],
            "executionId": env["parent_turn_id"],
        })
    assert outcome["outcome"] == "stop_requested", outcome
    assert kids[0] in stalled.cancelled, (
        f"`runs.stop` stopped the parent only: {stalled.cancelled}")
    assert records.get_turn_context(kids[0])["state"] == "cancelled"


def test_a_three_edge_ring_closes_on_its_third_hop_and_is_refused(tmp_path):
    """环 (kept by R-0016): the ancestry is the ledger's, not the caller's to state.

    The grant layer only rejects the **direct** reverse edge, so A→B, B→C, C→A
    is representable and the delegation graph is not a DAG. That makes the
    runtime cycle rule the one that has to hold - and it can only hold if the
    chain is read back out of the ledger, because the bridge arrives with no
    ancestry to declare. The ring closes on the third hop: alpha is already
    waiting in it, so gamma's call back to alpha is a role waiting on itself.
    """
    env = _delegating_parent(tmp_path)
    service, profiles, records = env["service"], env["profiles"], env["records"]
    profiles.grant_subagent(parent_id=env["child"]["profile_id"],
                            child_id=env["other"]["profile_id"])
    profiles.grant_subagent(parent_id=env["other"]["profile_id"],
                            child_id=env["parent"]["profile_id"])

    first = service.run(parent_turn_id=env["parent_turn_id"],
                        parent_profile_id=env["parent"]["profile_id"],
                        arguments={"subagent": "beta", "description": "do some work",
                                   "prompt": "x"})
    second = service.run(parent_turn_id=first["turnId"],
                         parent_profile_id=env["child"]["profile_id"],
                         arguments={"subagent": "gamma", "description": "pass it on",
                                    "prompt": "x"})
    # Written exactly as the loopback endpoint writes it: no ancestry handed in.
    with pytest.raises(DelegationError) as cycle:
        service.run(parent_turn_id=second["turnId"],
                    parent_profile_id=env["other"]["profile_id"],
                    arguments={"subagent": "alpha", "description": "and back again",
                               "prompt": "x"})
    assert cycle.value.code == "SUBAGENT_CYCLE", cycle.value.code
    with records.database.read() as conn:
        closed = conn.execute(
            "SELECT count(*) FROM server_turns WHERE parent_turn_id=?",
            (second["turnId"],)).fetchone()[0]
    assert closed == 0, "the refused hop must not create a turn"
    # The grant layer's own refusal stays where it is: a two-edge cycle never
    # becomes representable in the first place.
    with pytest.raises(ServerError) as direct:
        profiles.grant_subagent(parent_id=env["child"]["profile_id"],
                                child_id=env["parent"]["profile_id"])
    assert direct.value.code == "SUBAGENT_CYCLE"


def test_a_grandchild_delegation_is_allowed_now_that_depth_is_not_a_ceiling(tmp_path):
    """R-0016: the ceiling is revoked; only a repeated Profile is refused.

    The revoked rule is exactly what this test contradicts: under 65's ceiling a
    chain this long was refused before anyone could repeat themselves, which is
    why the ring test above was unreachable in the first place. Read the two as
    a pair - one pins the rule R-0016 keeps, this one pins the rule it revokes.
    """
    env = _delegating_parent(tmp_path / "deep", grandchild=True)
    service, profiles, records = env["service"], env["profiles"], env["records"]
    digest = service.objects.publish(
        b'{"schema_version":1,"harness_type":"codex","configuration":{}}').digest
    fourth = profiles.create(key="d4", request_digest="d4", name="delta",
                             harness_type="codex", config_digest=digest,
                             credential_id=None)[1]
    sessions = env["sessions"]
    # The fourth Profile needs a workspace to run in, exactly like the others.
    sessions.create_session("seed-delta", {
        "workspace_id": env["records"].get_turn_context(env["parent_turn_id"])["workspace_id"],
        "profile_id": fourth["profile_id"]})
    profiles.grant_subagent(parent_id=env["other"]["profile_id"], child_id=fourth["profile_id"])

    hop = service.run(parent_turn_id=env["parent_turn_id"],
                      parent_profile_id=env["parent"]["profile_id"],
                      arguments={"subagent": "beta", "description": "do some work",
                                 "prompt": "x"})
    second = service.run(parent_turn_id=hop["turnId"],
                         parent_profile_id=env["child"]["profile_id"],
                         arguments={"subagent": "gamma", "description": "go one deeper",
                                    "prompt": "x"})
    third = service.run(parent_turn_id=second["turnId"],
                        parent_profile_id=env["other"]["profile_id"],
                        arguments={"subagent": "delta", "description": "and once more",
                                   "prompt": "x"})
    assert third["state"] == "completed", third
    chain, current = [], third["turnId"]
    with records.database.read() as conn:
        while current is not None:
            row = conn.execute("SELECT profile_id, parent_turn_id FROM server_turns WHERE id=?",
                               (current,)).fetchone()
            chain.insert(0, str(row["profile_id"]))
            current = row["parent_turn_id"]
    assert chain == [env["parent"]["profile_id"], env["child"]["profile_id"],
                     env["other"]["profile_id"], fourth["profile_id"]], chain
    del service, profiles, records


def test_the_bridge_endpoint_hands_run_the_same_call_this_file_drives(tmp_path):
    """The checks above must describe the production call, not a kinder one.

    Read from the source: the endpoint's `run` passes no ancestry, which is why
    the cycle check has to derive it. If someone starts passing a chain here,
    this assertion goes red and the derivation above gets a second look.
    """
    import pathlib
    import re

    source = (pathlib.Path(__file__).resolve().parents[3]
              / "plugins" / "server-compat" / "src" / "ordessa_server_compat" / "http.py")
    body = source.read_text(encoding="utf-8")
    call = re.search(r"payload = delegation_service\.run\((.*?)\n\s*\)", body, re.S)
    assert call, "the delegation endpoint's run call moved; re-read it before trusting the gates"
    assert "chain" not in call.group(1), call.group(1)
    assert "parent_turn_id=grant[\"turnId\"]" in call.group(1), call.group(1)


def test_a_service_without_a_derived_chain_refuses_nothing(tmp_path):
    """The shape that keeps this honest: `run` has no chain parameter to trust.

    A caller-provided ancestry would make the gate pass in a test and stay shut
    in production, which is the defect this stage found.
    """
    import inspect

    parameters = inspect.signature(DelegationService.run).parameters
    assert "chain" not in parameters, (
        f"`run` takes {list(parameters)} - ancestry supplied by the caller is not ancestry")
