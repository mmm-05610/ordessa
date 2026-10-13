"""kilo production template gates (Work Order 43 follow-up).

Same contract as the other family template gates; the kilo-specific parts are
the `KILO_CONFIG_CONTENT` delivery channel (the probe-verified configuration
path - no configuration file is projected), the native-binary adapter command,
and the identity `provider/model` mapping.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ordessa_harness_kilo import production


REPO = Path(__file__).resolve().parents[4]

BRAND_MODULES = {"dsh": "ordessa_harness_dsh", "kilo": "ordessa_harness_kilo",
                 "qwen": "ordessa_harness_qwen", "opencode": "ordessa_harness_opencode",
                 "hermes": "ordessa_harness_hermes", "codex": "ordessa_harness_codex",
                 "pi": "ordessa_harness_pi", "claude-code": "ordessa_harness_claude_code",
                 "claude": "ordessa_harness_claude_code"}
RUNTIME = REPO / "plugins" / "harness" / "runtime"


from functools import partial
from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
from ordessa_execution_agents.harness.providers.declarations.capability_claims import capability_claims

_captured_harness_catalog = capture_selected_harness_catalog()
registry_capabilities = partial(capability_claims, _captured_harness_catalog.registry)

def test_checked_in_config_pins_official_root_and_model():
    document = production.config_document()
    assert production._base_url_of(document) == production.OFFICIAL_BASE_URL == "https://api.deepseek.com"
    assert document["model"] == production.NATIVE_MODEL_VALUE == "deepseek/deepseek-flash"
    # The credential is an environment reference, never a literal.
    assert document["provider"]["deepseek"]["options"]["apiKey"] == "{env:OPENAI_API_KEY}"
    assert document["autoupdate"] is False


def test_production_template_pins_the_confirmed_model_and_official_root():
    assert production.PRODUCT_MODEL_ID == "deepseek-flash"
    assert production.NATIVE_MODEL_VALUE == "deepseek/deepseek-flash"
    assert production.KILO_PROVIDER == "deepseek"
    assert production.CREDENTIAL_KIND == "api-key"
    assert production.CREDENTIAL_ENVIRONMENT == "OPENAI_API_KEY"
    assert production.ADAPTER_PACKAGE == "@kilocode/cli"
    assert production.ADAPTER_VERSION == "7.8.3"


def test_adapter_environment_carries_the_config_document():
    environment = production.adapter_environment()
    config = json.loads(environment["KILO_CONFIG_CONTENT"])
    assert production._base_url_of(config) == production.OFFICIAL_BASE_URL
    assert set(environment) == {"KILO_CONFIG_CONTENT"}


def test_loopback_override_changes_only_the_base_url():
    override = production.loopback_config_document("http://127.0.0.1:8080")
    differences = production.documented_differences("http://127.0.0.1:8080")
    assert list(differences) == ["provider.deepseek.options.baseURL"]
    assert differences["provider.deepseek.options.baseURL"] == (
        "https://api.deepseek.com", "http://127.0.0.1:8080")
    assert override["model"] == production.config_document()["model"]
    assert production._base_url_of(production.config_document()) == production.OFFICIAL_BASE_URL
    loopback_environment = production.adapter_environment("http://127.0.0.1:8080")
    assert production._base_url_of(json.loads(loopback_environment["KILO_CONFIG_CONTENT"])) == (
        "http://127.0.0.1:8080")
    with pytest.raises(production.KiloProductionTemplateError):
        production.loopback_config_document("https://api.deepseek.com")


def test_deployment_document_declares_the_managed_chain():
    document = production.deployment_document(
        artifact_token="kilo-runtime",
        tree_digest="sha256:" + "a" * 64,
     capabilities_for=registry_capabilities)
    assert document["schemaVersion"] == 1
    harness = document["harnesses"][0]
    assert harness["id"] == "kilo"
    assert harness["credentialKind"] == "api-key"
    assert harness["credentialEnvironment"] == "OPENAI_API_KEY"
    assert harness["runtimeArtifactMounts"] == [{
        "token": "kilo-runtime", "target": "/runtime/artifacts/kilo-runtime",
        "treeDigest": "sha256:" + "a" * 64,
    }]
    assert harness["stateProjection"] == {"target": "/runtime/home/.local/share/kilo"}
    assert harness["projectionFiles"] == []
    adapter = harness["adapter"]
    assert adapter["command"] == (
        "/runtime/artifacts/kilo-runtime/node_modules/@kilocode/cli-linux-x64-baseline/bin/kilo")
    assert adapter["args"] == ["acp"]
    config = json.loads(adapter["environment"]["KILO_CONFIG_CONTENT"])
    assert production._base_url_of(config) == production.OFFICIAL_BASE_URL
    # Nothing test-only may leak into the production default, and no credential
    # material anywhere.
    assert "NODE_OPTIONS" not in adapter["environment"]
    assert "LD_PRELOAD" not in adapter["environment"]
    assert "OPENAI_API_KEY" not in json.dumps(config).replace("{env:OPENAI_API_KEY}", "")


def test_gate_assets_exist_next_to_the_deployment_template():
    assert production.CONFIG_TEMPLATE.is_file()
    assert production.LOOPBACK_GUARD.is_file()
    # The configuration template is the source of the KILO_CONFIG_CONTENT value.
    environment = production.adapter_environment()
    assert json.loads(environment["KILO_CONFIG_CONTENT"]) == production.config_document()


def test_state_projection_is_the_data_subtree():
    assert production.STATE_TARGET == "/runtime/home/.local/share/kilo"
    assert not production.STATE_TARGET.startswith("/runtime/home/.config/")


def test_adapter_entry_is_derived_from_the_artifact_target():
    assert production.ADAPTER_ARTIFACT_ENTRY == (
        "/runtime/artifacts/kilo-runtime/node_modules/@kilocode/cli-linux-x64-baseline/bin/kilo")
    assert production.ADAPTER_ARTIFACT_ENTRY.startswith(production.ARTIFACT_TARGET + "/")


def test_deployment_document_refuses_an_invalid_artifact_declaration():
    for source, digest in ((("relative/path"), "sha256:" + "a" * 64),
                           ("/srv/kilo", "sha256:short"), ("/srv/kilo", "md5:" + "a" * 32)):
        with pytest.raises(production.KiloProductionTemplateError):
            production.deployment_document(artifact_token=source, tree_digest=digest, capabilities_for=registry_capabilities)


def test_product_model_translates_to_the_native_config_value():
    assert production.native_model("deepseek-flash") == "deepseek/deepseek-flash"
    assert production.native_model("something-else") == "something-else"
    assert production.native_model(None) is None


def test_capability_claims_derive_from_the_registry():
    claims = production.capability_claims(capabilities_for=registry_capabilities)
    assert claims == {
        "start": True, "observe": True, "finish": True,
        "attach": False, "steer": False, "permissions": False,
        "stream": True, "native_continuation": True,
    }


def test_the_sidecar_glue_owns_the_same_model_mapping():
    """The alias must exist in one place only, and the two must not disagree."""
    script = (
        "import('" + (Path(__file__).resolve().parents[4] / 'apps/server/tests/support/profile_claims.mjs').as_uri() + "').then((module) =>"
        " process.stdout.write(JSON.stringify({"
        " aliases: module.AGENTBOX_MODEL_ALIASES,"
        " translated: module.resolveNativeModel('kilo', 'deepseek-flash'),"
        " passthrough: module.resolveNativeModel('hermes', 'deepseek-flash'),"
        " profileRegistered: Boolean(module.resolveHarnessProfile('kilo')),"
        " listed: module.registeredHarnessIDs() })))"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, env={**os.environ, "ORDESSA_TEST_PYTHON": sys.executable}, text=True,
                            timeout=60, cwd=str(REPO))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["aliases"]["kilo"] == production.model_aliases()
    families = {path.parent.name.split("ordessa_harness_")[-1].replace("_code","")
                for path in (REPO / "plugins" / "harness").glob(
                    "*/src/ordessa_harness_*/production.py")} | {"claude"}
    assert set(payload["aliases"]) <= families, "an alias without a production template is drift"
    assert payload["translated"] == production.NATIVE_MODEL_VALUE
    assert payload["passthrough"] == "deepseek-flash"
    assert payload["profileRegistered"] is True
    assert "kilo" in payload["listed"]


def test_the_loopback_guard_blocks_non_loopback_destinations(tmp_path):
    """The guard is the enforcement behind "this gate only reached loopback"."""
    audit = tmp_path / "audit"
    script = (
        "const guard = '" + str(production.LOOPBACK_GUARD) + "';"
        "void guard;"
        "const net = require('node:net');"
        "const results = {};"
        "try { new net.Socket().connect({ host: 'api.deepseek.com', port: 443 });"
        " results.remote = 'allowed'; } catch (error) { results.remote = error.code; }"
        "process.stdout.write(JSON.stringify(results));"
    )
    # The guard is C, not a node module: compile it the way the gate does and
    # preload it, asserting the enforcement this gate will rely on.
    import shutil as _shutil
    compiler = _shutil.which("cc")
    assert compiler, "a C compiler is required for this test"
    so = tmp_path / "guard.so"
    import subprocess as _subprocess
    build = _subprocess.run(
        [compiler, "-shared", "-fPIC", "-O2", "-o", str(so),
         str(production.LOOPBACK_GUARD), "-ldl"],
        capture_output=True, env={**os.environ, "ORDESSA_TEST_PYTHON": sys.executable}, text=True, timeout=120)
    assert build.returncode == 0, build.stderr
    # The C guard refuses at the syscall layer, so refusals surface as
    # asynchronous socket errors (unlike the JS guard's synchronous throw):
    # an error listener must exist, and the audit file is the evidence.
    node_script = (
        "const net = require('node:net');"
        "const results = {};"
        "try { const remote = new net.Socket(); remote.on('error', () => {});"
        " remote.connect({ host: 'api.deepseek.com', port: 443 });"
        " results.remote = 'attempted'; } catch (error) { results.remote = error.code; }"
        "try { const socket = new net.Socket();"
        " socket.on('error', () => {});"
        " socket.connect({ host: '127.0.0.1', port: 1 });"
        " results.loopback = 'allowed'; } catch (error) { results.loopback = error.code; }"
        "setTimeout(() => process.stdout.write(JSON.stringify(results)), 300);"
    )
    environment = {**os.environ, "AGENTBOX_EGRESS_AUDIT": str(audit), "LD_PRELOAD": str(so)}
    result = subprocess.run(["node", "-e", node_script], capture_output=True, text=True,
                            timeout=60, env={**environment, "ORDESSA_TEST_PYTHON": sys.executable}, cwd=str(tmp_path))
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["loopback"] == "allowed"
    lines = audit.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("guard-loaded") for line in lines)
    # The guard refuses at name resolution, before any connection attempt.
    assert any(line.startswith("denied resolve api.deepseek.com") for line in lines)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
