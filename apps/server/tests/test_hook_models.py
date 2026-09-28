"""Order 59: the per-family hook models, the ledger, and the refusals.

The counterexamples the order asks for live here: an event the family does not
declare, a matcher where the family has none, a timeout out of range, a
handler type the family does not accept, and the rule that a hook is disabled
until a user enables it - with the exact command text visible first.
"""
from __future__ import annotations

import pytest

from ordessa_server_compat.hooks.model import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
    HookModelError,
    command_preview,
    schema_for,
    validate_model,
)
from ordessa_server_compat.hooks.records import HookRecords
from ordessa_server.idempotency import IdempotentRecords
from pacthold_runtime_compat.storage import Database


def _model(**overrides):
    model = {
        "event": "PreToolUse",
        "matcher": "Bash",
        "handlers": [{"type": "command", "command": "/bin/guard --check"}],
    }
    model.update(overrides)
    return model


def test_the_families_declare_their_own_models_and_unknown_ones_refuse():
    claude = schema_for("claude-code")
    codex = schema_for("codex")
    assert "PreToolUse" in claude.events and "PreToolUse" in codex.events
    assert claude.managed_only_flag == "disableAllHooks"
    assert codex.managed_only_flag == "hooks_only"
    # Codex declares only command handlers; claude declares the wider set.
    assert codex.handler_types == ("command",)
    assert "mcp_tool" in claude.handler_types

    with pytest.raises(HookModelError) as unsupported:
        schema_for("pi")
    assert unsupported.value.code == "HOOK_FAMILY_UNSUPPORTED"


def test_the_model_validates_and_canonicalises():
    canonical = validate_model("claude-code", _model())
    assert canonical["event"] == "PreToolUse" and canonical["matcher"] == "Bash"
    handler = canonical["handlers"][0]
    assert handler["type"] == "command" and handler["timeout"] == DEFAULT_TIMEOUT_SECONDS
    assert handler["async"] is False
    assert command_preview(canonical) == ["/bin/guard --check"]


def test_every_illegal_field_refuses_with_its_own_code():
    with pytest.raises(HookModelError) as event:
        validate_model("codex", _model(event="PreModelSwitch"))
    assert event.value.code == "HOOK_EVENT_UNSUPPORTED"

    with pytest.raises(HookModelError) as handler:
        validate_model("codex", _model(handlers=[{"type": "http", "url": "https://x.test"}]))
    assert handler.value.code == "HOOK_HANDLER_UNSUPPORTED"

    with pytest.raises(HookModelError) as timeout:
        validate_model("codex", _model(handlers=[
            {"type": "command", "command": "/bin/x", "timeout": MAX_TIMEOUT_SECONDS + 1}]))
    assert timeout.value.code == "HOOK_TIMEOUT_INVALID"

    with pytest.raises(HookModelError) as command:
        validate_model("codex", _model(handlers=[{"type": "command"}]))
    assert command.value.code == "HOOK_FIELD_INVALID"

    with pytest.raises(HookModelError) as shape:
        validate_model("codex", _model(extra=True))
    assert shape.value.code == "HOOK_MODEL_INVALID"

    # A loopback http handler is admissible for claude; a plain http one is not.
    with pytest.raises(HookModelError) as insecure:
        validate_model("claude-code", _model(handlers=[
            {"type": "http", "url": "http://example.test"}]))
    assert insecure.value.code == "HOOK_FIELD_INVALID"


def test_the_ledger_crud_keeps_hooks_disabled_until_enabled(tmp_path):
    database = Database(tmp_path / "data")
    database.initialize()
    records = HookRecords(database, IdempotentRecords(database))

    kind, created = records.create(
        key="a", request_digest="a", family="claude-code", name="guard-bash",
        model=_model())
    assert kind == "created" and created["enabled"] is False
    assert created["commands"] == ["/bin/guard --check"]
    hook_id = created["hook_id"]

    # An illegal edit is refused before storage; the stored model is untouched.
    from ordessa_server.errors import ServerError

    with pytest.raises(ServerError) as refused:
        records.update(hook_id=hook_id, model=_model(event="NotAnEvent"))
    assert refused.value.code == "HOOK_EVENT_UNSUPPORTED"
    assert records.get(hook_id)["model_json"] == records.get(hook_id)["model_json"]
    assert '"NotAnEvent"' not in records.get(hook_id)["model_json"]

    enabled = records.set_enabled(hook_id=hook_id, enabled=True)
    assert enabled["enabled"] is True
    assert [row["hook_id"] for row in records.enabled_for_family("claude-code")] == [hook_id]

    updated = records.update(hook_id=hook_id, model=_model(matcher="Edit"))
    assert updated["model"]["matcher"] == "Edit"

    records.set_enabled(hook_id=hook_id, enabled=False)
    assert records.enabled_for_family("claude-code") == []
    records.delete(hook_id=hook_id)
    assert records.list() == []

    # A hook with no command handler cannot be enabled: the switch would lie.
    declared_only = records.create(
        key="b", request_digest="b", family="claude-code", name="notify-only",
        model=_model(handlers=[{"type": "prompt", "prompt": "say hi"}]))[1]
    with pytest.raises(ServerError) as not_executable:
        records.set_enabled(hook_id=declared_only["hook_id"], enabled=True)
    assert not_executable.value.code == "HOOK_NOT_EXECUTABLE"


def test_hooks_render_in_the_families_own_shape_and_merge_into_one_document():
    from ordessa_server_compat.hooks.rendering import (
        merge_fragments,
        render_hooks_fragment,
    )

    canonical = validate_model("claude-code", _model())
    fragment = render_hooks_fragment("claude-code", [canonical])
    assert list(fragment) == ["PreToolUse"]
    group = fragment["PreToolUse"][0]
    assert group["matcher"] == "Bash"
    assert group["hooks"] == [{"type": "command", "command": "/bin/guard --check",
                              "timeout": DEFAULT_TIMEOUT_SECONDS, "async": False}]

    # Claude's settings.json gathers mcpServers and hooks as two keys; codex's
    # hooks.json is the fragment itself.
    merged = merge_fragments("/x/settings.json", [
        ("mcpServers", {"web-tools": {"command": "/bin/web-tools"}}),
        ("hooks", fragment),
    ])
    document = __import__("json").loads(merged)
    assert set(document) == {"mcpServers", "hooks"}
    assert document["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "/bin/guard --check"

    root = merge_fragments("/x/hooks.json", [(None, fragment)])
    assert set(__import__("json").loads(root)) == {"PreToolUse"}

    # Two fragments claiming one key refuse rather than overwrite.
    with pytest.raises(Exception) as conflict:
        merge_fragments("/x/settings.json", [("hooks", {}), ("hooks", {})])
    assert "HOOK_TARGET_CONFLICT" in str(conflict.value)


def test_trigger_facts_are_bounded_scanned_and_blocking_is_explicit(tmp_path):
    from ordessa_server_compat.hooks.triggers import (
        BLOCKING_EXIT_CODE,
        MAX_SUMMARY_CHARS,
        HookTriggerRecords,
        TriggerError,
        classify_exit,
    )

    database = Database(tmp_path / "data")
    database.initialize()
    hooks = HookRecords(database, IdempotentRecords(database))
    triggers = HookTriggerRecords(database)
    hook = hooks.create(key="a", request_digest="a", family="claude-code",
                        name="guard", model=_model())[1]

    ran = triggers.record(hook_id=hook["hook_id"], event="PreToolUse", exit_code=0,
                          output="checked\n")
    assert ran["effect"] == "ran" and ran["blocking"] is False

    blocked = triggers.record(hook_id=hook["hook_id"], event="PreToolUse",
                              exit_code=BLOCKING_EXIT_CODE, output="denied: rm -rf /\n")
    assert blocked["blocking"] is True and blocked["effect"] == "blocked"

    failed = triggers.record(hook_id=hook["hook_id"], event="PostToolUse", exit_code=1)
    assert failed["effect"] == "failed"

    long_text = "x" * (MAX_SUMMARY_CHARS + 100)
    truncated = triggers.record(hook_id=hook["hook_id"], event="Stop", exit_code=0,
                                output=long_text)
    assert truncated["truncated"] is True
    assert len(truncated["output_summary"]) == MAX_SUMMARY_CHARS

    # A summary carrying the execution's credential material is refused.
    with pytest.raises(TriggerError) as secret:
        triggers.record(hook_id=hook["hook_id"], event="Stop", exit_code=0,
                        output=b"leak: sk-abc123", forbidden=b"sk-abc123")
    assert secret.value.code == "HOOK_TRIGGER_CONTAINS_SECRET"

    with pytest.raises(TriggerError) as shape:
        triggers.record(hook_id=hook["hook_id"], event="Stop", exit_code="two")
    assert shape.value.code == "HOOK_TRIGGER_INVALID"

    assert classify_exit(BLOCKING_EXIT_CODE) == (True, "blocked")
    assert len(triggers.list(hook_id=hook["hook_id"])) == 4
    assert triggers.list(limit=2)  # newest first, bounded


def test_the_hooks_wire_face_creates_edits_enables_and_lists_triggers(tmp_path):
    """Order 59's wire face: the ledger's every product action, plus triggers.

    First-hand at the wire: a hook is created disabled with its commands
    visible; an illegal edit is refused with its own code; an unsupported
    family is refused; enabling works only for an executable hook; and the
    trigger query presents exit-2 as `blocked`.
    """
    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app

    runtime = build_runtime(tmp_path / "server")
    runtime.start()
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        token = runtime.token

        def call(method, params):
            return client.post(f"/wire/v1/{method}", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": method, "method": method, "params": params,
            }).json()

        created = call("hooks.create", {
            "requestId": "hook-create-1", "family": "claude-code", "name": "guard",
            "model": {"event": "PreToolUse", "matcher": "Bash",
                      "handlers": [{"type": "command", "command": "/bin/guard"}]},
        })["result"]["hook"]
        assert created["enabled"] is False
        assert created["commands"] == ["/bin/guard"]

        refused = call("hooks.create", {
            "requestId": "hook-create-2", "family": "pi", "name": "nope",
            "model": {"event": "PreToolUse",
                      "handlers": [{"type": "command", "command": "/bin/x"}]},
        })
        assert "error" in refused and refused["error"]["details"]["internalCode"] == "HOOK_FAMILY_UNSUPPORTED"

        illegal = call("hooks.update", {
            "requestId": "hook-update-1", "hookId": created["hookId"],
            "model": {"event": "NotAnEvent",
                      "handlers": [{"type": "command", "command": "/bin/x"}]},
        })
        assert illegal["error"]["details"]["internalCode"] == "HOOK_EVENT_UNSUPPORTED"

        enabled = call("hooks.setEnabled", {
            "requestId": "hook-enable-1", "hookId": created["hookId"],
            "enabled": True})["result"]["hook"]
        assert enabled["enabled"] is True
        listed = call("hooks.list", {"requestId": "hook-list-1"})["result"]["hooks"]
        assert [item["hookId"] for item in listed] == [created["hookId"]]

        # A trigger fact ingested into the ledger surfaces with its effect.
        runtime.plugin_host.provided_port('hook.triggers').record(
            hook_id=created["hookId"], event="PreToolUse", exit_code=2,
            output="denied\n")
        triggers = call("hooks.triggers", {
            "requestId": "hook-triggers-1", "hookId": created["hookId"]})["result"]["triggers"]
        assert triggers[0]["exitCode"] == 2 and triggers[0]["blocking"] is True
        assert triggers[0]["effect"] == "blocked" and triggers[0]["outputSummary"] == "denied\n"

        removed = call("hooks.delete", {
            "requestId": "hook-delete-1", "hookId": created["hookId"]})["result"]
        assert removed == {"deleted": True, "triggersRemoved": 1}
