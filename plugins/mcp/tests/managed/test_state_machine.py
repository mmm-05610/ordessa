"""State machine: legal chain leaves one independent fact per level (FR-02);
every illegal move is a typed refusal."""
from __future__ import annotations

import pytest

from backend.errors import McpError
from backend.managed import (
    LEGAL_TRANSITIONS,
    MCP_STATE_TRANSITION_INVALID,
)
from managed_helpers import SERVER_SCOPE, TOOLS_ONE

CHAIN = ("defined", "selected", "planned", "connecting", "connected",
         "catalog-observed")


def _walk_to_catalog_observed(harness, manager, caller, definition_id, revision):
    lease = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id=definition_id, revision=revision)
    manager.plan_connection(caller=caller, lease_id=lease.lease_id,
                            submission_id="sub-1")
    harness.factory.set(caller.session_ref, definition_id, tools=TOOLS_ONE)
    manager.start_connection(caller=caller, lease_id=lease.lease_id)
    return manager.observe_catalog(caller=caller, lease_id=lease.lease_id)


def test_full_chain_records_six_independent_facts_not_one_boolean(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    _walk_to_catalog_observed(harness, manager, caller, "srv-a", revision)
    lease = harness.leases.get_lease(
        next(l.lease_id for l in harness.leases.list_leases(caller)), caller)
    facts = harness.leases.facts(lease.lease_id, caller)
    state_entries = [f for f in facts if f["kind"] == "state-entry"]
    assert [f["to"] for f in state_entries] == list(CHAIN)
    # each level is its own record with its own from/to/seq - the ladder is
    # never collapsed into a single "available" boolean.
    assert len({f["seq"] for f in state_entries}) == 6
    assert [(f.get("from"), f.get("to")) for f in state_entries] == [
        (None, "defined"), ("defined", "selected"), ("selected", "planned"),
        ("planned", "connecting"), ("connecting", "connected"),
        ("connected", "catalog-observed"),
    ]
    info = manager.inspect_connection(caller=caller, lease_id=lease.lease_id)
    for level in CHAIN:
        assert info["levels"][level]["to"] == level
    # transition into connecting stamped a start time; nothing closed yet.
    assert lease.started_at and lease.closed_at is None


def test_illegal_transitions_are_typed_and_change_nothing(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    lease = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id="srv-a", revision=revision)
    for target in ("connecting", "connected", "catalog-observed", "closed"):
        with pytest.raises(McpError) as exc:
            harness.leases.transition(lease.lease_id, caller, target)
        assert exc.value.code == MCP_STATE_TRANSITION_INVALID
    assert harness.leases.get_lease(lease.lease_id, caller).state == "defined"


def test_skipping_connected_before_catalog_is_refused(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    harness.factory.set("sess-a", "srv-a", tools=TOOLS_ONE)
    lease, _, _ = harness.bring_up(manager, caller, "srv-a", revision)
    # a second observation re-enters catalog-observed? no: connected->
    # catalog-observed already consumed; re-observation stays a fact, the
    # state transition connected -> catalog-observed from catalog-observed
    # is NOT legal and must not silently happen.
    with pytest.raises(McpError) as exc:
        harness.leases.transition(lease.lease_id, caller, "catalog-observed")
    assert exc.value.code == MCP_STATE_TRANSITION_INVALID
    catalogs = harness.catalogs.observations_for_lease(lease.lease_id)
    assert len(catalogs) == 1


def test_terminal_states_accept_no_transitions(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    _walk_to_catalog_observed(harness, manager, caller, "srv-a", revision)
    lease = harness.leases.list_leases(caller)[0]
    result = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    assert result["state"] == "closed"
    for target in LEGAL_TRANSITIONS:
        if target == "closed":
            continue
        with pytest.raises(McpError) as exc:
            harness.leases.transition(lease.lease_id, caller, target)
        assert exc.value.code == MCP_STATE_TRANSITION_INVALID
    assert LEGAL_TRANSITIONS["closed"] == frozenset()
    assert LEGAL_TRANSITIONS["refused"] == frozenset()


def test_close_from_early_states_releases_without_a_client(harness):
    # defined -> closing -> closed is legal and never asks the factory.
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    lease = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id="srv-a", revision=revision)
    result = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    assert result["state"] == "closed"
    assert harness.factory.production_count == 0
