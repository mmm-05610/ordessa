"""Sole-occupancy invariants: one active lease per key, unique owner,
native/managed mutual exclusion, file-backed (survives a new manager)."""
from __future__ import annotations

import pytest

from backend.errors import MCP_OWNER_CONFLICT, McpError
from backend.managed import LANE_MANAGED, endpoint_fingerprint, new_owner_id
from managed_helpers import SERVER_SCOPE


def test_second_active_lease_on_same_key_is_refused(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    first = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id="srv-a", revision=revision)
    with pytest.raises(McpError) as exc:
        manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                           definition_id="srv-a", revision=revision)
    assert exc.value.code == MCP_OWNER_CONFLICT
    # closing releases the key; a new lease may then be opened.
    manager.close_lease(caller=caller, lease_id=first.lease_id,
                        owner_id=first.owner_id)
    second = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                                definition_id="srv-a", revision=revision)
    assert second.lease_id != first.lease_id
    assert second.state == "defined"


def test_different_sessions_same_endpoint_get_independent_leases(harness):
    # no pooling path: the endpoint fingerprint is equal, the sessionRef is
    # not, so the keys differ and each session gets its own lease + client.
    revision = harness.install_remote()
    manager = harness.manager()
    a = harness.caller("u-a", "sess-a")
    b = harness.caller("u-b", "sess-b")
    lease_a = manager.open_lease(caller=a, server_scope=SERVER_SCOPE,
                                 definition_id="srv-a", revision=revision)
    lease_b = manager.open_lease(caller=b, server_scope=SERVER_SCOPE,
                                 definition_id="srv-a", revision=revision)
    assert lease_a.endpoint_fingerprint == lease_b.endpoint_fingerprint
    assert lease_a.owner_id != lease_b.owner_id


def test_owner_id_must_be_unique_among_active_leases(harness):
    revision = harness.install_remote()
    manager = harness.manager()
    caller_a = harness.caller("u-a", "sess-a")
    caller_b = harness.caller("u-b", "sess-b")
    shared_owner = new_owner_id()
    harness.leases.create_lease(
        caller=caller_a, server_scope=SERVER_SCOPE, definition_id="srv-a",
        revision=revision, endpoint_fingerprint="sha256:" + "0" * 64,
        owner_id=shared_owner)
    with pytest.raises(McpError) as exc:
        harness.leases.create_lease(
            caller=caller_b, server_scope=SERVER_SCOPE, definition_id="srv-a",
            revision=revision, endpoint_fingerprint="sha256:" + "1" * 64,
            owner_id=shared_owner)
    assert exc.value.code == MCP_OWNER_CONFLICT


def test_native_projection_then_managed_lease_is_refused(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    manager.project_native(caller=caller, server_scope=SERVER_SCOPE,
                           definition_id="srv-a", revision=revision,
                           projection_digest="sha256:" + "a" * 64)
    with pytest.raises(McpError) as exc:
        manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                           definition_id="srv-a", revision=revision)
    assert exc.value.code == MCP_OWNER_CONFLICT


def test_managed_lease_then_native_projection_is_refused(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    lease = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id="srv-a", revision=revision)
    with pytest.raises(McpError) as exc:
        manager.project_native(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id="srv-a", revision=revision,
                               projection_digest="sha256:" + "b" * 64)
    assert exc.value.code == MCP_OWNER_CONFLICT
    # the managed lease survived the refused projection untouched
    assert harness.leases.get_lease(lease.lease_id, caller).lane == LANE_MANAGED


def test_occupancy_is_file_backed_across_manager_instances(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                       definition_id="srv-a", revision=revision)
    # a completely fresh manager (fresh store object) over the same root
    # still refuses the key - occupancy lives in the file, not in memory.
    reopened = harness.fresh_lease_store()
    other_manager = harness.manager(lease_store=reopened)
    with pytest.raises(McpError) as exc:
        other_manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                                 definition_id="srv-a", revision=revision)
    assert exc.value.code == MCP_OWNER_CONFLICT
    # and it can read back the lease facts from disk
    assert reopened.list_leases(caller)[0].state == "defined"


def test_endpoint_fingerprint_is_deterministic_and_secret_free(harness):
    # headers/env never enter the fingerprint (the credential dimension is
    # the lease's credential_revision field); same revision -> same digest.
    revision = harness.install_remote(headers={"X-Key": {"secretRef": "cred-1"}})
    model = harness.definitions.read_revision(
        server_scope=SERVER_SCOPE, definition_id="srv-a", revision=revision)
    fingerprint = endpoint_fingerprint(model)
    assert fingerprint == endpoint_fingerprint(model)
    assert "cred-1" not in fingerprint
