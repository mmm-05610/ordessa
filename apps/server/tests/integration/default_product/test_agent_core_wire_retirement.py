"""C01: one Pacthold Agent wire, with old product aliases unreachable."""
from __future__ import annotations

import importlib.util
import sqlite3

import pytest
from server_plugin_api import WireError

from ordessa_server.composition.configuration.product_selection import create_host_product_composition as create_composition


LEGACY_PRODUCT_MODULES = (
    "profile_wire_plugin",
    "agent_wire_plugin",
    "profile_configuration",
    "profile_preparation",
    "profile_sessions",
    "native_configuration",
    "skills",
    "configuration_observation",
    "profile_configuration",
    "submission_service",
)


def test_retired_profile_and_agent_factories_cannot_be_imported():
    for module in LEGACY_PRODUCT_MODULES:
        assert importlib.util.find_spec(f"ordessa_server_product.{module}") is None


def test_default_core_wire_has_only_public_agent_v3_and_preserves_old_database_bytes(tmp_path):
    root = tmp_path / "owned-data-root"
    bootstrap = create_composition().default_runtime(root)
    bootstrap.start()
    bootstrap.stop()

    profile_db = root / "plugins" / "profile" / "profile-store.sqlite"
    submission_db = root / "plugins" / "agent" / "submissions.sqlite"
    profile_db.parent.mkdir(parents=True)
    submission_db.parent.mkdir(parents=True)
    with sqlite3.connect(profile_db) as connection:
        connection.execute("CREATE TABLE historical_profile_fixture(id TEXT PRIMARY KEY, value BLOB)")
        connection.execute("INSERT INTO historical_profile_fixture VALUES('keep', X'00ff')")
    with sqlite3.connect(submission_db) as connection:
        connection.execute("CREATE TABLE historical_submission_fixture(id TEXT PRIMARY KEY, value BLOB)")
        connection.execute("INSERT INTO historical_submission_fixture VALUES('keep', X'fe01')")
    before = (profile_db.read_bytes(), submission_db.read_bytes())

    runtime = create_composition().default_runtime(root)
    try:
        runtime.start()
        methods = set(runtime.wire._registry.method_ids())
        assert {"agents.capabilities", "agents.profiles.list", "agents.nodes.prepare",
                "agents.operations.read"} <= methods
        assert not any(method.startswith(("profiles.v2.", "agent.")) for method in methods)

        capabilities = runtime.wire.dispatch("agents.capabilities", {}, caller=runtime.wire.identity_authority.authenticate("Bearer " + runtime.token))
        assert capabilities["contractVersion"] == "agent-assembly/3"
        assert capabilities["supports"]["profileCatalog"] is False
        assert "agents.profiles.list" in capabilities["supportedMethods"]
        assert "agents.profiles.create" not in capabilities["supportedMethods"]

        for method in (
            "profiles.v2.listProfiles", "agent.session.resolve",
            "agent.config.read", "agent.config.submitOperation",
            "agent.config.observe", "agent.config.release",
            "agent.submitInput", "agent.submission.scope",
            "agent.submission.capture.read", "agent.submission.query",
        ):
            with pytest.raises(WireError) as refused:
                runtime.wire.dispatch(method, {})
            assert refused.value.family == "INVALID_REQUEST"
    finally:
        runtime.stop()

    assert (profile_db.read_bytes(), submission_db.read_bytes()) == before
