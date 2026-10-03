"""FR-10 / counterexample 7: unconfirmable failure -> unknown -> reconcile is
mandatory before any retry; no second lease bets on the old client's exit."""
from __future__ import annotations

import pytest

from backend.errors import (
    CONNECTION_FAILED,
    MCP_OWNER_CONFLICT,
    UNKNOWN_OUTCOME,
    McpError,
)
from backend.managed import (
    MCP_RECONCILE_REQUIRED,
    MCP_STATE_TRANSITION_INVALID,
)
from managed_helpers import SERVER_SCOPE, TOOLS_ONE


def _lease_in_unknown(harness, manager, caller, definition_id="srv-a"):
    revision = harness.install_remote(definition_id)
    lease = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id=definition_id, revision=revision)
    manager.plan_connection(caller=caller, lease_id=lease.lease_id)
    harness.factory.set(caller.session_ref, definition_id,
                        tools=TOOLS_ONE, connect_error=RuntimeError("half-open transport"))
    with pytest.raises(McpError) as exc:
        manager.start_connection(caller=caller, lease_id=lease.lease_id)
    assert exc.value.code == UNKNOWN_OUTCOME
    return revision, harness.leases.get_lease(lease.lease_id, caller)


def test_connect_failure_parks_lease_in_unknown_with_its_own_fact(harness):
    manager, caller = harness.manager(), harness.caller()
    _, lease = _lease_in_unknown(harness, manager, caller)
    assert lease.state == "unknown"
    kinds = [(f["kind"], f.get("to")) for f in harness.leases.facts(lease.lease_id, caller)]
    assert ("state-entry", "unknown") in kinds
    # the unknown fact records the failed phase, never a secret or a body
    unknown_fact = [f for f in harness.leases.facts(lease.lease_id, caller)
                    if f.get("to") == "unknown"][0]
    assert unknown_fact["evidence"] == {"phase": "connect", "error": "RuntimeError"}


def test_no_second_lease_while_unknown_must_be_reconciled_first(harness):
    manager, caller = harness.manager(), harness.caller()
    revision, lease = _lease_in_unknown(harness, manager, caller)
    with pytest.raises(McpError) as exc:
        manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                           definition_id="srv-a", revision=revision)
    assert exc.value.code == MCP_RECONCILE_REQUIRED
    # close is also blocked: closing now would be another unconfirmed bet
    with pytest.raises(McpError) as exc2:
        manager.close_lease(caller=caller, lease_id=lease.lease_id,
                            owner_id=lease.owner_id)
    assert exc2.value.code == MCP_RECONCILE_REQUIRED
    # arbitrary state traffic out of unknown is refused (only reconcile paths)
    with pytest.raises(McpError) as exc3:
        harness.leases.transition(lease.lease_id, caller, "connecting")
    assert exc3.value.code == MCP_STATE_TRANSITION_INVALID


def test_reconcile_terminated_releases_key_and_retry_gets_fresh_client(harness):
    manager, caller = harness.manager(), harness.caller()
    revision, lease = _lease_in_unknown(harness, manager, caller)
    client = harness.factory.produced[-1]
    assert client.connected is False and client.close_count == 0
    reconciled = manager.reconcile(caller=caller, lease_id=lease.lease_id,
                                   owner_id=lease.owner_id, outcome="terminated",
                                   evidence={"source": "manager-query",
                                             "observation": "client-not-listed"})
    assert reconciled.state == "closed"
    assert reconciled.closed_at
    assert reconciled.cleanup_evidence["reconciled"] is True
    # only AFTER the reconciliation record may a retry create a NEW lease
    harness.factory.set(caller.session_ref, "srv-a", tools=TOOLS_ONE)
    retry, _, new_client = harness.bring_up(manager, caller, "srv-a", revision)
    assert retry.lease_id != lease.lease_id
    assert new_client is not client


def test_reconcile_alive_continues_the_same_lease_never_a_second(harness):
    manager, caller = harness.manager(), harness.caller()
    revision, lease = _lease_in_unknown(harness, manager, caller)
    reconciled = manager.reconcile(caller=caller, lease_id=lease.lease_id,
                                   owner_id=lease.owner_id, outcome="alive",
                                   evidence={"source": "manager-query",
                                             "observation": "client-listed"})
    assert reconciled.state == "connected"
    # the reconciliation says the client is alive and handshaked; the L0/L1
    # fake models that fact so the SAME lease can complete its chain...
    harness.factory.produced[-1].connected = True
    catalog = manager.observe_catalog(caller=caller, lease_id=lease.lease_id)
    assert catalog.tool_names == ("echo",)
    # ...while the key stays occupied: no second lease.
    with pytest.raises(McpError) as exc:
        manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                           definition_id="srv-a", revision=revision)
    assert exc.value.code == MCP_OWNER_CONFLICT


def test_start_failure_is_confirmed_refused_and_releases_the_key(harness):
    # nothing ever lived -> the outcome IS confirmable -> refused, not unknown
    manager, caller = harness.manager(), harness.caller()
    revision = harness.install_remote()
    lease = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id="srv-a", revision=revision)
    manager.plan_connection(caller=caller, lease_id=lease.lease_id)
    harness.factory.set(caller.session_ref, "srv-a",
                        tools=TOOLS_ONE, start_error=OSError("exec failed"))
    with pytest.raises(McpError) as exc:
        manager.start_connection(caller=caller, lease_id=lease.lease_id)
    assert exc.value.code == CONNECTION_FAILED
    assert harness.leases.get_lease(lease.lease_id, caller).state == "refused"
    retry = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id="srv-a", revision=revision)
    assert retry.state == "defined"  # key free without any reconcile


def test_reconcile_requires_owner_and_only_applies_to_unknown(harness):
    manager, caller = harness.manager(), harness.caller()
    revision = harness.install_remote()
    harness.factory.set("sess-a", "srv-a", tools=TOOLS_ONE)
    lease, _, _ = harness.bring_up(manager, caller, "srv-a", revision)
    with pytest.raises(McpError) as exc:  # healthy lease: nothing to reconcile
        manager.reconcile(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, outcome="terminated",
                          evidence={"source": "x"})
    assert exc.value.code == MCP_STATE_TRANSITION_INVALID
    # and the owner check stands even when there would be something to do
    with pytest.raises(McpError) as exc2:
        manager.reconcile(caller=caller, lease_id=lease.lease_id,
                          owner_id="owner-wrong", outcome="terminated",
                          evidence={"source": "x"})
    assert exc2.value.code == MCP_OWNER_CONFLICT
