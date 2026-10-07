"""dsh production template gates (Work Order 43).

Same contract as the Pi template gates: the checked-in configuration is the
only native configuration, the loopback override changes exactly one field, the
model translation lives in exactly one place per layer, and nothing test-only
or credential-shaped leaks into the production default.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

import pytest

from ordessa_harness_dsh import production


REPO = Path(__file__).resolve().parents[5]

BRAND_MODULES = {"dsh": "ordessa_harness_dsh", "kilo": "ordessa_harness_kilo",
                 "qwen": "ordessa_harness_qwen", "opencode": "ordessa_harness_opencode",
                 "hermes": "ordessa_harness_hermes", "codex": "ordessa_harness_codex",
                 "pi": "ordessa_harness_pi", "claude-code": "ordessa_harness_claude_code",
                 "claude": "ordessa_harness_claude_code"}
RUNTIME = REPO / "plugins" / "harness" / "runtime"


def test_checked_in_settings_match_the_module_constants():
    """The template file and the module must not drift into two truths."""
    document = yaml.safe_load(production.SETTINGS_TEMPLATE.read_text(encoding="utf-8"))
    section = document[production.SETTINGS_NAMESPACE]
    assert section["baseURL"] == production.OFFICIAL_BASE_URL == "https://api.deepseek.com"
    # Order 108 (AQ-0004): the checked-in template carries the permissive
    # production default, not the gate-era 64 that truncated answers.
    assert section["maxTokens"] == production.DEFAULT_OUTPUT_TOKEN_LIMIT == 8192
    assert section["thinking"] == "disabled"
    assert section["reasoningEffort"] == "off"
    # A credential reference, never credential material.
    assert "DEEPSEEK_API_KEY" not in json.dumps(document)


def test_gate_fixture_pins_the_gate_ceiling_while_the_template_stays_permissive():
    """Order 108 G2: the gate's budget is explicit, not inherited from 8192."""
    override = production.loopback_settings_document("http://127.0.0.1:8080")
    gate_fixture = production.gate_settings_document("http://127.0.0.1:8080")
    assert override[production.SETTINGS_NAMESPACE]["maxTokens"] == (
        production.DEFAULT_OUTPUT_TOKEN_LIMIT)
    assert production.DEFAULT_OUTPUT_TOKEN_LIMIT == 8192
    assert gate_fixture[production.SETTINGS_NAMESPACE]["maxTokens"] == (
        production.OUTPUT_TOKEN_LIMIT)
    assert production.OUTPUT_TOKEN_LIMIT == 64
    assert gate_fixture[production.SETTINGS_NAMESPACE]["baseURL"] == "http://127.0.0.1:8080"


def test_production_template_pins_the_confirmed_model_and_official_root():
    assert production.PRODUCT_MODEL_ID == "deepseek-flash"
    assert production.NATIVE_MODEL_VALUE == '["deepseek-official","deepseek-flash"]'
    assert production.DSH_PROVIDER == "deepseek-official"
    assert production.CREDENTIAL_KIND == "api-key"
    assert production.CREDENTIAL_ENVIRONMENT == "DEEPSEEK_API_KEY"
    assert production.ADAPTER_PACKAGE == "@deepseek-ai/dsh"
    assert production.ADAPTER_VERSION == "0.1.5-rc.1"


def test_loopback_override_changes_only_the_base_url():
    override = production.loopback_settings_document("http://127.0.0.1:8080")
    differences = production.documented_differences("http://127.0.0.1:8080")
    assert list(differences) == [f"{production.SETTINGS_NAMESPACE}.baseURL"]
    assert differences[f"{production.SETTINGS_NAMESPACE}.baseURL"] == (
        "https://api.deepseek.com", "http://127.0.0.1:8080")
    assert override[production.SETTINGS_NAMESPACE]["maxTokens"] == (
        production.settings_document()[production.SETTINGS_NAMESPACE]["maxTokens"])
    # The production template on disk is never rewritten by producing an override.
    assert production.settings_document()[production.SETTINGS_NAMESPACE]["baseURL"] == (
        production.OFFICIAL_BASE_URL)


def test_rendered_settings_bytes_are_deterministic():
    document = production.loopback_settings_document("http://127.0.0.1:9")
    first = production.render_settings_document(document)
    second = production.render_settings_document(production.loopback_settings_document("http://127.0.0.1:9"))
    assert first == second
    assert yaml.safe_load(first.decode("utf-8")) == document


def test_loopback_override_refuses_anything_but_a_loopback_url():
    for value in ("https://api.deepseek.com", "http://0.0.0.0:1", "http://192.168.0.1:1", "", None):
        with pytest.raises(production.DshProductionTemplateError):
            production.loopback_settings_document(value)


def test_deployment_document_declares_the_managed_chain():
    document = production.deployment_document(
        artifact_token="dsh-runtime",
        tree_digest="sha256:" + "a" * 64,
    )
    assert document["schemaVersion"] == 1
    harness = document["harnesses"][0]
    assert harness["id"] == "dsh"
    assert harness["credentialKind"] == "api-key"
    assert harness["credentialEnvironment"] == "DEEPSEEK_API_KEY"
    assert harness["modelControlId"] == production.MODEL_CONTROL_ID
    assert harness["controlOptions"] == {production.MODEL_CONTROL_ID: []}
    assert harness["runtimeArtifactMounts"] == [{
        "token": "dsh-runtime", "target": "/runtime/artifacts/dsh-runtime",
        "treeDigest": "sha256:" + "a" * 64,
    }]
    assert harness["stateProjection"] == {"target": "/runtime/home/.dsh/sessions"}
    assert harness["projectionFiles"] == [
        {"source": "deploy/dsh/settings.yaml", "target": "/runtime/home/.dsh/settings.yaml"},
    ]
    adapter = harness["adapter"]
    assert adapter["command"] == "/usr/bin/node"
    assert adapter["args"] == [
        "/runtime/artifacts/dsh-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js",
        "--profile", "acp",
    ]
    assert adapter["environment"]["DSH_HOME"] == "/runtime/home/.dsh"
    # Nothing test-only may leak into the production default: no preloaded
    # guard, no audit path, and no credential material anywhere.
    assert "NODE_OPTIONS" not in adapter["environment"]
    assert "AGENTBOX_EGRESS_AUDIT" not in adapter["environment"]
    assert "DEEPSEEK_API_KEY" not in json.dumps(adapter["environment"])


def test_projection_sources_exist_next_to_the_deployment_template():
    for projection in production.projection_files():
        assert (production.PLUGIN_ROOT / projection["source"]).is_file()
        assert projection["target"].startswith(f"{production.HARNESS_HOME}/")
    assert production.LOOPBACK_GUARD.is_file()
    assert production.LOOPBACK_GUARD_TARGET.startswith(f"{production.HARNESS_HOME}/")


def test_the_guest_home_is_the_one_isolated_root_and_both_paths_converge():
    """One home root: the dedicated variable and `$HOME` name the same target.

    dsh's own default is `$HOME/.dsh`, and the deployment declares that same
    directory through `DSH_HOME`; the read-only configuration and the writable
    session store are both inside it, so configuration and state can never be
    split across two homes (or land on the host's).
    """
    assert production.HARNESS_HOME == "/runtime/home/.dsh"
    assert production.ADAPTER_ENVIRONMENT["DSH_HOME"] == production.HARNESS_HOME
    guest_home = "/runtime/home"
    assert production.HARNESS_HOME == f"{guest_home}/.dsh"
    assert production.STATE_TARGET == f"{production.HARNESS_HOME}/sessions"
    assert production.STATE_TARGET.startswith(production.HARNESS_HOME + "/")
    # The read-only configuration is *not* inside the writable state subtree.
    for projection in production.projection_files():
        assert not projection["target"].startswith(production.STATE_TARGET + "/")
        assert projection["target"] != production.STATE_TARGET
    assert not production.LOOPBACK_GUARD_TARGET.startswith(production.STATE_TARGET + "/")


def test_adapter_entry_is_derived_from_the_artifact_target():
    assert production.ADAPTER_ARTIFACT_ENTRY == (
        "/runtime/artifacts/dsh-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js")
    assert production.ADAPTER_ARTIFACT_ENTRY.startswith(production.ARTIFACT_TARGET + "/")
    assert production.ADAPTER_ARTIFACT_ENTRY.endswith(production.ADAPTER_ARTIFACT_RELATIVE_ENTRY)


def test_deployment_document_refuses_an_invalid_artifact_declaration():
    for source, digest in ((("relative/path"), "sha256:" + "a" * 64),
                           ("/srv/dsh", "sha256:short"), ("/srv/dsh", "md5:" + "a" * 32)):
        with pytest.raises(production.DshProductionTemplateError):
            production.deployment_document(artifact_token=source, tree_digest=digest)


def test_product_model_translates_to_the_native_catalogue_value():
    assert production.native_model("deepseek-flash") == '["deepseek-official","deepseek-flash"]'
    assert production.native_model("something-else") == "something-else"
    assert production.native_model(None) is None


def test_capability_claims_derive_from_the_registry():
    """The template's claims are the registry's, verbatim - never a second copy."""
    claims = production.capability_claims()
    assert claims == {
        "start": True, "observe": True, "finish": True,
        "attach": False, "steer": False, "permissions": False,
        "stream": True, "native_continuation": True,
    }
    for value in claims.values():
        assert isinstance(value, bool)


def test_the_sidecar_glue_owns_the_same_model_mapping():
    """The alias must exist in one place only, and the two must not disagree."""
    script = (
        "import('" + (RUNTIME / "profile_extensions.mjs").as_uri() + "').then((module) =>"
        " process.stdout.write(JSON.stringify({"
        " aliases: module.AGENTBOX_MODEL_ALIASES,"
        " translated: module.resolveNativeModel('dsh', 'deepseek-flash'),"
        " passthrough: module.resolveNativeModel('hermes', 'deepseek-flash'),"
        " profileRegistered: Boolean(module.resolveHarnessProfile('dsh')),"
        " listed: module.registeredHarnessIDs() })))"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                            timeout=60, cwd=str(REPO))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["aliases"]["dsh"] == production.model_aliases()
    families = {path.parent.name.split("ordessa_harness_")[-1].replace("_code","")
                for path in (REPO / "plugins" / "harness").glob(
                    "*/src/ordessa_harness_*/production.py")} | {"claude"}
    assert set(payload["aliases"]) <= families, "an alias without a production template is drift"
    assert payload["translated"] == production.NATIVE_MODEL_VALUE
    assert payload["passthrough"] == "deepseek-flash"
    assert payload["profileRegistered"] is True
    assert "dsh" in payload["listed"]


def test_the_loopback_guard_blocks_non_loopback_destinations(tmp_path):
    """The guard is the enforcement behind "this gate only reached loopback"."""
    audit = tmp_path / "audit"
    script = (
        "const guard = '" + str(production.LOOPBACK_GUARD) + "';"
        "require(guard);"
        "const net = require('node:net');"
        "const results = {};"
        "try { new net.Socket().connect({ host: 'api.deepseek.com', port: 443 });"
        " results.remote = 'allowed'; } catch (error) { results.remote = error.code; }"
        "try { const socket = new net.Socket();"
        " socket.on('error', () => {});"
        " socket.connect({ host: '127.0.0.1', port: 1 });"
        " results.loopback = 'allowed'; } catch (error) { results.loopback = error.code; }"
        "process.stdout.write(JSON.stringify(results));"
    )
    environment = {**os.environ, "AGENTBOX_EGRESS_AUDIT": str(audit)}
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                            timeout=60, env=environment, cwd=str(tmp_path))
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["remote"] == "AGENTBOX_EGRESS_BLOCKED"
    assert outcome["loopback"] != "AGENTBOX_EGRESS_BLOCKED"
    lines = audit.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("guard-loaded") for line in lines)
    assert any(line.startswith("denied connect api.deepseek.com:443") for line in lines)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
