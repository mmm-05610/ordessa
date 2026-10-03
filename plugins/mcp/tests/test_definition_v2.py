"""V01 gate: typed v2 values, strict schema, CAS/immutable revisions, scope
isolation, and legacy read-compat (old digest kept, model normalised, no
rewrite)."""
import json

import pytest
from ordessa_server_compat.assets import mcp as legacy

from backend.definition import (
    Literal,
    SecretRef,
    canonical_definition_v2,
    definition_digest,
)
from backend.definition_store import McpDefinitionStore
from backend.errors import (
    MCP_ASSET_MISSING,
    MCP_CAS_CONFLICT,
    MCP_DEFINITION_INVALID,
    MCP_NAME_INVALID,
    MCP_OPERATION_CONFLICT,
    MCP_REVISION_EXISTS,
    MCP_SERVER_SCOPE_CONFLICT,
    McpError,
)

SCOPE = "scope-a"


def _definition(env=None, name="web-tools", command="/bin/web-tools"):
    return {"name": name, "transport": {"stdio": {
        "command": command, "args": ["--stdio"], "env": env or {}}}}


def _save(store, definition, *, revision_expected=0, key=None, definition_id="web-tools",
          scope=SCOPE):
    return store.save_revision(
        server_scope=scope, definition_id=definition_id, definition=definition,
        expected_version=revision_expected,
        operation_key=key or f"op-{definition_id}-{revision_expected}")


# -- typed values and strict schema ---------------------------------------------


def test_loopback_http_remote_with_typed_values_is_accepted():
    canonical = canonical_definition_v2({
        "name": "local-hub",
        "transport": {"remote": {
            "url": "http://127.0.0.1:8787/mcp",
            "headers": {"AUTH": {"secretRef": "credential_9"},
                        "X-TRACE": {"literal": "on"}}}},
    })
    assert canonical["transport"]["remote"]["headers"] == {
        "AUTH": {"secretRef": "credential_9"}, "X-TRACE": {"literal": "on"}}


def test_definition_id_must_be_a_lowercase_slug_and_writes_nothing(tmp_path):
    store = McpDefinitionStore(tmp_path / "assets")
    for bad in ("../escape", "Bad", "x" * 65, ""):
        with pytest.raises(McpError) as refused:
            store.save_revision(
                server_scope=SCOPE, definition_id=bad, definition=_definition("ok-name"),
                expected_version=0, operation_key="id-guard")
        assert refused.value.code == MCP_NAME_INVALID
    assert list((tmp_path / "assets").rglob("server.json")) == []


def test_literal_and_secretref_values_canonicalise_typed():
    canonical = canonical_definition_v2(_definition(env={
        "MODE": {"literal": "fast"},
        "API_KEY": {"secretRef": "credential_1"},
    }))
    assert canonical["transport"]["stdio"]["env"] == {
        "MODE": {"literal": "fast"}, "API_KEY": {"secretRef": "credential_1"}}


def test_a_bare_string_in_a_value_position_is_a_typed_refusal():
    with pytest.raises(McpError) as refused:
        canonical_definition_v2(_definition(env={"API_KEY": "plain-secret"}))
    assert refused.value.code == MCP_DEFINITION_INVALID
    assert "API_KEY" in refused.value.message


def test_oversized_nul_and_badly_shaped_values_refuse():
    for env in (
        {"A": {"literal": "x" * 4097}},
        {"A": {"literal": "bad\x00value"}},
        {"A": {"literal": 5}},
        {"A": {"other": "x"}},
        {"A": {"credentialRef": 17}},
        {"A": {"literal": "x", "secretRef": "y"}},
        {"A": None},
    ):
        with pytest.raises(McpError):
            canonical_definition_v2(_definition(env=env))


def test_unknown_transport_extra_fields_and_long_urls_refuse_before_storage(tmp_path):
    store = McpDefinitionStore(tmp_path / "assets")
    refusals = (
        {"name": "x", "transport": {"grpc": {}}},
        {"name": "x", "transport": {"stdio": {"command": "/bin/x"}}, "extra": 1},
        {"name": "x", "transport": {"stdio": {"command": "relative/x"}}},
        {"name": "x", "transport": {"remote": {"url": "http://evil.test/mcp"}}},
        {"name": "x", "transport": {"remote": {"url": "https://x.test/" + "a" * 600}}},
        {"name": "X", "transport": {"stdio": {"command": "/bin/x"}}},
    )
    for bad in refusals:
        with pytest.raises(McpError):
            _save(store, bad)
    # nothing reached storage: only the lock dir exists, no revision files
    written = list((tmp_path / "assets").rglob("server.json"))
    assert written == []


# -- save, CAS, immutability -------------------------------------------------------


def test_save_writes_one_immutable_revision_and_replays_idempotently(tmp_path):
    store = McpDefinitionStore(tmp_path / "assets")
    facts = _save(store, _definition(env={"API_KEY": {"secretRef": "c1"}}), key="k1")
    assert facts["revision"] == 1 and facts["digest"].startswith("sha256:")
    replay = _save(store, _definition(env={"API_KEY": {"secretRef": "c1"}}), key="k1")
    assert replay["replayed"] is True and replay["digest"] == facts["digest"]
    with pytest.raises(McpError) as clash:
        _save(store, _definition(env={"API_KEY": {"secretRef": "other"}}), key="k1")
    assert clash.value.code == MCP_OPERATION_CONFLICT
    with pytest.raises(McpError) as stale:
        _save(store, _definition(), revision_expected=5, key="k2")
    assert stale.value.code == MCP_CAS_CONFLICT
    # revision 1 bytes are untouched by every failed attempt
    path = store.revision_dir("web-tools", 1) / "server.json"
    model = json.loads(path.read_text(encoding="utf-8"))
    assert definition_digest(model) == facts["digest"]


def test_second_revision_and_duplicate_file_are_refused_per_layout(tmp_path):
    store = McpDefinitionStore(tmp_path / "assets")
    _save(store, _definition(), key="k1")
    second = _save(store, _definition(command="/bin/other"), revision_expected=1, key="k2")
    assert second["revision"] == 2
    assert store.get_definition(server_scope=SCOPE, definition_id="web-tools") \
        .latest_revision == 2
    # an existing revision file on disk is never overwritten by a save
    legacy_facts = store.install_legacy(_definition(name="other"), asset_id="other",
                                        revision=1)
    with pytest.raises(McpError) as exists:
        store.save_revision(
            server_scope=SCOPE, definition_id="other", definition=_definition(name="other"),
            expected_version=0, operation_key="k3")
    assert exists.value.code == MCP_REVISION_EXISTS
    path = store.revision_dir("other", 1) / "server.json"
    assert definition_digest(json.loads(path.read_text(encoding="utf-8"))) \
        == legacy_facts["digest"]


def test_saved_revision_never_carries_content_off_disk(tmp_path):
    store = McpDefinitionStore(tmp_path / "assets")
    facts = _save(store, _definition(env={"M": {"literal": "v"}}), key="k1")
    revision = store.read_revision(server_scope=SCOPE, definition_id="web-tools", revision=1)
    assert revision.canonical_digest == facts["digest"]
    assert revision.canonical_shape == "v2"
    assert revision.transport.env["M"] == Literal("v")
    assert revision.transport.executable_ref == "/bin/web-tools"
    assert tuple(revision.transport.argv) == ("--stdio",)
    with pytest.raises(McpError) as missing:
        store.read_revision(server_scope=SCOPE, definition_id="web-tools", revision=9)
    assert missing.value.code == MCP_ASSET_MISSING


def test_approval_is_separate_metadata_and_leaves_bytes_immutable(tmp_path):
    store = McpDefinitionStore(tmp_path / "assets")
    _save(store, _definition(), key="k1")
    path = store.revision_dir("web-tools", 1) / "server.json"
    before = path.read_bytes()
    record = store.approve_revision(
        server_scope=SCOPE, definition_id="web-tools", revision=1, actor="admin-1")
    assert record["approval"]["actor"] == "admin-1"
    assert store.read_revision(server_scope=SCOPE, definition_id="web-tools",
                               revision=1).approval.actor == "admin-1"
    assert path.read_bytes() == before


# -- server scope isolation -----------------------------------------------------------


def test_cross_scope_read_is_refused_without_leaking_and_write_conflicts(tmp_path):
    store = McpDefinitionStore(tmp_path / "assets")
    _save(store, _definition(), key="k1")
    with pytest.raises(McpError) as read:
        store.get_definition(server_scope="scope-b", definition_id="web-tools")
    assert read.value.code == MCP_ASSET_MISSING
    with pytest.raises(McpError) as deep:
        store.read_revision(server_scope="scope-b", definition_id="web-tools", revision=1)
    assert deep.value.code == MCP_ASSET_MISSING
    with pytest.raises(McpError) as write:
        store.save_revision(
            server_scope="scope-b", definition_id="web-tools", definition=_definition(),
            expected_version=0, operation_key="k2")
    assert write.value.code == MCP_SERVER_SCOPE_CONFLICT


# -- legacy read-compat and migration mapping --------------------------------------------


def test_legacy_revision_adopts_under_its_old_digest_and_normalises_values(tmp_path):
    store = McpDefinitionStore(tmp_path / "assets")
    legacy_facts = store.install_legacy({
        "name": "web-tools",
        "transport": {"stdio": {
            "command": "/bin/web-tools", "args": [],
            "env": {"API_KEY": {"credentialRef": "credential_1"}}}},
    }, asset_id="web-tools", revision=1)
    revision = store.adopt_legacy_revision(
        server_scope=SCOPE, definition_id="web-tools", revision=1,
        source="server_assets:legacy-import")
    # old digest preserved verbatim, never recomputed under a new rule
    assert revision.canonical_digest == legacy_facts["digest"]
    assert revision.canonical_digest == legacy.definition_digest(
        legacy.canonical_definition({
            "name": "web-tools",
            "transport": {"stdio": {
                "command": "/bin/web-tools", "args": [],
                "env": {"API_KEY": {"credentialRef": "credential_1"}}}},
        }))
    assert revision.canonical_shape == "legacy"
    # legacy on-disk shape is untouched and read as a SecretRef in the v2 model
    stored = json.loads((store.revision_dir("web-tools", 1) / "server.json")
                        .read_text(encoding="utf-8"))
    assert stored["transport"]["stdio"]["env"] == {"API_KEY": "credential_1"}
    assert revision.transport.env["API_KEY"] == SecretRef("credential_1")
    assert revision.migration == {
        "legacy_digest": legacy_facts["digest"], "recomputed": False,
        "rule": revision.migration["rule"],
    }
    # re-adopting the same bytes is idempotent; different bytes are refused
    again = store.adopt_legacy_revision(
        server_scope=SCOPE, definition_id="web-tools", revision=1)
    assert again.canonical_digest == legacy_facts["digest"]
