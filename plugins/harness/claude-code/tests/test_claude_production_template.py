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

from ordessa_harness_claude_code import production


REPO = Path(__file__).resolve().parents[4]
RUNTIME = REPO / "plugins" / "harness" / "runtime"


from functools import partial
from ordessa_server.composition.harness_catalog import capture_harness_catalog
from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
from ordessa_execution_agents.harness.providers.declarations.capability_claims import capability_claims

from ordessa_harness_claude_code.registration_declarations import registration_declarations

# This brand's own test catalog is established explicitly here: the declarations
# are read through this brand's public port and composed by the neutral capture
# helper. Nothing is taken from the implicit global selection or another brand.
_brand_declarations = registration_declarations()
_captured_harness_catalog = capture_harness_catalog(
    (_brand_declarations,), launch_declarations=(_brand_declarations,))
registry_capabilities = partial(capability_claims, _captured_harness_catalog.registry)

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
     capabilities_for=registry_capabilities)
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
        assert (production.DEPLOY_DIRECTORY / projection["source"].rsplit("/", 1)[-1]).is_file()
        assert projection["target"].startswith(f"{production.CONFIG_HOME}/")
    assert production.EGRESS_GUARD.is_file()


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
            production.deployment_document(artifact_token=source, tree_digest=digest, capabilities_for=registry_capabilities)


def test_product_model_translates_identity():
    assert production.native_model("deepseek-flash") == "deepseek-flash"
    assert production.native_model("something-else") == "something-else"
    assert production.native_model(None) is None


def test_capability_claims_derive_from_the_registry():
    claims = production.capability_claims(capabilities_for=registry_capabilities)
    # 2026-09-28 P-D 重探针：attach 由 False 翻 True（0.77 时代"握手 promptCapabilities
    # 为空"的旧负证据被钉版 0.81.2 第一手探针推翻，见 harnesses.toml claude-code 注释与
    # docs/implementation/specifications/014-plugin-release/reports/P-D-report.md）。本测试只断言"派生自注册表"，
    # golden 随注册表同步。
    assert claims == {
        "start": True, "observe": True, "finish": True,
        "attach": True, "steer": False, "permissions": False,
        "stream": True, "native_continuation": True,
    }


def test_the_official_default_selection_stays_pi_only():
    """Establishing this brand's catalog above must not change the product default."""
    default_selection = capture_selected_harness_catalog()
    assert [definition.harness_type for definition in default_selection.registry.all()] == ["pi"]


def test_the_sidecar_glue_registers_the_product_profile_id():
    script = (
        "import('" + (Path(__file__).resolve().parents[4] / 'apps/server/tests/support/profile_claims.mjs').as_uri() + "').then((module) =>"
        " process.stdout.write(JSON.stringify({"
        " translated: module.resolveNativeModel('claude-code', 'deepseek-flash'),"
        " profileRegistered: Boolean(module.resolveHarnessProfile('claude-code')),"
        " permissionMode: module.resolveHarnessProfile('claude-code').permissionMode,"
        " listed: module.registeredHarnessIDs() })))"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, env={**os.environ, "ORDESSA_TEST_PYTHON": sys.executable}, text=True,
                            timeout=60, cwd=str(REPO))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["translated"] == production.NATIVE_MODEL_VALUE
    assert payload["profileRegistered"] is True
    assert payload["permissionMode"] == "deny"
    assert "claude-code" in payload["listed"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
