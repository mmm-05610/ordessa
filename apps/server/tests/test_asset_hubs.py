"""Order 58 stage A/B: the skill asset store and its refusals.

The order's G1 is "one store: id / revision / tree digest / source, in the
Agent Skills format". These tests pin the format rules and the install
boundaries, each with the counterexample the order asks for: illegal
frontmatter, an empty or link-bearing tree, an oversized install, a revision
that already exists, and a digest that no longer matches.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins"  / "harness"

from ordessa_server_compat.assets.skills import (
    MAX_ASSET_ENTRIES,
    SkillAssetError,
    SkillAssetStore,
    parse_skill_frontmatter,
)


def _skill(root: pathlib.Path, name: str = "my-skill", body: str = "Body.\n") -> pathlib.Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: does a thing\n---\n\n{body}",
        encoding="utf-8",
    )
    return directory


def test_the_two_required_fields_and_nothing_guessed():
    fields = parse_skill_frontmatter(
        "---\nname: my-skill\ndescription: \"does a thing\"\n---\nbody\n")
    assert fields == {"name": "my-skill", "description": "does a thing"}


def test_illegal_frontmatter_is_a_typed_refusal():
    with pytest.raises(SkillAssetError) as missing:
        parse_skill_frontmatter("name: my-skill\ndescription: x\n")
    assert missing.value.code == "SKILL_FRONTMATTER_MISSING"

    with pytest.raises(SkillAssetError) as bad_name:
        parse_skill_frontmatter("---\nname: My Skill\ndescription: x\n---\n")
    assert bad_name.value.code == "SKILL_NAME_INVALID"

    with pytest.raises(SkillAssetError) as no_description:
        parse_skill_frontmatter("---\nname: my-skill\n---\n")
    assert no_description.value.code == "SKILL_DESCRIPTION_MISSING"

    with pytest.raises(SkillAssetError) as not_a_scalar:
        parse_skill_frontmatter("---\nname: my-skill\ndescription: x\ntags: [a, b]\n---\n")
    assert not_a_scalar.value.code == "SKILL_FRONTMATTER_INVALID"


def test_install_publishes_one_revision_and_verifies_its_digest(tmp_path):
    store = SkillAssetStore(tmp_path / "assets")
    source = _skill(tmp_path)
    (source / "resources").mkdir()
    (source / "resources" / "data.json").write_text('{"a": 1}\n', encoding="utf-8")
    facts = store.install(source, asset_id="my-skill", revision=1)
    assert facts["files"] == 2 and facts["tree_digest"].startswith("sha256:")
    installed = store.revision_dir("my-skill", 1)
    assert (installed / "SKILL.md").is_file()
    assert store.verify(asset_id="my-skill", revision=1,
                        expected_digest=facts["tree_digest"]) is True
    assert store.verify(asset_id="my-skill", revision=1,
                        expected_digest="sha256:" + "0" * 64) is False


def test_install_refuses_a_second_revision_at_the_same_number(tmp_path):
    store = SkillAssetStore(tmp_path / "assets")
    source = _skill(tmp_path)
    store.install(source, asset_id="my-skill", revision=1)
    with pytest.raises(SkillAssetError) as exists:
        store.install(source, asset_id="my-skill", revision=1)
    assert exists.value.code == "SKILL_REVISION_EXISTS"


def test_a_link_bearing_or_oversized_tree_is_refused(tmp_path):
    store = SkillAssetStore(tmp_path / "assets")
    source = _skill(tmp_path)
    os.symlink("/etc/hostname", source / "escape.txt")
    with pytest.raises(SkillAssetError) as linked:
        store.install(source, asset_id="my-skill", revision=1)
    assert linked.value.code == "SKILL_ASSET_INVALID"
    os.unlink(source / "escape.txt")

    for index in range(MAX_ASSET_ENTRIES + 1):
        (source / f"file-{index}.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SkillAssetError) as oversized:
        store.install(source, asset_id="my-skill", revision=1)
    assert oversized.value.code == "SKILL_ASSET_OUTSIDE_BOUNDS"


def test_a_missing_skill_md_is_refused(tmp_path):
    store = SkillAssetStore(tmp_path / "assets")
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(SkillAssetError) as refused:
        store.install(bare, asset_id="bare", revision=1)
    assert refused.value.code == "SKILL_ASSET_INVALID"


# -- MCP assets and the per-family spellings (order 58 G1/G2) --------------


def test_a_stdio_definition_canonicalises_and_refuses_misuse():
    from ordessa_server_compat.assets.mcp import McpAssetError, canonical_definition

    canonical = canonical_definition({
        "name": "web-tools",
        "transport": {"stdio": {
            "command": "/runtime/bin/web-tools",
            "args": ["--stdio"],
            "env": {"API_KEY": {"credentialRef": "credential_1"}},
        }},
    })
    assert canonical["transport"]["stdio"]["env"] == {"API_KEY": "credential_1"}

    with pytest.raises(McpAssetError) as literal:
        canonical_definition({
            "name": "bad",
            "transport": {"stdio": {"command": "/bin/x", "env": {"KEY": "plain-secret"}}},
        })
    assert literal.value.code == "MCP_CREDENTIAL_REFERENCE_REQUIRED"

    with pytest.raises(McpAssetError) as relative:
        canonical_definition({"name": "bad", "transport": {"stdio": {"command": "x"}}})
    assert relative.value.code == "MCP_DEFINITION_INVALID"

    with pytest.raises(McpAssetError) as transport:
        canonical_definition({"name": "bad", "transport": {"grpc": {}}})
    assert transport.value.code == "MCP_TRANSPORT_UNSUPPORTED"

    with pytest.raises(McpAssetError) as remote:
        canonical_definition({"name": "bad", "transport": {"remote": {"url": "http://evil.test"}}})
    assert remote.value.code == "MCP_DEFINITION_INVALID"


def test_the_mcp_store_publishes_one_revision_and_verifies_it(tmp_path):
    from ordessa_server_compat.assets.mcp import McpAssetError, McpAssetStore

    store = McpAssetStore(tmp_path / "assets")
    definition = {"name": "web-tools", "transport": {"stdio": {"command": "/bin/x", "args": []}}}
    facts = store.install(definition, asset_id="web-tools", revision=1)
    assert facts["digest"].startswith("sha256:") and facts["transport"] == "stdio"
    assert store.verify(asset_id="web-tools", revision=1, expected_digest=facts["digest"]) is True
    assert store.read(asset_id="web-tools", revision=1)["name"] == "web-tools"
    with pytest.raises(McpAssetError) as exists:
        store.install(definition, asset_id="web-tools", revision=1)
    assert exists.value.code == "MCP_REVISION_EXISTS"


def test_the_two_observed_spellings_render_and_unsupported_families_refuse():
    from ordessa_server_compat.assets.mcp import canonical_definition
    from ordessa_server_compat.assets.rendering import McpRenderError, render_for_family
    from ordessa_harness.registry.loader import load_builtin_registry

    registry = load_builtin_registry()

    def spec(name):
        return registry.get(name).profile

    canonical = canonical_definition({
        "name": "web-tools",
        "transport": {"stdio": {
            "command": "/bin/web-tools", "args": ["--stdio"],
            "env": {"API_KEY": {"credentialRef": "credential_1"}},
        }},
    })

    target, text = render_for_family(
        canonical, profile_spec=spec("claude-code"),
        resolved_env={"API_KEY": "resolved-value"})
    # 086 stage 1 (first-hand, CLI 2.1.274): the CLI reads `mcpServers` from
    # `$CLAUDE_CONFIG_DIR/.claude.json`, not from settings.json, so 58's slot
    # for this family moved; the render rule itself is unchanged.
    assert target == "/runtime/home/.claude/.claude.json"
    assert json.loads(text)["mcpServers"]["web-tools"]["command"] == "/bin/web-tools"
    assert json.loads(text)["mcpServers"]["web-tools"]["env"] == {"API_KEY": "resolved-value"}

    target, text = render_for_family(
        canonical, profile_spec=spec("codex"),
        resolved_env={"API_KEY": "resolved-value"})
    assert target == "/runtime/home/.codex/config.toml"
    assert "[mcp_servers.web-tools]" in text
    assert 'command = "/bin/web-tools"' in text
    assert 'args = ["--stdio"]' in text
    assert 'API_KEY = "resolved-value"' in text

    # A family that declares no MCP slot is refused, never approximated.
    with pytest.raises(McpRenderError) as unsupported:
        render_for_family(canonical, profile_spec=spec("pi"), resolved_env={})
    assert unsupported.value.code == "ASSET_SLOT_UNSUPPORTED"

    # A missing credential value refuses before any config text exists.
    with pytest.raises(McpRenderError) as unresolved:
        render_for_family(canonical, profile_spec=spec("qwen"), resolved_env={})
    assert unresolved.value.code == "MCP_CREDENTIAL_UNRESOLVED"


def test_assets_are_catalogued_bound_and_never_carry_content(tmp_path):
    from ordessa_server_compat.assets.records import AssetRecords, asset_view
    from ordessa_server.idempotency import IdempotentRecords
    from pacthold_runtime_compat.storage import Database

    database = Database(tmp_path / "data")
    database.initialize()
    records = AssetRecords(database, IdempotentRecords(database))
    kind, published = records.publish(
        key="a", request_digest="a", kind="mcp", name="web-tools", revision=1,
        digest="sha256:" + "1" * 64, source="hub:example.test/catalog")
    assert kind == "published" and published["source"].startswith("hub:")

    # One more revision of the same asset moves `latest_revision` and keeps
    # the source unless the caller states a new one.
    updated = records.publish(
        key="b", request_digest="b", kind="mcp", name="web-tools", revision=2,
        digest="sha256:" + "2" * 64, asset_id=published["asset_id"])[1]
    assert updated["latest_revision"] == 2 and updated["source"].startswith("hub:")

    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_profiles(id,version,name,harness_type,config_revision,"
            "native_generation,config_object_digest,created_at,updated_at) "
            "VALUES ('profile_1',1,'role','codex',1,0,'sha256:x','t','t')"
        )
    binding = records.bind(profile_id="profile_1", asset_id=published["asset_id"])
    assert binding["enabled"] is True and binding["revision"] == 2
    assert records.bindings("profile_1") == [binding]
    records.bind(profile_id="profile_1", asset_id=published["asset_id"], revision=1,
                 enabled=False)
    disabled = records.bindings("profile_1")[0]
    assert disabled["revision"] == 1 and disabled["enabled"] is False
    assert records.bindings("profile_1", enabled_only=True) == []

    view = asset_view(records.get(published["asset_id"]))
    assert "content" not in json.dumps(view) and view["digest"].startswith("sha256:")

    # An unpublished revision cannot be bound.
    from ordessa_server.errors import ServerError

    with pytest.raises(ServerError) as unknown:
        records.bind(profile_id="profile_1", asset_id=published["asset_id"], revision=9)
    assert unknown.value.code == "ASSET_REVISION_UNKNOWN"


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap is required")
def test_a_bound_mcp_asset_is_rendered_and_materialised_without_writeback(tmp_path):
    """Order 58 G2/G3/G4 on the local channel, end to end.

    A bound MCP asset is rendered for the family (registry-declared target and
    key), the credential reference resolves through the secret store, and the
    file appears in the Profile's own home at the declared path - while the
    stored definition keeps the reference, not the value, and nothing is read
    back (assets have zero writeback).
    """
    from fastapi.testclient import TestClient

    from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
    from ordessa_server.transport.http import create_app
    from pacthold.storage.secrets import MemorySecretStore

    import ordessa_server_compat.composition as runtime_module

    peer_source = "tests/harness_remote/home_probe_acp_peer.mjs"
    peer_bytes = REPO / "apps" / "server" / "tests" / "fixtures" / "home_probe_acp_peer.mjs"
    deployment = {
        "schemaVersion": 1,
        "harnesses": [{
            "id": "claude-code", "capabilityClaims": {"stream": True},
            "adapter": {"command": "/usr/bin/node", "args": [], "source": peer_source},
            "stateProjection": {"target": "/runtime/home/.claude"},
            "timeoutMs": 60_000,
        }],
    }
    original_file = runtime_module._sidecar_deployment_file

    def deployment_file(root, relative):
        if relative == peer_source:
            return peer_bytes.read_bytes()
        return original_file(root, relative)

    runtime_module._sidecar_deployment_file = deployment_file
    secrets = MemorySecretStore(values={"locator_1": b"resolved-secret"})
    try:
        (tmp_path / "project").mkdir(exist_ok=True)
        document = tmp_path / "deployment.json"
        document.write_text(json.dumps(deployment), encoding="utf-8")
        runtime = build_runtime_from_sidecar_deployment(
            tmp_path / "server", document, plugin_root=PLUGIN, secret_store=secrets)
        runtime.start()
        # The domains this test seeds are the ones the running round provides:
        # resolved from the plugin host's declared ports, the same objects the
        # wire reads (T014-S1b removed the runtime's business facade fields).
        repository = runtime.plugin_host.provided_port("product.repository")
        mcp_assets = runtime.plugin_host.provided_port("asset.mcp")
        asset_records = runtime.plugin_host.provided_port("asset.records")
        hook_records = runtime.plugin_host.provided_port("hook.records")
        repository.register_credential("credential_1", "api-key", "locator_1")
        facts = mcp_assets.install({
            "name": "web-tools",
            "transport": {"stdio": {"command": "/bin/web-tools", "args": ["--stdio"]}},
        }, asset_id="web-tools", revision=1)
        published = asset_records.publish(
            key="a", request_digest="a", kind="mcp", name="web-tools", revision=1,
            digest=facts["digest"], source="local:test", asset_id="web-tools")[1]
        assert published["asset_id"] == "web-tools", published
        profile = repository.profiles.create(
            key="p", request_digest="p", name="role", harness_type="claude-code",
            config_digest=runtime.objects.publish(
                b'{"schema_version":1,"harness_type":"claude-code","configuration":{}}').digest,
            credential_id="credential_1")[1]
        asset_records.bind(profile_id=profile["profile_id"],
                           asset_id=published["asset_id"])
        # Order 59: an enabled hook joins the same document (claude keeps hooks
        # in settings.json under the `hooks` key).
        hook = hook_records.create(
            key="h", request_digest="h", family="claude-code", name="guard-bash",
            model={"event": "PreToolUse", "matcher": "Bash",
                   "handlers": [{"type": "command", "command": "/bin/guard --check"}]})[1]
        hook_records.set_enabled(hook_id=hook["hook_id"], enabled=True)

        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            token = runtime.token
            opened = client.post("/wire/v1/workspaces.open", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": "o", "method": "workspaces.open",
                "params": {"requestId": "asset-open-1", "path": str(tmp_path / "project"),
                           "environment": {"kind": "local", "host": None, "user": None}},
            }).json()["result"]
            sent = client.post("/wire/v1/sessions.createAndSend", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": "s", "method": "sessions.createAndSend",
                "params": {"requestId": "asset-turn-1", "workspaceId": opened["workspace"]["id"],
                           "profileId": profile["profile_id"], "overrides": [],
                           "message": {"text": "hello", "attachments": []}},
            }).json()["result"]
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                session = runtime.plugin_host.provided_port('product.repository').get_session(sent["session"]["id"])
                if session["turns"] and session["turns"][0]["state"] in {"completed", "failed"}:
                    break
                time.sleep(0.05)
            assert session["turns"][0]["state"] == "completed", session["turns"][0]

        role = next(item for item in (tmp_path / "server" / "profiles").iterdir()
                    if item.is_dir() and item.name != "_sessions")
        # 086 stage 1: MCP servers and hooks are two different files for this
        # family - `mcpServers` in `.claude.json` (the path the CLI reads),
        # `hooks` in `settings.json` (59's pin, unchanged).
        mcp_document = json.loads(
            (role / ".claude" / ".claude.json").read_text(encoding="utf-8"))
        assert mcp_document["mcpServers"]["web-tools"]["command"] == "/bin/web-tools"
        assert mcp_document["mcpServers"]["web-tools"]["args"] == ["--stdio"]
        rendered = json.loads((role / ".claude" / "settings.json").read_text(encoding="utf-8"))
        hook_document = rendered["hooks"]["PreToolUse"][0]
        assert hook_document["matcher"] == "Bash"
        assert hook_document["hooks"][0]["command"] == "/bin/guard --check"
        # Nothing in the file is a credential value, and the audit (which
        # scans the home for the injected material) passed on this turn.
        assert "resolved-secret" not in (role / ".claude" / "settings.json").read_text()
        assert "resolved-secret" not in (role / ".claude" / ".claude.json").read_text()

        # A server that carries credential references is refused until the
        # family's injection path is pinned: the value must never land in a
        # durable config file (order 58 G5; the audit enforces it too).
        runtime.plugin_host.provided_port('asset.mcp').install({
            "name": "needs-key",
            "transport": {"stdio": {
                "command": "/bin/needs-key",
                "env": {"API_KEY": {"credentialRef": "credential_1"}},
            }},
        }, asset_id="needs-key", revision=1)
        from ordessa_server_compat.assets.mcp import definition_digest

        needs_key = runtime.plugin_host.provided_port('asset.mcp').read(asset_id="needs-key", revision=1)
        runtime.plugin_host.provided_port('asset.records').publish(
            key="b", request_digest="b", kind="mcp", name="needs-key", revision=1,
            digest=definition_digest(needs_key), asset_id="needs-key")
        runtime.plugin_host.provided_port('asset.records').bind(profile_id=profile["profile_id"], asset_id="needs-key")
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            token = runtime.token
            refused = client.post("/wire/v1/sessions.send", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": "s2", "method": "sessions.send",
                "params": {"requestId": "asset-turn-2", "sessionId": sent["session"]["id"],
                           "overrides": [],
                           "message": {"text": "hello again", "attachments": []}},
            }).json()
            assert "error" not in refused, refused
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                session = runtime.plugin_host.provided_port('product.repository').get_session(sent["session"]["id"])
                if (len(session["turns"]) >= 2
                        and session["turns"][1]["state"] in {"completed", "failed"}):
                    break
                time.sleep(0.05)
            assert session["turns"][1]["state"] == "failed"
            assert session["turns"][1]["error_code"] in {
                "EXECUTION_FAILED", "MCP_CREDENTIAL_INJECTION_UNVERIFIED",
            }
    finally:
        runtime_module._sidecar_deployment_file = original_file


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap is required")
def test_the_assets_wire_face_publishes_binds_and_lists(tmp_path):
    """Order 58's wire face: publish a skill directory and an MCP definition,
    bind them to a Profile, list the catalogue and the bindings.

    First-hand at the wire: the catalogue view carries the digest but no
    content and no host paths; the binding reports the revision that will be
    materialised; an unpublished revision is refused.
    """
    from fastapi.testclient import TestClient

    from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
    from ordessa_server.transport.http import create_app
    from pacthold.storage.secrets import MemorySecretStore

    import ordessa_server_compat.composition as runtime_module

    peer_source = "tests/harness_remote/home_probe_acp_peer.mjs"
    peer_bytes = REPO / "apps" / "server" / "tests" / "fixtures" / "home_probe_acp_peer.mjs"
    deployment = {
        "schemaVersion": 1,
        "harnesses": [{
            "id": "codex", "capabilityClaims": {"stream": True},
            "adapter": {"command": "/usr/bin/node", "args": [], "source": peer_source},
            "stateProjection": {"target": "/runtime/home/.codex"},
            "timeoutMs": 60_000,
        }],
    }
    original_file = runtime_module._sidecar_deployment_file

    def deployment_file(root, relative):
        if relative == peer_source:
            return peer_bytes.read_bytes()
        return original_file(root, relative)

    runtime_module._sidecar_deployment_file = deployment_file
    try:
        document = tmp_path / "deployment.json"
        document.write_text(json.dumps(deployment), encoding="utf-8")
        runtime = build_runtime_from_sidecar_deployment(
            tmp_path / "server", document, plugin_root=PLUGIN,
            secret_store=MemorySecretStore(values={}))
        runtime.start()
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: does a thing\n---\n\nBody.\n",
            encoding="utf-8")
        profile = runtime.plugin_host.provided_port('product.repository').profiles.create(
            key="p", request_digest="p", name="role", harness_type="codex",
            config_digest=runtime.objects.publish(
                b'{"schema_version":1,"harness_type":"codex","configuration":{}}').digest,
            credential_id=None)[1]

        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            token = runtime.token

            def call(method, params):
                return client.post(f"/wire/v1/{method}", headers={
                    "Authorization": f"Bearer {token}"}, json={
                    "jsonrpc": "2.0", "id": method, "method": method, "params": params,
                }).json()

            skill = call("assets.publishSkill", {
                "requestId": "wire-skill-1", "assetId": "my-skill", "revision": 1,
                "sourcePath": str(skill_dir),
            })["result"]["asset"]
            assert skill["kind"] == "skill" and skill["digest"].startswith("sha256:")
            assert skill["name"] == "my-skill" and "content" not in json.dumps(skill)

            mcp = call("assets.publishMcp", {
                "requestId": "wire-mcp-1", "assetId": "web-tools", "revision": 1,
                "definition": {"name": "web-tools",
                               "transport": {"stdio": {"command": "/bin/web-tools"}}},
            })["result"]["asset"]
            assert mcp["kind"] == "mcp" and mcp["digest"].startswith("sha256:")

            listing = call("assets.list", {})["result"]["assets"]
            assert sorted(item["assetId"] for item in listing) == ["my-skill", "web-tools"]

            bound = call("assets.bind", {
                "requestId": "wire-bind-1", "profileId": profile["profile_id"],
                "assetId": "my-skill",
            })["result"]["binding"]
            assert bound["revision"] == 1 and bound["enabled"] is True
            bindings = call("assets.bindings", {
                "profileId": profile["profile_id"]})["result"]["bindings"]
            assert [(item["assetId"], item["enabled"]) for item in bindings] == [("my-skill", True)]

            # An unpublished revision and a malformed definition are refused.
            refused = call("assets.bind", {
                "requestId": "wire-bind-2", "profileId": profile["profile_id"],
                "assetId": "my-skill", "revision": 5,
            })
            assert "error" in refused
            bad = call("assets.publishMcp", {
                "requestId": "wire-mcp-2", "assetId": "bad-server", "revision": 1,
                "definition": {"name": "bad-server",
                               "transport": {"stdio": {"command": "relative"}}},
            })
            assert "error" in bad and "MCP_DEFINITION_INVALID" in bad["error"]["message"]

            unbound = call("assets.unbind", {
                "requestId": "wire-unbind-1", "profileId": profile["profile_id"],
                "assetId": "my-skill"})["result"]
            assert unbound["unbound"] is True
            assert call("assets.bindings", {
                "profileId": profile["profile_id"]})["result"]["bindings"] == []

            # G7: sync a directory source through the wire, then install one
            # entry from the snapshot; the annotation reports it installed.
            source = _catalog_source(tmp_path / "hub")
            # A fresh entry name, so "installed" in the annotation is this
            # install's fact rather than an earlier publish's.
            (source / "mcp" / "calendar.json").write_text(json.dumps({
                "name": "calendar-tools",
                "transport": {"stdio": {"command": "/bin/calendar-tools"}},
            }), encoding="utf-8")
            index = json.loads((source / "index.json").read_text(encoding="utf-8"))
            index["entries"].append({"kind": "mcp", "name": "calendar-tools",
                                     "path": "mcp/calendar.json",
                                     "origin": "example.test/mcp/calendar-tools"})
            (source / "index.json").write_text(json.dumps(index), encoding="utf-8")
            catalog = call("assets.syncCatalog", {
                "requestId": "wire-sync-1", "sourceId": "community",
                "sourcePath": str(source)})["result"]["catalog"]
            assert catalog["digest"].startswith("sha256:")
            before = {item["name"]: item["installed"] for item in catalog["entries"]}
            # my-skill and web-tools were published earlier in this test, so
            # only the fresh entry is not yet in the catalogue.
            assert before == {"my-skill": True, "web-tools": True, "calendar-tools": False}, before
            installed = call("assets.installFromCatalog", {
                "requestId": "wire-install-1", "sourceId": "community",
                "entryName": "calendar-tools", "revision": 1})["result"]["installed"]
            assert installed["source"].startswith(catalog["digest"] + ":")
            refreshed = call("assets.catalog", {"sourceId": "community"})["result"]["catalog"]
            by_name = {item["name"]: item for item in refreshed["entries"]}
            assert by_name["calendar-tools"]["installed"] is True
            assert by_name["calendar-tools"]["installedDigest"] == installed["digest"]
            # A failed sync leaves the snapshot as it was.
            (source / "index.json").write_text("{ nope", encoding="utf-8")
            refused_sync = call("assets.syncCatalog", {
                "requestId": "wire-sync-2", "sourceId": "community",
                "sourcePath": str(source)})
            assert "error" in refused_sync
            assert call("assets.catalog", {"sourceId": "community"})["result"]["catalog"] == refreshed

            # G6: probe a fake stdio server through the wire.
            fake = REPO / "apps" / "server" / "tests" / "fixtures" / "fake_mcp_server.py"
            probe = call("assets.probe", {
                "definition": {"name": "fake", "transport": {"stdio": {
                    "command": "/usr/bin/python3", "args": [str(fake)]}}}})
            assert probe["result"]["probe"]["serverName"] == "fake-mcp"
            dead = call("assets.probe", {
                "definition": {"name": "dead", "transport": {"stdio": {
                    "command": "/nonexistent/binary"}}}})
            assert "error" in dead and "PROBE_SPAWN_FAILED" in dead["error"]["message"]
    finally:
        runtime_module._sidecar_deployment_file = original_file


# -- the directory-shaped hub and the MCP probe (order 58 G7/G6) -----------


def _catalog_source(root: pathlib.Path) -> pathlib.Path:
    source = root / "source"
    skill = source / "skills" / "my-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: does a thing\n---\n\nBody.\n", encoding="utf-8")
    (source / "mcp" / "server.json").parent.mkdir(parents=True)
    (source / "mcp" / "server.json").write_text(json.dumps({
        "name": "web-tools", "transport": {"stdio": {"command": "/bin/web-tools"}},
    }), encoding="utf-8")
    (source / "index.json").write_text(json.dumps({
        "schema_version": 1,
        "entries": [
            {"kind": "skill", "name": "my-skill", "path": "skills/my-skill",
             "origin": "example.test/skills/my-skill", "description": "does a thing"},
            {"kind": "mcp", "name": "web-tools", "path": "mcp/server.json",
             "origin": "example.test/mcp/web-tools"},
        ],
    }), encoding="utf-8")
    return source


def test_the_catalog_snapshots_and_installs_with_pinned_provenance(tmp_path):
    from ordessa_server_compat.assets.catalog import CatalogError, CatalogStore
    from ordessa_server_compat.assets.mcp import McpAssetStore
    from ordessa_server_compat.assets.records import AssetRecords
    from ordessa_server_compat.assets.skills import SkillAssetStore
    from ordessa_server.idempotency import IdempotentRecords
    from pacthold_runtime_compat.storage import Database

    database = Database(tmp_path / "data")
    database.initialize()
    records = AssetRecords(database, IdempotentRecords(database))
    assets_root = tmp_path / "assets"
    catalog = CatalogStore(assets_root / "catalogs")
    skills = SkillAssetStore(assets_root)
    mcp = McpAssetStore(assets_root)

    source = _catalog_source(tmp_path)
    snapshot = catalog.sync(source_id="community", source_path=source)
    assert snapshot["digest"].startswith("sha256:")
    assert len(snapshot["entries"]) == 2

    annotated = catalog.annotate(snapshot, installed={})
    assert [item["installed"] for item in annotated] == [False, False]

    skill = catalog.install_entry(snapshot=snapshot, entry_name="my-skill", revision=1,
                                  records=records, skills=skills, mcp=mcp)
    assert skill["source"] == f"{snapshot['digest']}:example.test/skills/my-skill"
    server = catalog.install_entry(snapshot=snapshot, entry_name="web-tools", revision=1,
                                   records=records, skills=skills, mcp=mcp)
    assert server["kind"] == "mcp"

    listed = {row["id"]: row for row in records.list()}
    assert listed["my-skill"]["source"].endswith("example.test/skills/my-skill")
    assert records.bindings  # attribute exists; no binding yet

    # A failed sync leaves the previous snapshot exactly as it was.
    (source / "index.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(CatalogError) as refused:
        catalog.sync(source_id="community", source_path=source)
    assert refused.value.code == "CATALOG_INVALID"
    assert catalog.snapshot("community") == snapshot

    # The payload resolves inside the source it came from, and an unknown
    # entry is a typed refusal.
    with pytest.raises(CatalogError) as unknown:
        catalog.payload_path(snapshot, "no-such-entry")
    assert unknown.value.code == "CATALOG_ENTRY_UNKNOWN"


def test_a_catalog_index_with_unknown_or_escaping_entries_is_refused():
    from ordessa_server_compat.assets.catalog import CatalogError, parse_index

    def index(entries):
        return json.dumps({"schema_version": 1, "entries": entries}).encode()

    with pytest.raises(CatalogError) as escaping:
        parse_index(index([{"kind": "skill", "name": "x", "path": "../escape",
                            "origin": "o"}]))
    assert escaping.value.code == "CATALOG_INVALID"
    with pytest.raises(CatalogError) as origin:
        parse_index(index([{"kind": "skill", "name": "x", "path": "x"}]))
    assert origin.value.code == "CATALOG_ORIGIN_MISSING"
    with pytest.raises(CatalogError) as kind:
        parse_index(index([{"kind": "hook", "name": "x", "path": "x", "origin": "o"}]))
    assert kind.value.code == "CATALOG_INVALID"


def test_the_mcp_probe_answers_bounded_and_types_every_failure(tmp_path):
    from ordessa_server_compat.assets.mcp_probe import McpProbeError, probe_stdio

    server = REPO / "apps" / "server" / "tests" / "fixtures" / "fake_mcp_server.py"
    ok = probe_stdio("/usr/bin/python3", args=[str(server)], timeout=5.0)
    assert ok["status"] == "ok" and ok["serverName"] == "fake-mcp"

    with pytest.raises(McpProbeError) as command:
        probe_stdio("relative-command")
    assert command.value.code == "PROBE_COMMAND_INVALID"

    with pytest.raises(McpProbeError) as spawn:
        probe_stdio("/nonexistent/server-binary")
    assert spawn.value.code == "PROBE_SPAWN_FAILED"

    # The failure modes are selected by the child's own environment; the probe
    # hands it a minimal one, so the modes are chosen by the fixture's default
    # plus a wrapper script for silence/garbage/oversize.
    def probe_with(mode: str, **kwargs):
        wrapper = tmp_path / f"server-{mode}.py"
        wrapper.write_text(
            "import os, sys\n"
            f"os.environ['FAKE_MCP_MODE'] = {mode!r}\n"
            f"sys.argv = ['fake', {str(server)!r}]\n"
            f"exec(open({str(server)!r}).read())\n",
            encoding="utf-8",
        )
        return probe_stdio("/usr/bin/python3", args=[str(wrapper)], **kwargs)

    with pytest.raises(McpProbeError) as timeout:
        probe_with("silent", timeout=0.5)
    assert timeout.value.code == "PROBE_TIMEOUT"

    with pytest.raises(McpProbeError) as garbage:
        probe_with("garbage", timeout=5.0)
    assert garbage.value.code == "PROBE_FORMAT_INVALID"

    with pytest.raises(McpProbeError) as oversized:
        probe_with("oversized", timeout=5.0, max_bytes=4096)
    assert oversized.value.code == "PROBE_RESPONSE_TOO_LARGE"


def test_a_plugin_is_stored_as_code_with_a_digest_and_a_preview(tmp_path):
    """Order 59: OpenCode's hook is a code asset - stored verbatim, previewed.

    The refusals are the point: a binary, a symlink, an oversized file and a
    duplicate revision all refuse typed, and nothing ever assembles code from
    form fields - what the user wrote is what the digest covers.
    """
    from ordessa_server_compat.assets.plugins import PluginAssetError, preview_of, PluginAssetStore

    store = PluginAssetStore(tmp_path / "assets")
    source = tmp_path / "guard.js"
    source.write_text("export const Guard = async (input, output) => {\n"
                      "  output.blocked = true\n}\n", encoding="utf-8")
    facts = store.install(source, asset_id="guard", revision=1)
    assert facts["digest"].startswith("sha256:") and facts["filename"] == "guard.js"
    assert "Guard" in facts["preview"]
    assert store.verify(asset_id="guard", revision=1, expected_digest=facts["digest"]) is True
    name, content = store.read(asset_id="guard", revision=1)
    assert name == "guard.js" and content == source.read_bytes()

    with pytest.raises(PluginAssetError) as exists:
        store.install(source, asset_id="guard", revision=1)
    assert exists.value.code == "PLUGIN_REVISION_EXISTS"

    binary = tmp_path / "bad.js"
    binary.write_bytes(b"\xff\xfe\x00binary")
    with pytest.raises(PluginAssetError) as not_text:
        store.install(binary, asset_id="bad", revision=1)
    assert not_text.value.code == "PLUGIN_NOT_TEXT"

    link = tmp_path / "link.js"
    os.symlink(source, link)
    with pytest.raises(PluginAssetError) as linked:
        store.install(link, asset_id="linked", revision=1)
    assert linked.value.code == "PLUGIN_ASSET_INVALID"

    wrong_suffix = tmp_path / "hook.py"
    wrong_suffix.write_text("print('nope')\n", encoding="utf-8")
    with pytest.raises(PluginAssetError) as suffix:
        store.install(wrong_suffix, asset_id="pyscript", revision=1)
    assert suffix.value.code == "PLUGIN_ASSET_INVALID"

    oversized = tmp_path / "big.js"
    oversized.write_text("x" * (256 * 1024 + 1), encoding="utf-8")
    with pytest.raises(PluginAssetError) as bounds:
        store.install(oversized, asset_id="big", revision=1)
    assert bounds.value.code == "PLUGIN_ASSET_OUTSIDE_BOUNDS"

    # The preview is bounded and marks its own truncation.
    long_preview = preview_of("\n".join(f"line {index}" for index in range(100)).encode())
    assert long_preview.endswith("…") and long_preview.count("\n") <= 24


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap is required")
def test_assets_publish_plugin_over_the_wire_returns_a_preview(tmp_path):
    from fastapi.testclient import TestClient

    from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
    from ordessa_server.transport.http import create_app
    from pacthold.storage.secrets import MemorySecretStore

    import ordessa_server_compat.composition as runtime_module

    peer_source = "tests/harness_remote/home_probe_acp_peer.mjs"
    peer_bytes = REPO / "apps" / "server" / "tests" / "fixtures" / "home_probe_acp_peer.mjs"
    deployment = {"schemaVersion": 1, "harnesses": [{
        "id": "codex", "capabilityClaims": {"stream": True},
        "adapter": {"command": "/usr/bin/node", "args": [], "source": peer_source},
        "stateProjection": {"target": "/runtime/home/.codex"},
        "timeoutMs": 60_000}]}
    original_file = runtime_module._sidecar_deployment_file

    def deployment_file(root, relative):
        if relative == peer_source:
            return peer_bytes.read_bytes()
        return original_file(root, relative)

    runtime_module._sidecar_deployment_file = deployment_file
    try:
        document = tmp_path / "deployment.json"
        document.write_text(json.dumps(deployment), encoding="utf-8")
        runtime = build_runtime_from_sidecar_deployment(
            tmp_path / "server", document, plugin_root=PLUGIN,
            secret_store=MemorySecretStore(values={}))
        runtime.start()
        plugin = tmp_path / "guard.js"
        plugin.write_text("export const Guard = async () => {}\n", encoding="utf-8")
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            token = runtime.token
            response = client.post("/wire/v1/assets.publishPlugin", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": "p", "method": "assets.publishPlugin",
                "params": {"requestId": "plugin-publish-1", "assetId": "guard",
                           "revision": 1, "sourcePath": str(plugin)},
            }).json()["result"]
            assert response["asset"]["kind"] == "plugin"
            assert response["asset"]["digest"].startswith("sha256:")
            assert "Guard" in response["preview"]
            listed = client.post("/wire/v1/assets.list", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": "l", "method": "assets.list", "params": {},
            }).json()["result"]["assets"]
            assert [item["kind"] for item in listed] == ["plugin"]
    finally:
        runtime_module._sidecar_deployment_file = original_file
