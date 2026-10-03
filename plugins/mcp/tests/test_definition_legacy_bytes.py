"""V01/V09 mutual-proof: the new store reproduces the legacy MCP asset byte rules.

Every sample here is the same definition the legacy suite uses
(apps/server/tests/test_asset_hubs.py, MCP section; plugins/server-compat
SC/assets/mcp.py). The old implementation is imported directly from the
editable venv install and compared against: canonical dict, digest string,
server.json bytes, file mode, and error code+message text.
"""
import json
import stat

import pytest
from ordessa_server_compat.assets import mcp as legacy

from backend.definition import (
    canonical_definition,
    canonical_definition_v2,
    definition_digest,
)
from backend.definition_store import McpDefinitionStore
from backend.errors import McpError

# -- samples taken verbatim from the legacy test suite -------------------------

STDIO_WITH_REF = {
    "name": "web-tools",
    "transport": {"stdio": {
        "command": "/runtime/bin/web-tools",
        "args": ["--stdio"],
        "env": {"API_KEY": {"credentialRef": "credential_1"}},
    }},
}
STDIO_BARE = {"name": "web-tools", "transport": {"stdio": {"command": "/bin/x", "args": []}}}
REMOTE_WITH_REF = {
    "name": "hub-remote",
    "transport": {"remote": {
        "url": "https://mcp.example.test/a",
        "headers": {"AUTH": {"credentialRef": "credential_2"}}},
    },
}
VALID_SAMPLES = (STDIO_WITH_REF, STDIO_BARE, REMOTE_WITH_REF)

MALFORMED_SAMPLES = (
    {"name": "bad", "transport": {"stdio": {
        "command": "/bin/x", "env": {"KEY": "plain-secret"}}}},
    {"name": "bad", "transport": {"stdio": {"command": "x"}}},
    {"name": "bad", "transport": {"grpc": {}}},
    {"name": "bad", "transport": {"remote": {"url": "http://evil.test"}}},
    {"name": "Bad Name", "transport": {"stdio": {"command": "/bin/x"}}},
    {"name": "bad", "transport": {"stdio": {"command": "/bin/x"}}, "extra": True},
    {"name": "bad", "transport": {"remote": {"url": "https://x.test/" + "a" * 600}}},
    {"name": "bad", "transport": {"stdio": {"command": "/bin/x", "args": ["a"] * 65}}},
    "not-a-mapping",
)


def test_canonical_dicts_are_identical_to_legacy():
    for sample in VALID_SAMPLES:
        assert canonical_definition(sample) == legacy.canonical_definition(sample)


def test_digest_strings_are_identical_to_legacy():
    for sample in VALID_SAMPLES:
        canonical = canonical_definition(sample)
        assert definition_digest(canonical) == legacy.definition_digest(canonical)
        assert definition_digest(canonical).startswith("sha256:")


def test_malformed_definitions_refuse_with_identical_codes_and_text():
    for sample in MALFORMED_SAMPLES:
        with pytest.raises(legacy.McpAssetError) as old:
            legacy.canonical_definition(sample)
        with pytest.raises(McpError) as new:
            canonical_definition(sample)
        assert new.value.code == old.value.code
        assert str(new.value) == str(old.value)


def test_legacy_and_new_install_produce_the_same_bytes_and_mode(tmp_path):
    old_store = legacy.McpAssetStore(tmp_path / "old")
    new_store = McpDefinitionStore(tmp_path / "new")
    for index, sample in enumerate(VALID_SAMPLES):
        asset_id = f"asset-{index}"
        old_facts = old_store.install(sample, asset_id=asset_id, revision=1)
        new_facts = new_store.install_legacy(sample, asset_id=asset_id, revision=1)
        assert new_facts == old_facts
        old_path = old_store.revision_dir(asset_id, 1) / "server.json"
        new_path = new_store.revision_dir(asset_id, 1) / "server.json"
        assert new_path.read_bytes() == old_path.read_bytes()
        assert stat.S_IMODE(new_path.stat().st_mode) == 0o644
        # the file layout spelling itself is the legacy one
        assert new_path.relative_to(tmp_path / "new") == \
            old_path.relative_to(tmp_path / "old")


def test_cross_verification_works_in_both_directions(tmp_path):
    old_store = legacy.McpAssetStore(tmp_path / "shared")
    new_store = McpDefinitionStore(tmp_path / "shared")
    old_facts = old_store.install(STDIO_WITH_REF, asset_id="web-tools", revision=1)
    assert new_store.verify_revision_digest(
        server_scope="scope-a", definition_id="web-tools", revision=1,
        expected_digest=old_facts["digest"]) is True
    new_facts = new_store.install_legacy(STDIO_WITH_REF, asset_id="web-tools-2", revision=7)
    assert old_store.verify(asset_id="web-tools-2", revision=7,
                            expected_digest=new_facts["digest"]) is True


def test_duplicate_revision_refusal_matches_legacy_text(tmp_path):
    old_store = legacy.McpAssetStore(tmp_path / "old")
    new_store = McpDefinitionStore(tmp_path / "new")
    old_store.install(STDIO_BARE, asset_id="web-tools", revision=1)
    new_store.install_legacy(STDIO_BARE, asset_id="web-tools", revision=1)
    with pytest.raises(legacy.McpAssetError) as old:
        old_store.install(STDIO_BARE, asset_id="web-tools", revision=1)
    with pytest.raises(McpError) as new:
        new_store.install_legacy(STDIO_BARE, asset_id="web-tools", revision=1)
    assert old.value.code == new.value.code == "MCP_REVISION_EXISTS"
    assert str(old.value) == str(new.value)


def test_stored_v2_revision_bytes_match_the_shared_digest_rule(tmp_path):
    store = McpDefinitionStore(tmp_path / "assets")
    definition = {
        "name": "web-tools",
        "transport": {"stdio": {
            "command": "/bin/web-tools", "args": ["--stdio"],
            "env": {"API_KEY": {"secretRef": "credential_1"},
                    "MODE": {"literal": "fast"}},
        }},
    }
    facts = store.save_revision(
        server_scope="scope-a", definition_id="web-tools", definition=definition,
        expected_version=0, operation_key="op-1")
    payload = (store.revision_dir("web-tools", 1) / "server.json").read_bytes()
    canonical = canonical_definition_v2(definition)
    assert payload == json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert facts["digest"] == definition_digest(canonical) == legacy.definition_digest(canonical)
