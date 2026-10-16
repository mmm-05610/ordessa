"""Codex production template gates (config bytes, fields, and the delegated seams).

Two things are asserted here that a review cannot see by reading the template:

* the native model catalogue the deployment projects is the **exact file the
  official installer writes** - recomputed here from the checked-in script bytes
  (`write_models_json`'s heredoc), never by executing the script and never over
  the network - and it retains the 42-D pinned SHA-256 witness without keeping
  a second physical catalogue source;
* the production configuration carries **exactly** the fields the deployment
  decided on, with no loopback address and no credential material, so the gate's
  loopback copy is provably a one-field override of a reviewed file.

The credential environment name and the ephemeral credential store are pinned
fields with a first-hand reason (see the module docstring of
`ordessa_harness_codex.production`): the ACP adapter's `api-key`
authentication reads `CODEX_API_KEY`/`OPENAI_API_KEY` only, and persisting that
authentication would write the credential into `$CODEX_HOME/auth.json`, which the
sidecar's state capture must refuse. Both facts are reproduced by
`scripts/server-round1/codex-production-chain-gate.py`.
"""
from __future__ import annotations
import sys
import os

import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from ordessa_harness_codex import production

REPO = Path(__file__).resolve().parents[4]
PLUGIN = REPO / "plugins" / "harness"
RUNTIME = PLUGIN / "runtime"

#: The production TOML fields, one by one. `cli_auth_credentials_store` and the
#: `env_key` value are AgentBox's evidence-based choices; every other field is
#: the official installer's shape with the guest catalogue path.
EXPECTED_CONFIG: dict = {
    "model": "deepseek-flash",
    "model_provider": "deepseek",
    "preferred_auth_method": "apikey",
    "forced_login_method": "api",
    "model_reasoning_effort": "high",
    "web_search": "disabled",
    "model_catalog_json": "/runtime/home/.codex/models.json",
    "cli_auth_credentials_store": "ephemeral",
    # The two official feature flags this deployment turns off, with the
    # first-hand evidence recorded in the state-error-boundary report:
    # `plugins` materializes the bundled plugin/skill corpus into
    # `$CODEX_HOME/.tmp/plugins/` (measured peak 5,529 files) and
    # `shell_snapshot` writes the credential-bearing environment dump into
    # `$CODEX_HOME/shell_snapshots/*.sh`.
    "features": {"plugins": False, "shell_snapshot": False},
    "model_providers": {
        "deepseek": {
            "name": "deepseek",
            "base_url": "https://api.deepseek.com/",
            "wire_api": "responses",
            "env_key": "CODEX_API_KEY",
        },
    },
}


from functools import partial
from ordessa_server.composition.harness_catalog import capture_harness_catalog
from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
from ordessa_execution_agents.harness.providers.declarations.capability_claims import capability_claims

from ordessa_harness_codex.registration_declarations import registration_declarations

# This brand's own test catalog is established explicitly here: the declarations
# are read through this brand's public port and composed by the neutral capture
# helper. Nothing is taken from the implicit global selection or another brand.
_brand_declarations = registration_declarations()
_captured_harness_catalog = capture_harness_catalog(
    (_brand_declarations,), launch_declarations=(_brand_declarations,))
registry_capabilities = partial(capability_claims, _captured_harness_catalog.registry)

def heredoc_bytes() -> bytes:
    """The bytes `write_models_json` writes, taken from the checked-in script.

    The installer writes the heredoc body plus the newline that ends its last
    line, which is what the comparison below reconstructs. Nothing is executed:
    the script is read as a byte string and split on the heredoc marker.
    """
    script = production.OFFICIAL_SCRIPT.read_bytes()
    marker = b"<<'CODEX_MODELS_JSON'\n"
    start = script.find(marker)
    assert start >= 0, "the checked-in script no longer carries the CODEX_MODELS_JSON heredoc"
    body_start = start + len(marker)
    body_end = script.find(b"\nCODEX_MODELS_JSON\n", body_start)
    assert body_end >= 0, "the heredoc is not terminated"
    return script[body_start:body_end] + b"\n"


def test_the_projected_catalogue_is_the_official_installer_bytes():
    """The canonical models.json equals the official heredoc and pinned 42-D bytes."""
    written = heredoc_bytes()
    projected = production.models_bytes()
    assert projected == written, "package deployment/models.json drifted from the official heredoc"
    metadata = production.official_script_metadata()
    assert metadata["sha256"] == hashlib.sha256(production.OFFICIAL_SCRIPT.read_bytes()).hexdigest()
    assert metadata["scriptVersion"] == "1.3.0"
    assert metadata["bytes"] == len(production.OFFICIAL_SCRIPT.read_bytes())
    assert metadata["heredoc"]["sha256"] == hashlib.sha256(projected).hexdigest()
    assert metadata["heredoc"]["bytes"] == len(projected)
    assert metadata["executed"] is False
    # Preserve the 42-D byte witness without keeping a second physical source.
    assert hashlib.sha256(projected).hexdigest() == "bce20f679495809f4fa6e48672b6dcbab84b6adff5251890b6e6a21eddb9c12f"
    assert metadata["heredoc"]["sha256"] == "bce20f679495809f4fa6e48672b6dcbab84b6adff5251890b6e6a21eddb9c12f"
    assert production.models_bytes() == written


def test_the_official_script_is_evidence_and_is_never_executed():
    """Nothing in the plugin runs the installer; only its bytes are compared."""
    import os
    import stat

    mode = os.stat(production.OFFICIAL_SCRIPT).st_mode
    assert not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), (
        "the checked-in installer must not be executable")
    references = []
    for path in sorted((PLUGIN / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "OFFICIAL_SCRIPT" in line and "subprocess" in line:
                references.append(f"{path.name}: {line.strip()}")
    assert references == [], f"the installer is spawned from plugin code: {references}"


def test_the_production_configuration_is_exactly_the_reviewed_fields():
    document = production.config_document()
    assert document == EXPECTED_CONFIG
    raw = production.config_bytes().decode("utf-8")
    assert "http://127.0.0.1" not in raw
    assert "https://api.deepseek.com/" in raw
    assert "experimental_bearer_token" not in raw
    assert "sk-" not in raw
    # The catalogue path is the guest path, not a host path and not /tmp.
    assert document["model_catalog_json"] == production.MODELS_TARGET
    assert production.MODELS_TARGET == f"{production.CODEX_HOME}/models.json"


def test_the_catalogue_holds_both_official_models_and_the_product_whitelist_is_narrower():
    catalogue = production.models_document()
    slugs = [item["slug"] for item in catalogue["models"]]
    assert slugs == ["deepseek-flash", "deepseek-v4-pro"]
    from ordessa_harness_codex import remote

    assert remote._DEEPSEEK_MODELS == frozenset({"deepseek-flash"})
    assert production.PRODUCT_MODEL_ID in remote._DEEPSEEK_MODELS
    assert "deepseek-v4-pro" not in remote._DEEPSEEK_MODELS


def test_loopback_override_changes_only_the_base_url():
    override = production.loopback_config_bytes("http://127.0.0.1:8080")
    differences = production.documented_differences("http://127.0.0.1:8080")
    assert differences == {
        "model_providers.deepseek.base_url": ("https://api.deepseek.com/", "http://127.0.0.1:8080"),
    }
    assert tomllib.loads(override.decode("utf-8"))["model"] == production.PRODUCT_MODEL_ID
    assert tomllib.loads(override.decode("utf-8"))["cli_auth_credentials_store"] == "ephemeral"
    # Producing an override never rewrites the reviewed file.
    assert production.config_document() == EXPECTED_CONFIG


def test_loopback_override_refuses_anything_but_a_loopback_url():
    for value in ("https://api.deepseek.com/", "http://0.0.0.0:1", "http://192.168.0.1:1", "", None):
        with pytest.raises(production.CodexProductionTemplateError):
            production.loopback_config_bytes(value)


def test_the_deployment_config_disables_the_two_official_state_churners():
    """The reviewed config turns off the two official feature flags whose
    default behaviour was first-hand observed to churn this deployment's state
    (plugin materialization) and to write the credential into native state
    (shell snapshots)."""
    from ordessa_harness_codex import production

    config = production.config_bytes().decode("utf-8")
    assert "[features]" in config
    assert "plugins = false" in config
    assert "shell_snapshot = false" in config
    for flag in production.OFFICIAL_FEATURE_FLAGS_OFF:
        assert flag in config


def test_the_deployment_document_declares_the_managed_chain():
    document = production.deployment_document(
        artifact_token="artifact",
        tree_digest="sha256:" + "a" * 64,
     capabilities_for=registry_capabilities)
    assert document["schemaVersion"] == 1
    # The document names no host path at all: the plugin root and every mount
    # token are the loader's business, not the file's.
    assert "pluginRoot" not in document
    harness = document["harnesses"][0]
    assert harness["id"] == "codex"
    assert harness["credentialKind"] == "api-key"
    assert harness["credentialEnvironment"] == "CODEX_API_KEY"
    assert harness["preferredAuthMethod"] == "api-key"
    assert harness["modelControlId"] == production.MODEL_CONTROL_ID
    assert harness["controlOptions"] == {production.MODEL_CONTROL_ID: []}
    assert harness["runtimeArtifactMounts"] == [{
        "token": "artifact",
        "target": "/runtime/artifacts/codex-runtime",
        "treeDigest": "sha256:" + "a" * 64,
    }]
    assert harness["stateProjection"] == {
        # §14: the declared state target is the *session subtree*; the rest
        # of $CODEX_HOME stays in the profile home and the ephemeral paths are
        # anchored on that home (see the room's ephemeral_anchor).
        "target": "/runtime/home/.codex/sessions",
        "ephemeralPaths": [".tmp", "shell_snapshots"],
    }
    assert harness["sessionStore"] == {"kind": "sessions-subtree"}
    assert harness["projectionFiles"] == [
        {"source": "deploy/codex/config.toml", "target": "/runtime/home/.codex/config.toml"},
        {"source": "deploy/codex/models.json", "target": "/runtime/home/.codex/models.json"},
    ]
    adapter = harness["adapter"]
    assert adapter["command"] == "/usr/bin/node"
    assert adapter["args"] == [
        "/runtime/artifacts/codex-runtime/node_modules/@agentclientprotocol/codex-acp/dist/index.js"]
    assert adapter["environment"] == {
        "CODEX_HOME": "/runtime/home/.codex", "NO_BROWSER": "1"}
    assert "DEEPSEEK_API_KEY" not in json.dumps(adapter["environment"])
    assert not any(
        token in key for key in adapter["environment"]
        for token in ("TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL", "AUTH")
    )


def test_the_adapter_entry_is_derived_from_the_artifact_target():
    assert production.ADAPTER_ARTIFACT_ENTRY.startswith(production.ARTIFACT_TARGET + "/")
    assert production.ADAPTER_ARTIFACT_ENTRY.endswith(production.ADAPTER_ARTIFACT_RELATIVE_ENTRY)
    assert production.ARTIFACT_TARGET == f"/runtime/artifacts/{production.ARTIFACT_NAME}"


def test_the_projected_files_exist_and_the_state_target_shares_the_home_root():
    for projection in production.projection_files():
        assert (production.DEPLOY_DIRECTORY / projection["source"].rsplit("/", 1)[-1]).is_file()
        assert projection["target"].startswith(f"{production.AGENT_HOME}/")
    # The explicit variable and the $HOME-derived default name the same directory.
    assert production.CODEX_HOME == f"{production.AGENT_HOME}/.codex"
    assert production.STATE_TARGET == f"{production.CODEX_HOME}/sessions"
    assert production.ADAPTER_ENVIRONMENT["CODEX_HOME"] == production.CODEX_HOME
    # Both read-only files live *inside* the writable state subtree; the Server
    # and bwrap derive them as protected state paths from this declaration alone.
    for projection in production.projection_files():
        assert projection["target"].startswith(production.CODEX_HOME + "/")


def test_the_deployment_document_refuses_invalid_artifact_declarations():
    # A token is a name, never a path, and the digest has to be a full sha256:
    # each of these is refused by the template rather than written into a
    # document that could not be bound on any machine.
    for token, digest in (("relative/path", "sha256:" + "a" * 64),
                          ("/srv/artifact", "sha256:" + "a" * 64),
                          ("Artifact", "sha256:" + "a" * 64),
                          ("a" * 33, "sha256:" + "a" * 64),
                          ("artifact", "sha256:short"),
                          ("artifact", "md5:" + "a" * 32)):
        with pytest.raises(production.CodexProductionTemplateError):
            production.deployment_document(artifact_token=token, tree_digest=digest, capabilities_for=registry_capabilities)


def test_the_product_model_needs_no_alias_and_the_sidecar_agrees():
    """Codex's catalogue spells the product model id exactly; no translation."""
    assert production.model_aliases() == {}
    assert production.native_model("deepseek-flash") == "deepseek-flash"
    assert production.native_model("other") == "other"
    assert production.native_model(None) is None
    script = (
        "import('" + (Path(__file__).resolve().parents[4] / 'apps/server/tests/support/profile_claims.mjs').as_uri() + "').then((module) =>"
        " process.stdout.write(JSON.stringify({"
        " aliases: module.AGENTBOX_MODEL_ALIASES,"
        " translated: module.resolveNativeModel('codex', 'deepseek-flash'),"
        " unknown: module.resolveNativeModel('codex', undefined) ?? null })))"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, env={**os.environ, "ORDESSA_TEST_PYTHON": sys.executable}, text=True,
                            timeout=60, cwd=str(REPO))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "codex" not in payload["aliases"]
    assert payload["translated"] == "deepseek-flash"
    assert payload["unknown"] is None


def test_the_observed_capabilities_are_claimed_only_after_the_chain_gate():
    """The template never promotes a static candidate into an observation."""
    claims = production.capability_claims(capabilities_for=registry_capabilities)
    observed = production.observed_capabilities()
    assert set(observed) <= {name for name, value in claims.items() if value}
    if not production.HAS_PRODUCTION_DEPLOYMENT:
        assert observed == frozenset()
    else:
        # A production deployment is only ever claimed on gate evidence, and the
        # gate observed at least the implementation-level operations.
        assert {"start", "stream", "finish", "observe"} <= set(observed)
        assert "attach" not in observed and "permissions" not in observed


def test_the_official_default_selection_stays_pi_only():
    """Establishing this brand's catalog above must not change the product default."""
    default_selection = capture_selected_harness_catalog()
    assert [definition.harness_type for definition in default_selection.registry.all()] == ["pi"]
