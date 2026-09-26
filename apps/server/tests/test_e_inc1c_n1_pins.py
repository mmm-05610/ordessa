"""INC1c c-3 (E leg) — the delegation entry's N1 interleave locks.

Approved per-path in `approvals/INC1c-release.md` (c-3) under the B案 ruling
裁①: the delegated child turn's frozen effective object is still minted at the
delegation creation point, but the creation is now anchored the same way the
Session leg anchors - out-of-transaction assembly, in-transaction
`config_revision` re-check (red/green-bidirectional), and a live-row edit that
lands between creation and acceptance can never move what the child turn is
bound to (β2's raw-key acceptance semantics, pinned for the second entry of
the one object family).

Red sides (β2 23:12Z methodology, throwaway plain-clone sims):
* window 1 is RED on a pristine `57e91ec` tree: without the anchor the stale
  snapshot is accepted silently (no 409).
* window 2 is RED under a one-shot sim patch that reintroduces a COALESCE'd
  live-row pickup at acceptance (pre-β2 semantics); green verbatim here.

Run (from `source/`):
    PYTHONPATH=src:$(ls -d plugins/*/src | paste -sd:) \
    ../tmp/venv/bin/python -m pytest tests/server/test_e_inc1c_n1_pins.py -q
"""
from __future__ import annotations

import json

import pytest

from ordessa_server.errors import ServerError
from ordessa_server.execution.delegation import DelegationService
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.profiles import ProfileRecords
from ordessa_server_compat.sessions import SessionRecords, SessionService
from ordessa_server.workspaces import WorkspaceRecords
from pacthold.storage import Database, ObjectStore


class _WindowExecution:
    """Execution port standing in for the acceptance leg: it opens the race
    window strictly between the child turn's creation and its acceptance,
    then records what the acceptance would bind."""

    def __init__(self, records, *, in_window_edit=None) -> None:
        self.records = records
        self.in_window_edit = in_window_edit
        self.bound_effective: dict[str, str | None] = {}

    def accept(self, turn_id: str) -> None:
        if self.in_window_edit is not None:
            self.in_window_edit()
        context = self.records.get_turn_context(turn_id)
        self.bound_effective[turn_id] = context["effective_config_object_digest"]
        self.records.set_turn_dispatch(
            turn_id, work_id="w", execution_id="e", dispatch_id="d", state="running")
        self.records.append_turn_event(turn_id, "message.delta", {"text": "s"})
        self.records.complete_turn(
            turn_id, checkpoint_object_digest="sha256:a", checkpoint_native_id=f"n-{turn_id}",
            result_object_digest="sha256:r",
            usage={"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            usage_source="fake")

    # the roster/tool path never needs these for the pins below
    def submit(self, request):  # pragma: no cover
        raise AssertionError("unused in pins")


def _pieces(tmp_path, *, in_window_edit=None):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    profiles = ProfileRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    records = SessionRecords(database, idempotency)
    objects = ObjectStore(tmp_path / "data")
    execution = _WindowExecution(records, in_window_edit=in_window_edit)
    sessions = SessionService(records, idempotency, objects, harnesses=None,
                              profiles=profiles, credentials=None, execution=execution)
    service = DelegationService(records=records, profiles=profiles, sessions=sessions,
                                execution=execution, objects=objects)

    def config_for(model: str) -> str:
        return objects.publish(json.dumps(
            {"schema_version": 1, "harness_type": "codex",
             "configuration": {"model": model}}).encode()).digest

    v1 = config_for("creation-time")
    parent = profiles.create(key="p", request_digest="p", name="alpha", harness_type="codex",
                             config_digest=v1, credential_id=None)[1]
    child = profiles.create(key="c", request_digest="c", name="beta", harness_type="codex",
                            config_digest=v1, credential_id=None)[1]
    workspace = workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/workspace", connection_id="c")[1]
    session_row = sessions.create_session("seed-child", {
        "workspace_id": workspace["workspace_id"],
        "profile_id": child["profile_id"]})[1]
    return database, profiles, records, objects, execution, service, child, session_row


def _edit_live_profile_row(database, objects, profile_id: str, model: str) -> None:
    """A committed live-row edit - new configuration object AND a bumped
    `config_revision`, exactly what a profile update lands (β2 D2 W1-W3)."""
    digest = objects.publish(json.dumps(
        {"schema_version": 1, "harness_type": "codex",
         "configuration": {"model": model}}).encode()).digest
    with database.transaction() as conn:
        conn.execute(
            "UPDATE server_profiles SET config_object_digest=?, config_revision=config_revision+1 "
            "WHERE id=?", (digest, profile_id))


# --------------------------------------------------------------------------
# window 1 — the anchor has teeth: a stale creation snapshot is refused.

def test_creation_is_refused_when_the_live_row_moved_after_the_out_of_tx_assembly(tmp_path):
    (_db, profiles, records, objects, _exec, service, child, session_row) = _pieces(tmp_path)
    stale = profiles.get(child["profile_id"])          # the row as the assembly read it
    _edit_live_profile_row(_db, objects, child["profile_id"], "moved before INSERT")

    with pytest.raises(ServerError) as refused:
        service._create_child_turn(
            session_id=session_row["session_id"], child_profile=stale,
            parent_turn_id="parent-turn", prompt="go", model=None, posture=None)
    assert refused.value.code == "PROFILE_REVISION_CONFLICT"
    assert refused.value.status == 409
    # nothing bound to the stale assembly was written through the anchor
    with _db.read() as conn:
        assert conn.execute(
            "SELECT 1 FROM server_turns WHERE profile_id=?", (child["profile_id"],),
        ).fetchone() is None


def test_undrifted_creation_freezes_the_effective_object_and_binds_it(tmp_path):
    (_db, profiles, records, objects, _exec, service, child, session_row) = _pieces(tmp_path)
    fresh = profiles.get(child["profile_id"])
    turn_id = service._create_child_turn(
        session_id=session_row["session_id"], child_profile=fresh,
        parent_turn_id="parent-turn", prompt="go", model=None, posture=None)
    context = records.get_turn_context(turn_id)
    frozen_digest = context["effective_config_object_digest"]
    assert frozen_digest, "the delegated leg must never write a NULL frozen digest here"
    value = json.loads(objects.read(frozen_digest))
    assert value["harness_type"] == "codex"
    assert value["configuration"] == {"model": "creation-time"}


# --------------------------------------------------------------------------
# window 2 — creation→accept interleave: the binding stays the frozen object.

def test_N1_live_edit_between_delegated_creation_and_accept_never_moves_the_binding(tmp_path):
    (_db, profiles, records, objects, _exec, service, child, session_row) = _pieces(tmp_path,
                                                                                       in_window_edit=lambda: None)
    fresh = profiles.get(child["profile_id"])
    turn_id = service._create_child_turn(
        session_id=session_row["session_id"], child_profile=fresh,
        parent_turn_id="parent-turn", prompt="go", model=None, posture=None)
    frozen = records.get_turn_context(turn_id)["effective_config_object_digest"]

    # force the edit into the open window: strictly after creation, strictly
    # before the acceptance leg reads anything.
    execution = _exec
    execution.in_window_edit = lambda: _edit_live_profile_row(
        _db, objects, child["profile_id"], "mid-window edit")
    execution.accept(turn_id)
    assert execution.bound_effective[turn_id] == frozen, (
        "the delegation entry bound the mid-window live edit instead of the "
        "creation-point frozen object (COALESCE'd pickup is forbidden since β2)")


# --------------------------------------------------------------------------
# B案 zero-external-change byte pin (裁①/验收点2): the anchor must not move bytes.

def test_anchor_changes_nothing_about_the_minted_object_bytes(tmp_path):
    digests = []
    for round_id in range(2):
        (_db, profiles, records, objects, _exec, service, child, session_row) = _pieces(
            tmp_path / f"run{round_id}")
        fresh = profiles.get(child["profile_id"])
        turn_id = service._create_child_turn(
            session_id=session_row["session_id"], child_profile=fresh,
            parent_turn_id="parent-turn", prompt="go", model=None,
            posture={"preset": "default", "keys": {"exec": "deny"}, "inheritedFrom": "p"})
        digests.append(records.get_turn_context(turn_id)["effective_config_object_digest"])
    assert digests[0] == digests[1], (
        "B案 requires same input -> same frozen object bytes; the anchor added no content")
