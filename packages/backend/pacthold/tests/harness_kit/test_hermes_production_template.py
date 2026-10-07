"""Hermes production template gates.

The template is only trustworthy if it is the *same* configuration Work Order
42-D prepared, if the parts the layers above must never learn stay out of it,
and if the two measured facts that shape it - where Hermes keeps its session
store, and why no product model control can be declared - are recorded rather
than assumed.
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ordessa_harness_hermes import production


REPO = Path(__file__).resolve().parents[5]
RUNTIME = REPO / "plugins" / "harness" / "runtime"
DEPLOY = REPO / "plugins" / "harness" / "deploy" / "hermes"


def as_json(value):
    """JSON-normalized comparison: key order and formatting are not identity."""
    return json.loads(json.dumps(value, sort_keys=True))


def load_bootstrap():
    """Load the artifact bootstrap by path, without writing bytecode beside it.

    The file stays the artifact copy: the builder publishes this exact file into
    the artifact's `site-packages`, so a stray `__pycache__` in `deploy/hermes`
    would be a (harmless but untidy) side effect of testing it.
    """
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        specification = importlib.util.spec_from_file_location(
            "agentbox_hermes_bootstrap_under_test", DEPLOY / "bootstrap.py",
        )
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def test_native_configuration_is_the_prepared_42d_configuration(tmp_path):
    """The checked-in template must equal the 42-D prepared configuration.

    `model-validation-42d.mjs` is where Work Order 42-D prepared the Hermes
    configuration. Sweeping a second, hand-written copy into the plugin is
    exactly how the production deployment and the accepted preparation would
    drift apart, so this runs the prepared path in `--dry-run` (with a
    throwaway token file the test creates) and demands field-by-field equality.
    """
    token = tmp_path / "not-a-real-token"
    token.write_bytes(b"hermes-template-test-token")
    token.chmod(0o600)
    result = subprocess.run(
        ["node", str(Path(__file__).resolve().parents[5] / "plugins/harness/packaging" / "builders" / "model-validation-42d.mjs"),
         "--family", "hermes", "--secret-file", str(token), "--dry-run"],
        capture_output=True, text=True, timeout=180, cwd=str(REPO),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prepared = json.loads(result.stdout.strip().splitlines()[-1])
    assert prepared["outcome"] == "PREPARED"
    assert as_json(prepared["config"]) == as_json(production.config_document())
    assert production.config_yaml_text() == (
        REPO / "plugins" / "harness" / "deploy" / "hermes" / "config.yaml"
    ).read_text(encoding="utf-8")
    # The template references an environment variable and carries no material.
    assert "hermes-template-test-token" not in production.config_yaml_text()
    assert "key_env: DEEPSEEK_API_KEY" in production.config_yaml_text()
    assert "sk-" not in production.config_yaml_text()


def test_production_template_pins_the_confirmed_model_and_official_root():
    document = production.config_document()
    provider = document["providers"][production.PROVIDER_BLOCK_KEY]
    assert production.PRODUCT_MODEL_ID == "deepseek-flash"
    assert production.NATIVE_MODEL_VALUE == "deepseek-flash"
    # The product's provider identity stays DeepSeek official - it lives in the
    # declared block's content (root, credential reference, catalogue), not in the
    # key Hermes resolves.
    assert production.HERMES_PROVIDER == "deepseek"
    assert production.PROVIDER_BLOCK_KEY == "custom"
    assert provider["name"] == "DeepSeek official"
    assert provider["api"] == production.OFFICIAL_BASE_URL == "https://api.deepseek.com"
    assert document["model"]["base_url"] == production.OFFICIAL_BASE_URL
    # The model is declared through Hermes' user-defined-provider kind, not through
    # the built-in `deepseek` provider: the built-in one rewrites the model id
    # before the request (only first-class `deepseek-v<digit>...` ids and
    # reasoner-like names survive; everything else becomes `deepseek-chat`), which
    # would send a model id the product never declared. A custom provider passes
    # the id through unchanged.
    assert production.MODEL_PROVIDER_DECLARATION == production.PROVIDER_BLOCK_KEY == "custom"
    assert document["model"]["provider"] == production.MODEL_PROVIDER_DECLARATION
    assert production.MODEL_PROVIDER_DECLARATION != production.HERMES_PROVIDER
    # Measured: the block is keyed by the bare kind, because Hermes persists the
    # resolved provider identity and resumes through it; a `custom:<key>`
    # reference would leave a resumed session without this block (placeholder
    # credential). The key must therefore equal Hermes' resolved identity.
    assert production.MODEL_PROVIDER_DECLARATION == production.NATIVE_PROVIDER_IDENTITY
    assert production.NATIVE_MODEL_SELECTION == "custom:deepseek-flash"
    assert document["model"]["default"] == production.PRODUCT_MODEL_ID
    # Order 108 (AQ-0004): the checked-in template carries the permissive
    # production default, not the gate-era 64 that truncated answers.
    assert document["model"]["max_tokens"] == production.DEFAULT_OUTPUT_TOKEN_LIMIT == 8192
    assert provider["key_env"] == production.CREDENTIAL_ENVIRONMENT == "DEEPSEEK_API_KEY"
    assert provider["extra_body"]["thinking"] == {"type": "disabled"}
    assert provider["transport"] == "chat_completions"
    # The block a built-in declaration would have used is the same content:
    # provider, root, credential reference and catalogue did not change - only
    # which Hermes provider kind resolves them.
    assert provider["default_model"] == production.PRODUCT_MODEL_ID
    assert provider["models"] == {production.PRODUCT_MODEL_ID: {}}


def test_the_retry_bound_is_the_lowest_supported_and_declared():
    """One retry is the floor: Hermes' agent retries once, so two attempts max."""
    document = production.config_document()
    assert document["agent"]["api_max_retries"] == production.API_MAX_RETRIES == 1
    assert production.MAX_PROVIDER_ATTEMPTS == production.API_MAX_RETRIES + 1 == 2
    # The gate's budget is what an endpoint may see for one prompt; it may never
    # be lowered below the declared retry bound.
    assert production.MAX_PROVIDER_ATTEMPTS >= production.API_MAX_RETRIES + 1


def test_loopback_override_changes_only_the_two_endpoint_fields():
    override = production.loopback_config_document("http://127.0.0.1:8080")
    differences = production.documented_differences("http://127.0.0.1:8080")
    assert sorted(differences) == ["model.base_url", f"providers.{production.PROVIDER_BLOCK_KEY}.api"]
    for before, after in differences.values():
        assert before == "https://api.deepseek.com"
        assert after == "http://127.0.0.1:8080"
    # The endpoint override inherits the permissive production default (order
    # 108): only the two endpoint fields differ, and everything else - ceiling
    # included - matches the template.
    assert override["model"]["max_tokens"] == production.DEFAULT_OUTPUT_TOKEN_LIMIT == 8192
    assert override["agent"] == production.config_document()["agent"]
    assert override["providers"][production.PROVIDER_BLOCK_KEY]["models"] == (
        production.config_document()["providers"][production.PROVIDER_BLOCK_KEY]["models"])
    # Reproducing the override never rewrites the projection source.
    assert production.config_document()["model"]["base_url"] == production.OFFICIAL_BASE_URL
    assert "127.0.0.1" not in production.config_yaml_text()
    rendered = production.loopback_config_yaml("http://127.0.0.1:8080")
    assert "base_url: http://127.0.0.1:8080" in rendered
    assert "api: http://127.0.0.1:8080" in rendered


def test_gate_projection_pins_the_gate_ceiling_while_the_template_stays_permissive():
    """Order 108 G2: the fixture a chain gate projects carries 64, not 8192.

    `loopback_config_document` is the endpoint-only override (it inherits the
    permissive default); `gate_projected_config_document` and the serialized
    `loopback_config_yaml` the gate mounts pin `model.max_tokens` to the gate's
    own OUTPUT_TOKEN_LIMIT. If the pin were removed the gate would project 8192
    and its request budget would no longer be bounded - the counter-example.
    """
    assert production.loopback_config_document(
        "http://127.0.0.1:8080")["model"]["max_tokens"] == production.DEFAULT_OUTPUT_TOKEN_LIMIT
    assert production.gate_projected_config_document(
        "http://127.0.0.1:8080")["model"]["max_tokens"] == production.OUTPUT_TOKEN_LIMIT == 64
    rendered = production.loopback_config_yaml("http://127.0.0.1:8080")
    assert "max_tokens: 64" in rendered
    assert "max_tokens: 8192" not in rendered


def test_loopback_override_refuses_anything_but_a_loopback_url():
    for value in ("https://api.deepseek.com", "http://0.0.0.0:1", "http://192.168.0.1:1", "", None):
        with pytest.raises(production.HermesProductionTemplateError):
            production.loopback_config_document(value)


def test_deployment_document_declares_the_managed_chain():
    document = production.deployment_document(
        artifact_token="artifact",
        tree_digest="sha256:" + "a" * 64,
    )
    assert document["schemaVersion"] == 1
    # The document names no host path at all: the plugin root and every mount
    # token are the loader's business, not the file's.
    assert "pluginRoot" not in document
    harness = document["harnesses"][0]
    assert harness["id"] == "hermes"
    assert harness["credentialKind"] == "api-key"
    assert harness["credentialEnvironment"] == "DEEPSEEK_API_KEY"
    # Measured: Hermes 0.19 advertises no ACP `configOptions`, and the pinned
    # bridge can only select a model through that list, so a declared model
    # control would make every round fail before any provider request. The
    # production template therefore declares none.
    assert production.MODEL_CONTROL_ID is None
    assert "modelControlId" not in harness
    assert "controlOptions" not in harness
    assert harness["runtimeArtifactMounts"] == [{
        "token": "artifact",
        "target": "/runtime/artifacts/hermes-runtime",
        "treeDigest": "sha256:" + "a" * 64,
    }]
    assert harness["stateProjection"] == {"target": "/runtime/home/.hermes"}
    assert "sessionStore" not in harness  # shared-DB family: library stays in the home
    assert harness["stateProjection"]["target"] == production.STATE_TARGET
    assert harness["projectionFiles"] == [
        {"source": "deploy/hermes/config.yaml", "target": "/runtime/home/.hermes/config.yaml"},
    ]
    # The projected configuration sits *inside* Hermes' own home, at exactly the
    # path Hermes reads it from, and is therefore a protected state path: the
    # read-only file is not state and never reaches a checkpoint.
    assert harness["projectionFiles"][0]["target"] == production.CONFIG_TARGET
    assert Path(harness["projectionFiles"][0]["target"]).parent == Path(production.AGENT_HOME)
    assert production.STATE_TARGET == production.AGENT_HOME
    adapter = harness["adapter"]
    assert adapter["command"] == "/usr/bin/python3"
    assert adapter["args"] == ["-m", "hermes_cli.main", "acp"]
    assert production.ENTRY_RELATIVE == production.ENTRY_MODULE.replace(".", "/") + ".py"
    environment = adapter["environment"]
    assert environment["PYTHONPATH"] == (
        "/runtime/artifacts/hermes-runtime/site-packages")
    assert environment["PYTHONPATH"] == production.ARTIFACT_SITE_PACKAGES
    assert environment["HERMES_HOME"] == production.STATE_TARGET
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["HERMES_IGNORE_USER_CONFIG"] == "1"
    assert environment["HERMES_IGNORE_RULES"] == "1"
    assert environment["HERMES_SKIP_NODE_BOOTSTRAP"] == "1"
    assert environment["HERMES_MAX_ITERATIONS"] == "1"
    # The environment mirrors the prepared declaration: the provider value is the
    # same custom-provider reference the configuration resolves.
    assert environment["HERMES_TUI_PROVIDER"] == production.MODEL_PROVIDER_DECLARATION
    assert environment["HERMES_INFERENCE_PROVIDER"] == production.MODEL_PROVIDER_DECLARATION
    assert environment["HERMES_MODEL"] == production.NATIVE_MODEL_VALUE
    # The output ceiling is not an environment key: the Server's deployment
    # validation refuses credential-shaped keys and `HERMES_MAX_TOKENS` matches
    # its `TOKEN` pattern. It is declared in the projected configuration
    # (`model.max_tokens`) and asserted on the wire by the chain gate.
    assert "HERMES_MAX_TOKENS" not in environment
    assert production.config_document()["model"]["max_tokens"] == production.DEFAULT_OUTPUT_TOKEN_LIMIT
    assert not any("TOKEN" in key for key in environment)
    # Nothing test-only may leak into the production default: no preloaded
    # guard, no audit paths, no credential material anywhere.
    assert "DEEPSEEK_API_KEY" not in json.dumps(environment)
    for key in ("NODE_OPTIONS", "AGENTBOX_EGRESS_AUDIT", "AGENTBOX_ACP_AUDIT"):
        assert key not in environment
    assert not any(key.startswith("AGENTBOX_") for key in environment)
    rendered = json.dumps(document)
    assert "127.0.0.1" not in rendered
    assert "loopback" not in rendered
    assert "sitecustomize" not in rendered


def test_a_model_control_can_only_be_declared_explicitly_for_a_gate():
    """The gate needs the declared-control variant to demonstrate the refusal."""
    variant = production.deployment_document(
        artifact_token="artifact",
        tree_digest="sha256:" + "a" * 64,
        model_control_id="model",
    )
    assert variant["harnesses"][0]["modelControlId"] == "model"
    assert variant["harnesses"][0]["controlOptions"] == {"model": []}
    # The production default is unaffected by producing the variant.
    assert "modelControlId" not in production.deployment_document(
        artifact_token="artifact",
        tree_digest="sha256:" + "a" * 64,
    )["harnesses"][0]


def test_projection_and_overlay_files_exist_next_to_the_deployment_template():
    for projection in production.projection_files():
        assert (production.PLUGIN_ROOT / projection["source"]).is_file()
        assert Path(projection["target"]).parent == Path(production.AGENT_HOME)
    assert production.CONFIG_TEMPLATE.is_file()
    assert production.LOOPBACK_GUARD.is_file()
    # The gate's guard goes into the same protected home: it is a read-only
    # projection for this run only, never part of the production deployment.
    assert production.LOOPBACK_GUARD_TARGET == f"{production.AGENT_HOME}/sitecustomize.py"
    assert production.LOOPBACK_GUARD_TARGET.startswith(production.AGENT_HOME + "/")
    assert production.LOOPBACK_GUARD_TARGET not in json.dumps(production.projection_files())
    assert (DEPLOY / "bootstrap.py").is_file()
    assert (DEPLOY / "sitecustomize.py").is_file()
    # The artifact publishes the same two names the deployment relies on.
    assert production.BOOTSTRAP_MODULE == "agentbox_hermes_bootstrap"
    assert (DEPLOY / "bootstrap.py").read_text(encoding="utf-8").count("def apply()") == 1


def test_the_guest_home_is_the_one_isolated_root_and_both_paths_converge():
    """One home root: `HERMES_HOME` and `$HOME/.hermes` are the same directory."""
    assert production.AGENT_HOME == "/runtime/home/.hermes"
    assert production.STATE_TARGET == production.AGENT_HOME
    guest_home = "/runtime/home"
    assert production.AGENT_HOME == f"{guest_home}/.hermes"
    assert production.CONFIG_TARGET == f"{production.STATE_TARGET}/config.yaml"


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
        with pytest.raises(production.HermesProductionTemplateError):
            production.deployment_document(artifact_token=token, tree_digest=digest)


def test_product_model_passes_through_and_the_sidecar_glue_has_no_alias():
    """The alias must exist in one place only - and for Hermes there is none.

    The deployment template is Python; the translation (if any) is applied inside
    the sidecar process, which is JavaScript. Hermes resolves its model in its own
    catalogue under the same spelling, so both sides must agree that there is
    nothing to translate.
    """
    assert production.model_aliases() == {}
    assert production.native_model("deepseek-flash") == "deepseek-flash"
    script = (
        "import('" + (RUNTIME / "profile_extensions.mjs").as_uri() + "').then((module) =>"
        " process.stdout.write(JSON.stringify({"
        " aliases: module.AGENTBOX_MODEL_ALIASES,"
        " hermesAlias: module.AGENTBOX_MODEL_ALIASES.hermes ?? null,"
        " translated: module.resolveNativeModel('hermes', 'deepseek-flash'),"
        " empty: module.resolveNativeModel('hermes', undefined) ?? null })))"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                            timeout=60, cwd=str(REPO))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hermesAlias"] is None
    assert payload["translated"] == production.PRODUCT_MODEL_ID
    assert payload["empty"] is None
    assert "hermes" not in payload["aliases"]
    assert "pi" in payload["aliases"], "the alias mechanism must still be table-driven"


def test_only_one_configuration_copy_exists_in_the_plugin():
    """No second, drifting model configuration may live next to the template."""
    present = {item.name for item in DEPLOY.iterdir() if item.name != "__pycache__"}
    assert present == {"config.yaml", "bootstrap.py", "sitecustomize.py", "loopback-guard.py"}
    package_directory = Path(production.__file__).parent
    for item in package_directory.iterdir():
        assert item.suffix not in {".yaml", ".json", ".yml"}, (
            f"{item} looks like a second configuration copy; the template owns deploy/hermes/config.yaml")
    assert production.CONFIG_TEMPLATE.parent == DEPLOY


def test_the_bootstrap_verifies_the_projected_configuration_in_place(tmp_path):
    """The artifact verifies the reviewed file; it never writes one.

    The reviewed `config.yaml` is a read-only projection *inside* the home, so
    there is nothing to materialize and nothing that may be rewritten.  What the
    module still owns is the fail-closed check: Hermes must never start when the
    projected configuration is missing, unreadable, empty or a symlink.
    """
    module = load_bootstrap()
    assert module.HOME_ROOT == "/runtime/home"
    assert module.HOME_ENVIRONMENT == "HERMES_HOME"
    assert module.CONFIG_NAME == production.CONFIG_NAME
    home = tmp_path / "home"
    home.mkdir()
    config = home / production.CONFIG_NAME
    config.write_text(production.config_yaml_text(), encoding="utf-8")
    # A controlled stand-in for the projected read-only bind: the deployment
    # mounts the reviewed file read-only, and so does this fixture.
    config.chmod(0o444)
    audit = tmp_path / "audit"
    # The isolated root is the anchor the check is written against; the test
    # points it at its own controlled directory so nothing outside `tmp_path`
    # is ever read or written.
    isolated_root = module.HOME_ROOT
    module.HOME_ROOT = str(tmp_path)
    os.environ["HERMES_HOME"] = str(home)
    os.environ[module.AUDIT_ENVIRONMENT] = str(audit)
    try:
        outcome = module.apply()
        assert outcome["config"] == "verified"
        assert outcome["path"] == str(config)
        assert outcome["bytes"] == config.stat().st_size
        assert outcome["digest"] == "sha256:" + hashlib.sha256(config.read_bytes()).hexdigest()
        # Nothing was written: the reviewed bytes are still the projected bytes.
        assert config.read_text(encoding="utf-8") == production.config_yaml_text()
        lines = audit.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1 and lines[0].startswith("bootstrap-verified ")
        assert f"digest={outcome['digest']}" in lines[0]
        assert "posture=read-only" in lines[0]
        # A *writable* reviewed configuration is refused: the deployment's whole
        # point is that nothing can rewrite the endpoint of the next turn.
        config.chmod(0o600)
        with pytest.raises(module.HermesBootstrapError) as writable:
            module.apply()
        assert "WRITABLE" in str(writable.value)
        config.chmod(0o444)
        # A missing, empty or symlinked configuration is fatal, not tolerated.
        config.unlink()
        with pytest.raises(module.HermesBootstrapError):
            module.apply()
        config.write_text("", encoding="utf-8")
        config.chmod(0o444)
        with pytest.raises(module.HermesBootstrapError):
            module.apply()
        config.unlink()
        config.symlink_to(production.CONFIG_TEMPLATE)
        with pytest.raises(module.HermesBootstrapError):
            module.apply()
        # A home that is not inside the isolated root is refused as well.
        module.HOME_ROOT = isolated_root
        for value in ("", "relative/home", "/tmp/agentbox-home", "/home/tester/.hermes"):
            os.environ["HERMES_HOME"] = value
            with pytest.raises(module.HermesBootstrapError):
                module.apply()
    finally:
        module.HOME_ROOT = isolated_root
        os.environ.pop("HERMES_HOME", None)
        os.environ.pop(module.AUDIT_ENVIRONMENT, None)


def test_the_artifact_sitecustomize_fails_loudly_and_delegates():
    """A managed Hermes must never start without its reviewed configuration."""
    text = (DEPLOY / "sitecustomize.py").read_text(encoding="utf-8")
    assert "import agentbox_hermes_bootstrap" in text
    assert "SystemExit" in text
    # CPython swallows ordinary exceptions from sitecustomize, so the failure
    # must be a SystemExit to actually stop the adapter process.
    assert "raise SystemExit" in text


def test_the_gate_guard_is_test_only_and_delegates_to_the_bootstrap():
    guard = production.LOOPBACK_GUARD.read_text(encoding="utf-8")
    assert "import agentbox_hermes_bootstrap" in guard
    assert "AGENTBOX_EGRESS_AUDIT" in guard
    assert "AGENTBOX_ACP_AUDIT" in guard
    assert "self-test-ok" in guard
    # The guard also reads the adapter's own ACP model state back (`acp-model`
    # lines), so the native identity of the model is a measurement of the real
    # chain rather than a derivation from the configuration.
    assert "acp-model" in guard
    assert "def _record_model_state" in guard
    assert "inspect.iscoroutinefunction" in guard
    # It is preloaded by the gate through PYTHONPATH only: the production
    # environment names neither the guard nor its audit sinks.
    environment = production.ADAPTER_ENVIRONMENT
    assert not any("AGENTBOX" in key for key in environment)
    assert production.LOOPBACK_GUARD_TARGET not in json.dumps(environment)
    assert production.LOOPBACK_GUARD_TARGET not in json.dumps(production.projection_files())


def test_the_gate_can_build_an_artifact_only_from_a_built_artifact_endpoint():
    """The gate needs the entry point inside the artifact, not a host path."""
    assert production.ARTIFACT_SITE_PACKAGES.startswith(production.ARTIFACT_TARGET + "/")
    assert production.ADAPTER_ARGS[0] == "-m"
    assert production.ADAPTER_ARGS[1] == production.ENTRY_MODULE
    assert production.ADAPTER_ARGS[-1] == "acp"
    assert production.ADAPTER_COMMAND == "/usr/bin/python3"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
