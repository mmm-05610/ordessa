"""Closing an Agent runtime must release its environment writer lock.

Regression: the close-time unresolved inventory called a node-access
enumeration the product policy never grants. Once a dispatch had built the
agent services, ``runtime.stop()`` raised and left the writer lock row behind,
so the next process could not open the same data root (the real
``test_real_http_cli_catalog_lifecycle_conflicts_auth_and_restart`` failure).
"""
import sqlite3

import pytest

from ordessa_server.composition.agent_tools import AgentServiceConfiguration, build_agent_runtime
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac


def _build(root):
    port = ProtectedFingerprintHmac({"fixture": b"close-fixture"}, active_key_id="fixture")
    return build_agent_runtime(
        AgentServiceConfiguration(root, agent_contract_version="agent-assembly/1"),
        fingerprint_port=port)


def _lock_rows(root):
    with sqlite3.connect(root / "state" / "core.sqlite") as connection:
        return [row[0] for row in connection.execute("SELECT owner_token FROM env_writer_lock").fetchall()]


@pytest.mark.parametrize("dispatch", [None, "agents.capabilities"])
def test_agent_runtime_stop_releases_the_writer_lock(tmp_path, dispatch):
    root = tmp_path / "root"
    runtime = _build(root)
    runtime.start()
    try:
        if dispatch is not None:
            caller = runtime.wire.identity_authority.authenticate("Bearer " + runtime.token)
            runtime.wire.dispatch(dispatch, {}, caller=caller)
    finally:
        runtime.stop()
    assert _lock_rows(root) == []
    # The failure mode was exactly this reopen: a second runtime on the same root.
    reopened = _build(root)
    reopened.start()
    reopened.stop()
    assert _lock_rows(root) == []
