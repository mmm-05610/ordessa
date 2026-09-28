"""Controlled T09 read-only association after a registry restart."""
from __future__ import annotations

from ordessa_harness.server_acp.registry import AcpChannelRegistry


class Records:
    def __init__(self):
        self.rows = {}
        self.created = 0

    def create_session(self, **_kwargs):
        return "accepted", {"session_id": f"session-{self.created + 1}"}

    def create_turn(self, *, session_id, **_kwargs):
        self.created += 1
        turn_id = f"turn-{self.created}"
        self.rows[turn_id] = {"id": turn_id, "session_id": session_id,
                              "harness_type": "pi", "state": "accepted",
                              "terminal_reason": None, "error_code": None,
                              "updated_at": f"tick-{self.created}"}
        return True, "accepted", {"turn_id": turn_id}

    def get_turn_context(self, turn_id):
        return dict(self.rows[turn_id])

    def finish_cancelled(self, execution_id, *, terminal_reason):
        self.rows[execution_id].update(state="cancelled", terminal_reason=terminal_reason)

    def fail_turn(self, execution_id, code):
        self.rows[execution_id].update(state="failed", error_code=code)


class Profiles:
    def get(self, _profile_id):
        return {"config_revision": 1, "config_object_digest": "sha256:profile"}


class Transport:
    def __init__(self):
        self.terminated = 0

    def terminate(self):
        self.terminated += 1


def make_registry(records, launch):
    return AcpChannelRegistry(session_records=records, profile_records=Profiles(), launch=launch)


def test_restart_lookup_never_reattaches_or_relaunches_a_terminal_run(tmp_path):
    records = Records()
    launched = []

    def launch(**_kwargs):
        transport = Transport()
        launched.append(transport)
        return transport

    original = make_registry(records, launch)
    opened = original.acquire(harness_id="pi", workspace_id="project-1",
                              profile_id="profile-1", cwd=str(tmp_path))
    connection_id, execution_id = opened["connectionId"], opened["executionId"]
    live = original.recovery_view(connection_id=connection_id, execution_id=execution_id)
    assert live["attachable"] is True and live["connectionId"] == connection_id
    assert original.recovery_view(connection_id="other", execution_id=execution_id)["attachable"] is False

    original.stop_all()
    assert records.rows[execution_id]["state"] == "cancelled"
    restarted = make_registry(records, launch)
    before = dict(records.rows[execution_id])
    recovered = restarted.recovery_view(connection_id=connection_id, execution_id=execution_id)
    assert recovered["attachable"] is False and recovered["connectionId"] is None
    assert recovered["run"]["state"] == "closed"
    assert recovered["run"]["endReason"] == "server-stop"
    assert records.rows[execution_id] == before
    assert len(launched) == 1 and records.created == 1
    assert restarted.get(connection_id) is None


def test_unsealed_inflight_row_after_restart_is_readable_but_not_reattachable(tmp_path):
    records = Records()
    launches = []

    def launch(**_kwargs):
        launches.append(Transport())
        return launches[-1]

    first = make_registry(records, launch)
    opened = first.acquire(harness_id="pi", workspace_id="project-1",
                           profile_id="profile-1", cwd=str(tmp_path))
    restarted = make_registry(records, launch)
    view = restarted.recovery_view(connection_id=opened["connectionId"],
                                   execution_id=opened["executionId"])
    assert view["run"]["state"] == "accepted"  # no invented terminal result
    assert view["attachable"] is False and view["connectionId"] is None
    assert records.created == 1 and len(launches) == 1
    first.stop_all()
