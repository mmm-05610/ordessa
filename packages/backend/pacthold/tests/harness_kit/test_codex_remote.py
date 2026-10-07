from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tomllib

import pytest

from ordessa_harness_codex.contracts import CodexContinuationV1
from ordessa_harness_codex.remote import (
    build_remote_plan, classify_native_session_path, decode_codex_jsonl,
    materialize_remote_credential, validate_remote_configuration,
    _deepseek_model_catalog,
    build_acp_sidecar_projection,
)


def test_plan_owns_bounded_fresh_and_native_resume_argv():
    configuration = {"model": "gpt-fixture", "reasoning_effort": "high"}
    fresh = build_remote_plan(configuration, "hello", None)
    assert fresh.command[:4] == ("/runtime/bin/codex", "exec", "--color", "never")
    assert fresh.command[-1] == "-"
    assert "hello" not in fresh.command
    assert fresh.stdin == b"hello"
    assert set(fresh.environment) == {"HOME", "CODEX_HOME", "PATH", "LANG"}

    resumed = build_remote_plan(
        configuration, "continue", CodexContinuationV1("thread-fixture"),
    )
    assert resumed.command[:4] == (
        "/runtime/bin/codex", "exec", "resume", "thread-fixture",
    )
    assert resumed.continuation_thread_id == "thread-fixture"


def test_deepseek_credential_becomes_isolated_config_and_catalog():
    plan = build_remote_plan({
        "model": "deepseek-flash", "provider": "deepseek",
        "reasoning_effort": "high",
    }, "hello", None)
    projection = materialize_remote_credential(plan, b"sk-fixture_value_123456\n")
    assert plan.provider == "deepseek"
    assert "--ignore-user-config" not in plan.command
    assert projection.target == "/runtime/home/config.toml"
    assert b'https://api.deepseek.com/' in projection.content
    assert b'experimental_bearer_token = "sk-fixture_value_123456"' in projection.content
    assert b'model = "deepseek-flash"' in projection.content
    assert b'model_provider = "deepseek"' in projection.content
    assert b'preferred_auth_method = "apikey"' in projection.content
    assert b'forced_login_method = "api"' in projection.content
    assert b'model_reasoning_effort = "high"' in projection.content
    assert b'web_search = "disabled"' in projection.content
    assert b'model_catalog_json = "/runtime/home/models.json"' in projection.content
    assert b'wire_api = "responses"' in projection.content
    catalog = json.loads(projection.view_files["models.json"])
    assert hashlib.sha256(projection.view_files["models.json"]).hexdigest() == "bce20f679495809f4fa6e48672b6dcbab84b6adff5251890b6e6a21eddb9c12f"
    assert projection.view_files["models.json"] == _deepseek_model_catalog()
    assert {item["slug"] for item in catalog["models"]} == {"deepseek-flash", "deepseek-v4-pro"}
    expected_fields = {
        "slug", "prefer_websockets", "support_verbosity", "default_verbosity",
        "apply_patch_tool_type", "web_search_tool_type", "input_modalities",
        "supports_image_detail_original", "truncation_policy", "supports_parallel_tool_calls",
        "tool_mode", "multi_agent_version", "use_responses_lite", "include_skills_usage_instructions",
        "auto_review_model_override", "context_window", "max_context_window",
        "effective_context_window_percent", "auto_compact_token_limit", "comp_hash",
        "reasoning_summary_format", "default_reasoning_summary", "display_name", "description",
        "default_reasoning_level", "supported_reasoning_levels", "shell_type", "visibility",
        "minimal_client_version", "supported_in_api", "availability_nux", "upgrade", "priority",
        "model_messages", "experimental_supported_tools", "supports_search_tool", "default_service_tier",
        "supports_reasoning_summaries", "base_instructions",
    }
    assert all(set(item) == expected_fields for item in catalog["models"])
    assert projection.target == "/runtime/home/config.toml"
    assert "models.json" in projection.view_files
    assert "sk-fixture" not in repr(projection)


@pytest.mark.parametrize("value", [
    {},
    {"model": "bad model"},
    {"model": "ok", "argv": ["sh"]},
    {"model": "ok", "reasoning_effort": "unbounded"},
    {"model": "ok", "provider": "unknown"},
    {"model": "deepseek-chat", "provider": "deepseek"},
    {"model": "deepseek-v4-pro", "provider": "deepseek"},
])
def test_configuration_rejects_missing_or_injectable_fields(value):
    with pytest.raises(ValueError):
        validate_remote_configuration(value)


def test_acp_sidecar_projection_is_non_sensitive_and_uses_caller_catalog_path():
    projection = build_acp_sidecar_projection("/tmp/agentbox-home/models.json")
    assert projection.target == "/tmp/agentbox-home/config.toml"
    assert projection.view_files["models.json"] == _deepseek_model_catalog()
    assert b"experimental_bearer_token" not in projection.content
    assert b"secret" not in projection.content.lower()
    assert b'model = "deepseek-flash"' in projection.content
    assert b'model_catalog_json = "/tmp/agentbox-home/models.json"' in projection.content
    assert b'base_url = "https://api.deepseek.com/"' in projection.content
    assert b'wire_api = "responses"' in projection.content


@pytest.mark.parametrize("catalog_path", [
    "models.json", "/tmp/models.json", "/tmp/agentbox-home/../models.json",
    "/tmp/agentbox-home", "/tmp/agentbox-home//models.json",
])
def test_acp_sidecar_projection_rejects_non_guest_absolute_catalog_paths(catalog_path):
    with pytest.raises(ValueError, match="CODEX_CATALOG_PATH_INVALID"):
        build_acp_sidecar_projection(catalog_path)


def test_codex_catalog_is_declared_as_package_data():
    package = tomllib.loads((Path(__file__).resolve().parents[5] / "plugins/harness/codex/pyproject.toml").read_text())
    patterns = package["tool"]["setuptools"]["package-data"]["ordessa_harness_codex"]
    assert "*.json" in patterns
    assert "*.toml" in patterns
    assert (Path(__file__).resolve().parents[5] / "plugins/harness/codex/src/ordessa_harness_codex/deepseek-models.json").is_file()
    assert (Path(__file__).resolve().parents[5] / "plugins/harness/codex/src/ordessa_harness_codex/deepseek-sidecar-config.toml").is_file()


def test_decoder_and_path_classifier_fail_closed():
    content = b"\n".join(json.dumps(item).encode() for item in (
        {"type": "thread.started", "thread_id": "thread-fixture"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}},
        {"type": "turn.completed", "usage": {"output_tokens": 2}},
    ))
    decoded = decode_codex_jsonl(content)
    assert decoded.thread_id == "thread-fixture"
    assert decoded.messages == ("answer",)
    assert decoded.completed is True
    assert classify_native_session_path(
        "sessions/2026/09/13/rollout-thread-fixture.jsonl", "thread-fixture",
    )
    assert not classify_native_session_path("auth.json", "thread-fixture")
    assert not classify_native_session_path("history.jsonl", "thread-fixture")
    assert not classify_native_session_path(
        "sessions/2026/09/13/rollout-other.jsonl", "thread-fixture",
    )
