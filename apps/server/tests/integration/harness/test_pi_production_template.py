"""Pi production template gates.

The template is only trustworthy if it is the *same* configuration Work Order
42-D prepared and if the parts the layers above must never learn stay out of it.
Both are asserted here, including the one place a second copy could hide: the
model id Pi's own catalogue uses, which lives in the sidecar glue that has to
apply it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ordessa_harness_pi import production
from functools import partial
from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
from ordessa_agents.harness.providers.declarations.capability_claims import capability_claims
registry_capabilities = partial(capability_claims, capture_selected_harness_catalog().registry)


REPO = Path(__file__).resolve().parents[5]

BRAND_MODULES = {"dsh": "ordessa_harness_dsh", "kilo": "ordessa_harness_kilo",
                 "qwen": "ordessa_harness_qwen", "opencode": "ordessa_harness_opencode",
                 "hermes": "ordessa_harness_hermes", "codex": "ordessa_harness_codex",
                 "pi": "ordessa_harness_pi", "claude-code": "ordessa_harness_claude_code",
                 "claude": "ordessa_harness_claude_code"}
RUNTIME = REPO / "plugins" / "harness" / "runtime"


def as_json(value):
    """JSON-normalized comparison: key order and formatting are not identity."""
    return json.loads(json.dumps(value, sort_keys=True))


def test_native_configuration_is_the_prepared_42d_configuration(tmp_path):
    """The checked-in template must equal the 42-D prepared configuration.

    `model-validation-42d.mjs` is where Work Order 42-D prepared the Pi
    configuration. Sweeping a second, hand-written copy into the plugin is
    exactly how the production deployment and the accepted preparation would
    drift apart, so this runs the prepared path in `--dry-run` (with a
    throwaway token file the test creates) and demands equality.
    """
    token = tmp_path / "not-a-real-token"
    token.write_bytes(b"pi-template-test-token")
    token.chmod(0o600)
    result = subprocess.run(
        ["node", str(Path(__file__).resolve().parents[5] / "tooling/checks/harness/model_validation_42d.mjs"),
         "--family", "pi", "--secret-file", str(token), "--dry-run"],
        capture_output=True, env={**os.environ, "ORDESSA_TEST_PYTHON": sys.executable}, text=True, timeout=180, cwd=str(REPO),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prepared = json.loads(result.stdout.strip().splitlines()[-1])
    assert prepared["outcome"] == "PREPARED"
    assert as_json(prepared["config"]) == as_json(production.models_document())
    assert as_json(prepared["settings"]) == as_json(production.settings_document())
    # The template references an environment variable and carries no material.
    assert "pi-template-test-token" not in json.dumps(production.models_document())
    assert "$DEEPSEEK_API_KEY" in json.dumps(production.models_document())


def test_production_template_pins_the_confirmed_model_and_official_root():
    models = production.models_document()
    provider = models["providers"][production.PI_PROVIDER]
    assert production.PRODUCT_MODEL_ID == "deepseek-flash"
    assert production.NATIVE_MODEL_VALUE == "deepseek/deepseek-flash"
    assert provider["baseUrl"] == production.OFFICIAL_BASE_URL == "https://api.deepseek.com"
    assert provider["api"] == "openai-completions"
    assert provider["apiKey"] == "$DEEPSEEK_API_KEY"
    model = provider["models"][0]
    assert model["id"] == production.PRODUCT_MODEL_ID
    # Order 108 (AQ-0004): the template carries the permissive production
    # default, no longer the gate-era 64 that truncated ordinary answers.
    assert model["maxTokens"] == production.DEFAULT_OUTPUT_TOKEN_LIMIT == 8192
    assert model["reasoning"] is False
    assert model["samplingParams"]["thinking"] == {"type": "disabled"}
    settings = production.settings_document()
    assert settings["retry"]["enabled"] is False
    assert settings["retry"]["maxRetries"] == 0
    assert settings["retry"]["provider"]["maxRetries"] == 0


def test_loopback_override_changes_only_the_base_url():
    override = production.loopback_models_document("http://127.0.0.1:8080")
    differences = production.documented_differences("http://127.0.0.1:8080")
    assert list(differences) == [f"providers.{production.PI_PROVIDER}.baseUrl"]
    assert differences[f"providers.{production.PI_PROVIDER}.baseUrl"] == (
        "https://api.deepseek.com", "http://127.0.0.1:8080")
    assert override["providers"][production.PI_PROVIDER]["models"] == (
        production.models_document()["providers"][production.PI_PROVIDER]["models"])
    # The production template on disk is never rewritten by producing an override.
    assert production.models_document()["providers"][production.PI_PROVIDER]["baseUrl"] == (
        production.OFFICIAL_BASE_URL)


def test_gate_fixture_pins_the_gate_ceiling_while_the_template_stays_permissive():
    """Order 108 G2: the gate's own budget is explicit, not inherited from 8192.

    The endpoint override keeps "only baseUrl" (so the catalogue still carries the
    permissive default); the gate projection is a *separate*, explicit pin to
    OUTPUT_TOKEN_LIMIT. If the pin were removed the gate would project the
    template's 8192 and no longer bound its request budget - the counter-example,
    asserted by the two values actually differing.
    """
    override = production.loopback_models_document("http://127.0.0.1:8080")
    gate_fixture = production.gate_models_document("http://127.0.0.1:8080")
    assert override["providers"][production.PI_PROVIDER]["models"][0]["maxTokens"] == (
        production.DEFAULT_OUTPUT_TOKEN_LIMIT)
    assert production.DEFAULT_OUTPUT_TOKEN_LIMIT == 8192
    assert gate_fixture["providers"][production.PI_PROVIDER]["models"][0]["maxTokens"] == (
        production.OUTPUT_TOKEN_LIMIT)
    assert production.OUTPUT_TOKEN_LIMIT == 64
    assert gate_fixture["providers"][production.PI_PROVIDER]["baseUrl"] == "http://127.0.0.1:8080"


def test_loopback_override_refuses_anything_but_a_loopback_url():
    for value in ("https://api.deepseek.com", "http://0.0.0.0:1", "http://192.168.0.1:1", "", None):
        with pytest.raises(production.PiProductionTemplateError):
            production.loopback_models_document(value)


def test_deployment_document_declares_the_managed_chain():
    document = production.deployment_document(
        capabilities_for=registry_capabilities,
        artifact_token="artifact",
        tree_digest="sha256:" + "a" * 64,
    )
    assert document["schemaVersion"] == 1
    # The document names no host path at all: the plugin root and every mount
    # token are the loader's business, not the file's.
    assert "pluginRoot" not in document
    harness = document["harnesses"][0]
    assert harness["id"] == "pi"
    assert harness["credentialKind"] == "api-key"
    assert harness["credentialEnvironment"] == "DEEPSEEK_API_KEY"
    assert harness["modelControlId"] == production.MODEL_CONTROL_ID
    assert harness["controlOptions"] == {production.MODEL_CONTROL_ID: []}
    assert harness["runtimeArtifactMounts"] == [{
        "token": "artifact",
        "target": "/runtime/artifacts/pi-runtime",
        "treeDigest": "sha256:" + "a" * 64,
    }]
    assert harness["stateProjection"] == {"target": "/runtime/home/.pi/agent/sessions"}
    assert harness["projectionFiles"] == [
        {"source": "deploy/pi/models.json", "target": "/runtime/home/.pi/agent/models.json"},
        {"source": "deploy/pi/settings.json", "target": "/runtime/home/.pi/agent/settings.json"},
    ]
    adapter = harness["adapter"]
    assert adapter["command"] == "/usr/bin/node"
    assert adapter["args"] == [
        "/runtime/artifacts/pi-runtime/node_modules/@automatalabs/pi-acp/dist/index.js"]
    assert adapter["environment"]["PI_CODING_AGENT_DIR"] == "/runtime/home/.pi/agent"
    assert adapter["environment"]["PI_OFFLINE"] == "1"
    # Nothing test-only may leak into the production default: no preloaded
    # guard, no audit path, and no credential material anywhere.
    assert "NODE_OPTIONS" not in adapter["environment"]
    assert "AGENTBOX_EGRESS_AUDIT" not in adapter["environment"]
    assert "DEEPSEEK_API_KEY" not in json.dumps(adapter["environment"])


def test_projection_sources_exist_next_to_the_deployment_template():
    for projection in production.projection_files():
        assert (production.DEPLOY_DIRECTORY / projection["source"].rsplit("/", 1)[-1]).is_file()
        assert projection["target"].startswith(f"{production.AGENT_HOME}/")
    assert production.LOOPBACK_GUARD.is_file()
    assert production.LOOPBACK_GUARD_TARGET.startswith(f"{production.AGENT_HOME}/")


def test_the_guest_home_is_the_one_isolated_root_and_both_paths_converge():
    """One home root: the dedicated variable and `$HOME` name the same target.

    Pi's own default is `$HOME/.pi/agent`, and the deployment declares that same
    directory through `PI_CODING_AGENT_DIR`; the read-only configuration and the
    writable journal are both inside it, so configuration and state can never be
    split across two homes (or land on the host's).
    """
    assert production.AGENT_HOME == "/runtime/home/.pi/agent"
    assert production.ADAPTER_ENVIRONMENT["PI_CODING_AGENT_DIR"] == production.AGENT_HOME
    # Pi's own default is `$HOME/.pi/agent`; the guest's HOME is the one
    # isolated root, so the default and the declared variable are one directory.
    guest_home = "/runtime/home"
    assert production.AGENT_HOME == f"{guest_home}/.pi/agent"
    assert production.STATE_TARGET == f"{production.AGENT_HOME}/sessions"
    assert production.STATE_TARGET.startswith(production.AGENT_HOME + "/")
    # The read-only configuration is *not* inside the writable state subtree:
    # nothing has to be protected, and nothing can be shadowed by the bind.
    for projection in production.projection_files():
        assert not projection["target"].startswith(production.STATE_TARGET + "/")
        assert projection["target"] != production.STATE_TARGET
    assert not production.LOOPBACK_GUARD_TARGET.startswith(production.STATE_TARGET + "/")


def test_adapter_entry_is_derived_from_the_artifact_target():
    assert production.ADAPTER_ARTIFACT_ENTRY == (
        "/runtime/artifacts/pi-runtime/node_modules/@automatalabs/pi-acp/dist/index.js")
    assert production.ADAPTER_ARTIFACT_ENTRY.startswith(production.ARTIFACT_TARGET + "/")
    assert production.ADAPTER_ARTIFACT_ENTRY.endswith(production.ADAPTER_ARTIFACT_RELATIVE_ENTRY)
    assert production.STATE_TARGET == f"{production.AGENT_HOME}/sessions"


def test_deployment_document_refuses_an_invalid_artifact_declaration():
    # A token is a name, never a path, and the digest has to be a full sha256:
    # each of these is refused by the template rather than written into a
    # document that could not be bound on any machine.
    for token, digest in (("relative/path", "sha256:" + "a" * 64),
                          ("/srv/artifact", "sha256:" + "a" * 64),
                          ("Artifact", "sha256:" + "a" * 64),
                          ("a" * 33, "sha256:" + "a" * 64),
                          ("artifact", "sha256:short"),
                          ("artifact", "md5:" + "a" * 32)):
        with pytest.raises(production.PiProductionTemplateError):
            production.deployment_document(artifact_token=token, tree_digest=digest, capabilities_for=registry_capabilities)


def test_product_model_translates_to_the_native_catalogue_value():
    assert production.native_model("deepseek-flash") == "deepseek/deepseek-flash"
    assert production.native_model("something-else") == "something-else"
    assert production.native_model(None) is None


def test_the_sidecar_glue_owns_the_same_model_mapping():
    """The alias must exist in one place only, and the two must not disagree.

    The deployment template is Python; the translation is applied inside the
    sidecar process, which is JavaScript. Rather than keep two copies in step by
    hand, the JavaScript module is asked for its table and compared. The table
    may hold other families, but it may not hold one without a production
    template here - an alias with no template is drift by construction.
    """
    script = (
        "import('" + (Path(__file__).resolve().parents[5] / 'apps/server/tests/support/profile_claims.mjs').as_uri() + "').then((module) =>"
        " process.stdout.write(JSON.stringify({"
        " aliases: module.AGENTBOX_MODEL_ALIASES,"
        " translated: module.resolveNativeModel('pi', 'deepseek-flash'),"
        " passthrough: module.resolveNativeModel('hermes', 'deepseek-flash'),"
        " empty: module.resolveNativeModel('pi', undefined) ?? null })))"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, env={**os.environ, "ORDESSA_TEST_PYTHON": sys.executable}, text=True,
                            timeout=60, cwd=str(REPO))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["aliases"]["pi"] == production.model_aliases()
    families = {path.parent.name.split("ordessa_harness_")[-1].replace("_code","")
                for path in (REPO / "plugins" / "harness").glob(
                    "*/src/ordessa_harness_*/production.py")} | {"claude"}
    assert set(payload["aliases"]) <= families, "an alias without a production template is drift"
    assert payload["translated"] == production.NATIVE_MODEL_VALUE
    assert payload["passthrough"] == "deepseek-flash"
    assert payload["empty"] is None


def test_the_access_entry_translates_no_model_and_names_no_brand():
    """The entry relays an ACP parameter; it does not rewrite one.

    The retired envelope translated `request.model` on every model-bearing op of
    both its routes. A transparent relay cannot do that, so the check inverted with
    the chain: the alias *table* still lives here and its parity with this brand's
    production template is asserted above, but applying it is the caller's decision,
    not a step the access layer performs. `acp_passthrough_target.test.mjs` pins the
    same fact behaviourally by sending an unknown model field through the relay.
    """
    entry = (Path(__file__).resolve().parents[5] / 'apps/server/src/ordessa_server/composition/native_channels/access_entry.mjs').read_text(encoding="utf-8")
    assert "resolveNativeModel" not in entry, "the relay is rewriting an ACP parameter"
    # No Harness name is branched on inside the generic entry: brand differences live under harnesses/.
    for name in ("pi-acp", "automatalabs", "deepseek", "codex", "claude", "hermes", "dsh",
                 "qwen", "kilo", "opencode", "omp"):
        assert name not in entry, f"{name} must not appear in the generic access entry"


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
                            timeout=60, env={**environment, "ORDESSA_TEST_PYTHON": sys.executable}, cwd=str(tmp_path))
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["remote"] == "AGENTBOX_EGRESS_BLOCKED"
    assert outcome["loopback"] != "AGENTBOX_EGRESS_BLOCKED"
    lines = audit.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("guard-loaded") for line in lines)
    assert any(line.startswith("denied connect api.deepseek.com:443") for line in lines)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
