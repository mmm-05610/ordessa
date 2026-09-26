"""Order 60 B: per-tool permission rules, last-match-wins, presets, refusals.

The counterexamples the order names: an unknown key, an unknown action, an
out-of-range timeout-analog (here: a malformed pattern), the last-match-wins
boundary, and the rule that an unmatched target falls back to the preset
rather than to `allow`.
"""
from __future__ import annotations

import pytest

from ordessa_server.profiles.permissions import (
    PRESET_ACTIONS,
    PermissionRuleError,
    effective_rules,
    preset_rules,
    resolve,
    resolve_all,
    validate_rules,
)


def test_last_match_wins_and_the_preset_catches_everything_else():
    rules = validate_rules([
        {"key": "bash", "action": "deny"},
        {"key": "bash", "pattern": "ls *", "action": "allow"},
        {"key": "edit", "pattern": "src/**", "action": "ask"},
    ])
    # The later, narrower rule wins for its target...
    assert resolve(rules, key="bash", target="ls -la", preset="plan") == "allow"
    # ...and the earlier broad rule still decides everything else.
    assert resolve(rules, key="bash", target="rm -rf /", preset="plan") == "deny"
    # A key with no rule falls back to the preset, never to `allow`.
    assert resolve(rules, key="webfetch", preset="plan") == PRESET_ACTIONS["plan"]
    assert resolve(rules, key="webfetch", preset="full-access") == "allow"
    # A pattern rule cannot speak about a targetless resolution.
    assert resolve(rules, key="edit", preset="default") == "ask"


def test_presets_expand_to_explicit_rules_and_overrides_append():
    plan = preset_rules("plan")
    assert {"key": "edit", "pattern": None, "action": "deny"} in plan
    # The user may override a preset rule with a later, narrower one.
    rules = effective_rules("plan", [{"key": "edit", "pattern": "docs/**", "action": "allow"}])
    assert resolve(rules, key="edit", target="docs/readme.md", preset="plan") == "allow"
    assert resolve(rules, key="edit", target="src/main.py", preset="plan") == "deny"


def test_unknown_keys_actions_patterns_and_shapes_refuse_typed():
    with pytest.raises(PermissionRuleError) as key:
        validate_rules([{"key": "shell", "action": "allow"}])
    assert key.value.code == "PERMISSION_KEY_UNSUPPORTED" and key.value.index == 0

    with pytest.raises(PermissionRuleError) as action:
        validate_rules([{"key": "bash", "action": "maybe"}])
    assert action.value.code == "PERMISSION_ACTION_UNSUPPORTED"

    with pytest.raises(PermissionRuleError) as pattern:
        validate_rules([{"key": "bash", "pattern": "a b\nc", "action": "ask"}])
    assert pattern.value.code == "PERMISSION_PATTERN_INVALID"

    with pytest.raises(PermissionRuleError) as shape:
        validate_rules([{"key": "bash", "action": "ask", "note": "x"}])
    assert shape.value.code == "PERMISSION_RULE_INVALID"

    with pytest.raises(PermissionRuleError) as preset:
        resolve([], key="bash", preset="yolo")
    assert preset.value.code == "PERMISSION_PRESET_UNSUPPORTED"

    with pytest.raises(PermissionRuleError):
        resolve([], key="not-a-tool")


def test_the_frozen_posture_states_every_key_and_every_named_target():
    rules = effective_rules("default", [
        {"key": "bash", "pattern": "git *", "action": "allow"},
        {"key": "bash", "action": "ask"},
    ])
    posture = resolve_all(rules, preset="default", targets={"bash": ("git status", "rm -rf /")})
    assert posture["preset"] == "default"
    assert set(posture["keys"]) == {
        "read", "edit", "bash", "task", "external_directory", "webfetch", "skill"}
    assert posture["targets"]["bash"] == {"git status": "ask", "rm -rf /": "ask"}
    # Order matters inside the set: with the allow first, the broad ask wins
    # for the git command too - the frozen posture shows exactly that.
    rules_reversed = effective_rules("default", [
        {"key": "bash", "action": "ask"},
        {"key": "bash", "pattern": "git *", "action": "allow"},
    ])
    posture_reversed = resolve_all(rules_reversed, targets={"bash": ("git status",)})
    assert posture_reversed["targets"]["bash"]["git status"] == "allow"


def test_the_posture_is_stored_validated_and_frozen_into_the_next_turn(tmp_path):
    """Order 60 A/G1: an edited rule set is stored ordered, refused typed when
    illegal, and shows up in the *next* turn's frozen effective configuration."""
    import json

    from ordessa_server.errors import ServerError
    from ordessa_server.idempotency import IdempotentRecords
    from ordessa_server.profiles import ProfileRecords
    from ordessa_server_compat.sessions import SessionRecords
    from pacthold.storage import Database

    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    profiles = ProfileRecords(database, idempotency)
    sessions = SessionRecords(database, idempotency)

    profile = profiles.create(
        key="p", request_digest="p", name="role", harness_type="claude-code",
        config_digest="sha256:" + "0" * 64, credential_id=None)[1]

    # An illegal rule refuses before storage, with the rule's own code.
    with pytest.raises(ServerError) as refused:
        profiles.set_permissions(
            profile_id=profile["profile_id"], preset="default",
            rules=[{"key": "shell", "action": "allow"}],
            expected_version=profiles.get(profile["profile_id"])["version"],
            key="perm-1", request_digest="perm-1")
    assert refused.value.code == "PERMISSION_KEY_UNSUPPORTED"

    written = profiles.set_permissions(
        profile_id=profile["profile_id"], preset="plan",
        rules=[{"key": "edit", "pattern": "docs/**", "action": "allow"}],
        expected_version=profiles.get(profile["profile_id"])["version"],
        key="perm-2", request_digest="perm-2")[1]
    rules = json.loads(profiles.get(profile["profile_id"])["permission_rules_json"])
    assert rules[0]["key"] == "edit" and rules[0]["action"] == "deny"  # the preset
    assert rules[-1]["pattern"] == "docs/**"                          # then the override

    # The frozen posture: resolve_all over the stored rules, preset `plan`.
    posture = resolve_all(rules, preset="plan")
    assert posture["keys"]["edit"] == "deny" and posture["keys"]["bash"] == "deny"
    assert posture["keys"]["read"] == "ask"
    assert written["profile"]["id"] == profile["profile_id"]


def test_sessions_belong_to_the_workspace_and_turns_carry_the_profile(tmp_path):
    """Order 60 C: the corrected ownership, pinned as a rule.

    A Session is listed by its *workspace*; the Profile is the current binding
    and each Turn records its own. So: two Sessions of one workspace bound to
    two different Profiles both list; switching one Session's Profile changes
    the binding field, not which workspace owns it; and the wire's session
    listing accepts no profile as a query axis.
    """
    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app

    runtime = build_runtime(tmp_path / "server")
    runtime.start()
    profiles = runtime.repository.profiles
    workspaces = runtime.repository.workspaces
    # Alias discipline: stopped-runtime facades read None; the round's record
    # objects stay usable across client sessions over the same database.
    sessions_repo = runtime.repository.sessions
    workspace = workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/workspace", connection_id="connection")[1]
    digests = {}
    for harness in ("claude-code", "codex"):
        digests[harness] = runtime.objects.publish(
            f'{{"schema_version":1,"harness_type":"{harness}","configuration":{{}}}}'.encode()
        ).digest
    first = profiles.create(key="p1", request_digest="p1", name="role-a",
                            harness_type="claude-code", config_digest=digests["claude-code"],
                            credential_id=None)[1]
    second = profiles.create(key="p2", request_digest="p2", name="role-b",
                             harness_type="codex", config_digest=digests["codex"],
                             credential_id=None)[1]
    from ordessa_server_compat.sessions import SessionService
    from ordessa_server.idempotency import IdempotentRecords

    service = SessionService(runtime.repository.sessions, IdempotentRecords(runtime.database),
                             runtime.objects, harnesses=runtime.harnesses,
                             profiles=profiles, credentials=runtime.repository.credentials,
                             execution=None)
    session_a = service.create_session("s1", {
        "workspace_id": workspace["workspace_id"], "profile_id": first["profile_id"]})[1]
    session_b = service.create_session("s2", {
        "workspace_id": workspace["workspace_id"], "profile_id": second["profile_id"]})[1]

    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        token = runtime.token

        listed = client.post("/wire/v1/sessions.list", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "l", "method": "sessions.list",
            "params": {"includeArchived": False,
                       "workspaceId": workspace["workspace_id"]},
        }).json()["result"]["items"]
        assert sorted(item["id"] for item in listed) == sorted(
            [session_a["session_id"], session_b["session_id"]])
        # The binding is visible, per session, and two bindings coexist.
        assert {item["id"]: item["profileId"] for item in listed} == {
            session_a["session_id"]: first["profile_id"],
            session_b["session_id"]: second["profile_id"],
        }
        # There is no profile axis: asking for one is an invalid parameter,
        # not a filter that silently returns someone's "own" sessions.
        refused = client.post("/wire/v1/sessions.list", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "l2", "method": "sessions.list",
            "params": {"includeArchived": False, "profileId": first["profile_id"]},
        }).json()
        assert "error" in refused and refused["error"]["code"] == "INVALID_REQUEST"

    # A same-family switch moves the binding; the workspace still owns the
    # session. A cross-family one is refused - changing family is the clone
    # rule (order 60 G5), not a switch.
    third = profiles.create(key="p3", request_digest="p3", name="role-c",
                            harness_type="claude-code", config_digest=digests["claude-code"],
                            credential_id=None)[1]
    with pytest.raises(Exception) as cross_family:
        sessions_repo.switch_profile(
            session_id=session_a["session_id"], profile_id=second["profile_id"],
            expected_version=sessions_repo.get_session(
                session_a["session_id"])["version"],
            request_id="switch-c0", request_digest="switch-c0")
    assert cross_family.value.code == "PROFILE_HARNESS_MISMATCH"
    sessions_repo.switch_profile(
        session_id=session_a["session_id"], profile_id=third["profile_id"],
        expected_version=sessions_repo.get_session(
            session_a["session_id"])["version"],
        request_id="switch-c1", request_digest="switch-c1")
    moved = sessions_repo.get_session(session_a["session_id"])
    assert moved["profile_id"] == third["profile_id"]
    assert moved["workspace_id"] == workspace["workspace_id"]


def test_clone_plans_what_travels_and_never_pretends_about_sessions():
    """Order 60 D: the migration plan, item by item.

    Same family reuses the family-specific records; another family translates
    the neutral ones (skills, MCP where the target declares the slot, hooks the
    target's schema accepts) and lists everything else with its reason. Native
    sessions never travel.
    """
    from ordessa_server.profiles.clone import CloneError, plan_migration
    from ordessa_harness.registry.loader import load_builtin_registry

    registry = load_builtin_registry()

    def spec(name):
        return registry.get(name).profile

    source = {
        "harness_type": "claude-code", "credential_id": "credential_1",
        "account_id": "account_1", "permission_preset": "plan",
        "permission_rules_json": '[{"key": "edit", "pattern": "docs/**", "action": "allow"}]',
    }
    bindings = [
        {"kind": "skill", "name": "my-skill", "revision": 1},
        {"kind": "mcp", "name": "web-tools", "revision": 1},
        {"kind": "plugin", "name": "guard", "revision": 1},
    ]
    hooks = [
        {"name": "guard-bash", "model": {"event": "PreToolUse", "matcher": "Bash",
         "handlers": [{"type": "command", "command": "/bin/guard", "timeout": 60,
                       "async": False}]}},
        {"name": "notify-hook", "model": {"event": "Notification",
         "handlers": [{"type": "prompt", "prompt": "say hi", "timeout": 60, "async": False}]}},
    ]

    # Same family: everything family-specific travels.
    same = plan_migration(source=source, target_harness="claude-code",
                          asset_bindings=bindings, hooks=hooks,
                          registry_profile=spec("claude-code"))
    assert same["sameFamily"] is True
    by_item = {entry["item"]: entry for entry in same["items"]}
    assert by_item["configuration"]["migrated"] and by_item["credential"]["migrated"]
    assert by_item["account"]["migrated"] and by_item["permissions"]["migrated"]
    assert same["permissions"]["preset"] == "plan"
    assert same["permissions"]["rules"][-1]["pattern"] == "docs/**"
    assert by_item["hook:guard-bash"]["migrated"] and by_item["hook:notify-hook"]["migrated"]
    assert by_item["native-sessions"]["migrated"] is False

    # Cross family to codex: the family-specific records are listed, not moved.
    cross = plan_migration(source=source, target_harness="codex",
                           asset_bindings=bindings, hooks=hooks,
                           registry_profile=spec("codex"))
    entries = {entry["item"]: entry for entry in cross["items"]}
    assert entries["configuration"]["migrated"] is False
    assert entries["credential"]["migrated"] is False
    assert entries["account"]["migrated"] is False
    assert entries["permissions"]["migrated"] is True          # neutral by design
    assert entries["skill:my-skill"]["migrated"] is True       # Agent Skills shape
    assert entries["mcp:web-tools"]["migrated"] is True        # codex declares the mcp slot
    assert entries["plugin:guard"]["migrated"] is True         # delivered as a code asset
    # codex declares only command handlers, so the prompt hook is refused with
    # a reason instead of vanishing.
    assert entries["hook:guard-bash"]["migrated"] is True
    assert entries["hook:notify-hook"]["migrated"] is False
    assert "handler" in entries["hook:notify-hook"]["reason"]
    assert cross["refusedCount"] >= 4 and cross["migratedCount"] >= 4


def test_a_clone_row_records_its_origin_and_carries_only_what_the_plan_allows(tmp_path):
    from ordessa_server.idempotency import IdempotentRecords
    from ordessa_server.profiles import ProfileRecords
    from pacthold.storage import Database

    database = Database(tmp_path / "data")
    database.initialize()
    profiles = ProfileRecords(database, IdempotentRecords(database))
    source = profiles.create(key="s", request_digest="s", name="role",
                             harness_type="claude-code",
                             config_digest="sha256:" + "1" * 64,
                             credential_id=None)[1]
    profiles.set_permissions(
        profile_id=source["profile_id"], preset="plan", rules=[],
        expected_version=profiles.get(source["profile_id"])["version"],
        key="perm", request_digest="perm")

    clone = profiles.clone_from(
        source_id=source["profile_id"], name="clone", harness_type="codex",
        report={"sameFamily": False})
    assert clone["origin_profile_id"] == source["profile_id"]
    assert clone["cloned_at"] and clone["harness_type"] == "codex"
    # Cross family: the configuration object is *not* reused and the (absent)
    # credential is not invented; the neutral posture travels.
    assert clone["config_object_digest"] == ""
    assert clone["credential_id"] is None and clone["account_id"] is None
    assert clone["permission_preset"] == "plan"
    rules_json = clone["permission_rules_json"]
    assert rules_json and "deny" in rules_json


def test_the_clone_wire_face_returns_the_migration_report(tmp_path):
    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app

    runtime = build_runtime(tmp_path / "server")
    runtime.start()
    profile = runtime.repository.profiles.create(
        key="p", request_digest="p", name="role", harness_type="claude-code",
        config_digest=runtime.objects.publish(
            b'{"schema_version":1,"harness_type":"claude-code","configuration":{}}').digest,
        credential_id=None)[1]
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        token = runtime.token
        cloned = client.post("/wire/v1/profiles.clone", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "c", "method": "profiles.clone",
            "params": {"requestId": "clone-request-1", "profileId": profile["profile_id"],
                       "displayName": "role clone", "harness": "codex"},
        }).json()["result"]
        assert cloned["profile"]["harness"] == "codex"
        assert cloned["profile"]["originProfileId"] == profile["profile_id"]
        report = cloned["migration"]
        assert report["sameFamily"] is False
        items = {entry["item"]: entry for entry in report["items"]}
        assert items["native-sessions"]["migrated"] is False
        assert items["credential"]["migrated"] is False
        assert report["migratedCount"] + report["refusedCount"] == len(report["items"])

        # The same family reuses the configuration object and the credential
        # reference; the report says so.
        same = client.post("/wire/v1/profiles.clone", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "c2", "method": "profiles.clone",
            "params": {"requestId": "clone-request-2", "profileId": profile["profile_id"],
                       "displayName": "role clone same"},
        }).json()["result"]
        assert same["migration"]["sameFamily"] is True
        same_items = {entry["item"]: entry for entry in same["migration"]["items"]}
        assert same_items["configuration"]["migrated"] is True
        assert same_items["native-sessions"]["migrated"] is False


def test_a_clone_rebinds_exactly_the_migrated_assets_and_setpermissions_writes(tmp_path):
    """Order 60: the clone's bindings match its report, and the permission
    posture has a wire write path with the same refusals."""
    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app

    runtime = build_runtime(tmp_path / "server")
    runtime.start()
    source = runtime.repository.profiles.create(
        key="p", request_digest="p", name="role", harness_type="claude-code",
        config_digest=runtime.objects.publish(
            b'{"schema_version":1,"harness_type":"claude-code","configuration":{}}').digest,
        credential_id=None)[1]
    # One skill binding and one plugin binding on the source.
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: does a thing\n---\nBody.\n", encoding="utf-8")
    from pacthold.resource_contracts.runtime_artifacts import runtime_artifact_tree_digest

    runtime.skill_assets.install(skill_dir, asset_id="my-skill", revision=1)
    runtime.asset_records.publish(
        key="s", request_digest="s", kind="skill", name="my-skill", revision=1,
        digest=runtime_artifact_tree_digest(runtime.skill_assets.revision_dir("my-skill", 1)),
        asset_id="my-skill")
    plugin = tmp_path / "guard.js"
    plugin.write_text("export const Guard = async () => {}\n", encoding="utf-8")
    facts = runtime.plugin_assets.install(plugin, asset_id="guard", revision=1)
    runtime.asset_records.publish(
        key="pg", request_digest="pg", kind="plugin", name="guard", revision=1,
        digest=facts["digest"], asset_id="guard")
    runtime.asset_records.bind(profile_id=source["profile_id"], asset_id="my-skill")
    runtime.asset_records.bind(profile_id=source["profile_id"], asset_id="guard")

    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        token = runtime.token
        cloned = client.post("/wire/v1/profiles.clone", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "c", "method": "profiles.clone",
            "params": {"requestId": "clone-rebind-1", "profileId": source["profile_id"],
                       "displayName": "clone", "harness": "codex"},
        }).json()["result"]
        report = cloned["migration"]
        clone_id = cloned["profile"]["id"]
        # codex declares the mcp slot but has no skill slot in this fixture's
        # terms: whatever the plan said migrated is what got rebound.
        migrated = sorted(entry["item"] for entry in report["items"]
                          if entry["migrated"] and ":" in entry["item"])
        assert report["reboundAssets"] == migrated
        bound = runtime.asset_records.bindings(clone_id)
        assert sorted(item["assetId"] for item in bound) == [
            item.split(":", 1)[1] for item in migrated]

        # setPermissions: a valid write lands, an illegal rule refuses typed.
        written = client.post("/wire/v1/profiles.setPermissions", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "sp", "method": "profiles.setPermissions",
            "params": {"requestId": "set-permissions-1", "profileId": clone_id,
                       "expectedVersion": cloned["profile"]["version"],
                       "preset": "plan",
                       "rules": [{"key": "webfetch", "action": "deny"}]},
        }).json()["result"]["profile"]
        assert written["permissionPreset"] == "plan"
        assert written["permissionRules"][-1]["key"] == "webfetch"

        refused = client.post("/wire/v1/profiles.setPermissions", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "sp2", "method": "profiles.setPermissions",
            "params": {"requestId": "set-permissions-2", "profileId": clone_id,
                       "expectedVersion": written["version"], "preset": "plan",
                       "rules": [{"key": "shell", "action": "allow"}]},
        }).json()
        assert refused["error"]["details"]["internalCode"] == "PERMISSION_KEY_UNSUPPORTED"
