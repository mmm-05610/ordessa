"""claude-code production template gates (Work Order 43).

Same contract as the other family template gates; the claude-specific parts
are the settings `env` map (the probe-verified path to the native endpoint),
the identity model mapping, and the LD_PRELOAD guard asset that reaches the
native CLI binary a NODE_OPTIONS hook cannot.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ordessa_harness.claude import production


REPO = Path(__file__).resolve().parents[3]
RUNTIME = REPO / "plugins" / "harness" / "runtime"


def test_checked_in_settings_match_the_module_constants():
    document = json.loads(production.SETTINGS_TEMPLATE.read_text(encoding="utf-8"))
    assert document["env"]["ANTHROPIC_BASE_URL"] == production.OFFICIAL_BASE_URL == (
        "https://api.deepseek.com/anthropic")
    assert document["model"] == production.PRODUCT_MODEL_ID == "deepseek-flash"
    # A credential reference lives in the environment, never in the settings file.
    assert "AUTH_TOKEN" not in json.dumps(document)
    assert "api_key" not in json.dumps(document).lower() or "ANTHROPIC_API_KEY" not in json.dumps(document)


def test_production_template_pins_the_confirmed_model_and_official_root():
    assert production.PRODUCT_MODEL_ID == "deepseek-flash"
    assert production.NATIVE_MODEL_VALUE == "deepseek-flash"
    assert production.CLAUDE_PROVIDER == "deepseek"
    assert production.CREDENTIAL_KIND == "api-key"
    assert production.CREDENTIAL_ENVIRONMENT == "ANTHROPIC_AUTH_TOKEN"
    assert production.ADAPTER_PACKAGE == "@agentclientprotocol/claude-agent-acp"
    assert production.ADAPTER_VERSION == "0.81.2"


def test_loopback_override_changes_only_the_base_url():
    override = production.loopback_settings_document("http://127.0.0.1:8080")
    differences = production.documented_differences("http://127.0.0.1:8080")
    assert list(differences) == ["env.ANTHROPIC_BASE_URL"]
    assert differences["env.ANTHROPIC_BASE_URL"] == (
        "https://api.deepseek.com/anthropic", "http://127.0.0.1:8080")
    assert override["model"] == production.settings_document()["model"]
    assert production.settings_document()["env"]["ANTHROPIC_BASE_URL"] == production.OFFICIAL_BASE_URL


def test_loopback_override_refuses_anything_but_a_loopback_url():
    for value in ("https://api.deepseek.com", "http://0.0.0.0:1", "http://192.168.0.1:1", "", None):
        with pytest.raises(production.ClaudeProductionTemplateError):
            production.loopback_settings_document(value)


def test_deployment_document_declares_the_managed_chain():
    document = production.deployment_document(
        artifact_token="claude-runtime",
        tree_digest="sha256:" + "a" * 64,
    )
    assert document["schemaVersion"] == 1
    harness = document["harnesses"][0]
    assert harness["id"] == "claude-code"
    assert harness["credentialKind"] == "api-key"
    assert harness["credentialEnvironment"] == "ANTHROPIC_AUTH_TOKEN"
    assert harness["runtimeArtifactMounts"] == [{
        "token": "claude-runtime", "target": "/runtime/artifacts/claude-runtime",
        "treeDigest": "sha256:" + "a" * 64,
    }]
    assert harness["stateProjection"] == {"target": "/runtime/home/.claude/projects"}
    assert harness["projectionFiles"] == [
        {"source": "deploy/claude/settings.json", "target": "/runtime/home/.claude/settings.json"},
    ]
    adapter = harness["adapter"]
    assert adapter["command"] == "/usr/bin/node"
    assert adapter["args"] == [
        "/runtime/artifacts/claude-runtime/node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js"]
    assert adapter["environment"]["CLAUDE_CONFIG_DIR"] == "/runtime/home/.claude"
    assert "NODE_OPTIONS" not in adapter["environment"]
    assert "ANTHROPIC_AUTH_TOKEN" not in json.dumps(adapter["environment"])


def test_projection_sources_exist_next_to_the_deployment_template():
    for projection in production.projection_files():
        assert (production.PLUGIN_ROOT / projection["source"]).is_file()
        assert projection["target"].startswith(f"{production.CONFIG_HOME}/")
    assert (production.PLUGIN_ROOT / production.LOOPBACK_GUARD_SOURCE).is_file()


def test_the_guest_home_is_the_one_isolated_root_and_both_paths_converge():
    """One home root: the dedicated variable and `$HOME` name the same target."""
    assert production.CONFIG_HOME == "/runtime/home/.claude"
    assert production.ADAPTER_ENVIRONMENT["CLAUDE_CONFIG_DIR"] == production.CONFIG_HOME
    assert production.CONFIG_HOME == "/runtime/home/.claude"
    assert production.STATE_TARGET == f"{production.CONFIG_HOME}/projects"
    for projection in production.projection_files():
        assert not projection["target"].startswith(production.STATE_TARGET + "/")


def test_adapter_entry_is_derived_from_the_artifact_target():
    assert production.ADAPTER_ARTIFACT_ENTRY == (
        "/runtime/artifacts/claude-runtime/node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js")
    assert production.ADAPTER_ARTIFACT_ENTRY.startswith(production.ARTIFACT_TARGET + "/")


def test_deployment_document_refuses_an_invalid_artifact_declaration():
    for source, digest in ((("relative/path"), "sha256:" + "a" * 64),
                           ("/srv/claude", "sha256:short"), ("/srv/claude", "md5:" + "a" * 32)):
        with pytest.raises(production.ClaudeProductionTemplateError):
            production.deployment_document(artifact_token=source, tree_digest=digest)


def test_product_model_translates_identity():
    assert production.native_model("deepseek-flash") == "deepseek-flash"
    assert production.native_model("something-else") == "something-else"
    assert production.native_model(None) is None


def test_capability_claims_derive_from_the_registry():
    claims = production.capability_claims()
    assert claims == {
        "start": True, "observe": True, "finish": True,
        "attach": False, "steer": False, "permissions": False,
        "stream": True, "native_continuation": True,
    }


def test_the_sidecar_glue_registers_the_product_profile_id():
    script = (
        "import('" + (RUNTIME / "profile_extensions.mjs").as_uri() + "').then((module) =>"
        " process.stdout.write(JSON.stringify({"
        " translated: module.resolveNativeModel('claude-code', 'deepseek-flash'),"
        " profileRegistered: Boolean(module.resolveHarnessProfile('claude-code')),"
        " permissionMode: module.resolveHarnessProfile('claude-code').permissionMode,"
        " listed: module.registeredHarnessIDs() })))"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                            timeout=60, cwd=str(REPO))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["translated"] == production.NATIVE_MODEL_VALUE
    assert payload["profileRegistered"] is True
    assert payload["permissionMode"] == "deny"
    assert "claude-code" in payload["listed"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
