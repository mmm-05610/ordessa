"""Hermes production chain gates that do not need a model or a sandbox.

The chain gate itself drives a real Worker and a real Hermes ACP adapter; the
parts of it that decide whether a run *passed* are ordinary functions, and they
are asserted here: what the fake endpoint records and refuses, what the
deployment layer accepts, what the sandbox posture check refuses, and what the
cleanup path does when it cannot remove something.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.request

import pytest

from ordessa_server.bootstrap import build_runtime_from_sidecar_deployment
from ordessa_harness.hermes import production


REPO = Path(__file__).resolve().parents[3]
GATE_PATH = REPO / "scripts" / "server-round1" / "hermes-production-chain-gate.py"


def load_gate():
    specification = importlib.util.spec_from_file_location("hermes_chain_gate_under_test", GATE_PATH)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return load_gate()


# -- the fake endpoint -------------------------------------------------------

def post(url: str, body: dict, token: str | None = None) -> bytes:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - loopback only
        return response.read()


def test_the_fake_endpoint_binds_loopback_and_never_records_the_token(gate):
    endpoint = gate.FakeEndpoint(gate.FAKE_TOKEN)
    try:
        endpoint.assert_loopback_only()
        endpoint.start()
        endpoint.begin_phase("unit", 1)
        payload = post(f"{endpoint.base_url}/chat/completions", {
            "model": "deepseek-flash", "max_tokens": 64, "stream": True,
            "messages": [{"role": "user", "content": f"remember {gate.NONCE_ROUND_1}"}],
        }, token=gate.FAKE_TOKEN)
        assert b"data:" in payload
        snapshot = endpoint.snapshot()
        assert snapshot["unauthorizedRequests"] == 0
        assert snapshot["requestsBeyondBudget"] == 0
        recorded = snapshot["requests"][0]
        assert recorded["authorizationMatchesInjectedToken"] is True
        assert recorded["structure"]["model"] == "deepseek-flash"
        assert recorded["structure"]["maxTokens"] == 64
        assert recorded["structure"]["messages"][0]["containsRound1User"] is True
        # The structure is what gets reported: the token value itself never is.
        assert gate.FAKE_TOKEN not in json.dumps(snapshot)
    finally:
        endpoint.stop()


def test_the_fake_endpoint_refuses_a_request_beyond_its_phase_budget(gate):
    endpoint = gate.FakeEndpoint(gate.FAKE_TOKEN)
    try:
        endpoint.start()
        endpoint.begin_phase("model-control", 0)
        post(f"{endpoint.base_url}/chat/completions", {"model": "x", "messages": []},
             token=gate.FAKE_TOKEN)
        assert endpoint.over_budget == 1
        assert len(endpoint.phase_requests("model-control")) == 1
    finally:
        endpoint.stop()


def test_the_fake_endpoint_counts_an_unauthorized_bearer(gate):
    endpoint = gate.FakeEndpoint(gate.FAKE_TOKEN)
    try:
        endpoint.start()
        endpoint.begin_phase("unit", 2)
        post(f"{endpoint.base_url}/chat/completions", {"model": "x", "messages": []}, token="wrong")
        assert endpoint.unauthorized == 1
    finally:
        endpoint.stop()


# -- postures and evidence the gate asserts ----------------------------------

def test_the_sandbox_posture_requires_exactly_two_writable_binds(gate):
    good = [
        "--dir", "/workspace", "--ro-bind", "/usr", "/usr",
        "--bind", "/host/workspace", "/workspace",
        "--ro-bind", "/host/artifact", production.ARTIFACT_TARGET,
        "--ro-bind", "/host/view", "/runtime/view",
        "--ro-bind", "/host/secret", "/runtime/secret/credential",
        "--bind", "/host/state", production.STATE_TARGET,
    ]
    outcome = gate.assert_worker_posture([good], production.ARTIFACT_TARGET, production.STATE_TARGET)
    assert outcome["writableTargets"] == [production.STATE_TARGET, "/workspace"]
    assert production.ARTIFACT_TARGET in outcome["readOnlyTargets"]
    with pytest.raises(gate.GateFailure) as extra:
        gate.assert_worker_posture(
            [[*good, "--bind", "/host/home", "/home/maoqh"]],
            production.ARTIFACT_TARGET, production.STATE_TARGET)
    assert extra.value.code == "HERMES_GATE_WRITABLE_MOUNT_UNEXPECTED"
    with pytest.raises(gate.GateFailure) as unmounted:
        gate.assert_worker_posture(
            [[token for token in good if token != production.ARTIFACT_TARGET]],
            production.ARTIFACT_TARGET, production.STATE_TARGET)
    assert unmounted.value.code == "HERMES_GATE_ARTIFACT_NOT_MOUNTED"


def test_continuation_evidence_requires_the_first_round_in_the_second_request(gate):
    good = [{
        "structure": {
            "maxTokens": 64, "model": gate.WIRE_MODEL_ID, "stream": True, "toolCount": 3,
            "messages": [
                {"role": "system", "chars": 100},
                {"role": "user", "chars": 40, "containsRound1User": True},
                {"role": "assistant", "chars": 13, "containsRound1Assistant": True},
                {"role": "user", "chars": 30},
            ],
        },
    }]
    evidence = gate.continuation_evidence(good)
    assert evidence["round2CarriesRound1User"] is True
    assert evidence["round2CarriesRound1Assistant"] is True
    assert evidence["maxTokens"] == 64
    assert evidence["model"] == gate.WIRE_MODEL_ID

    without_context = [{
        "structure": {
            "maxTokens": 64, "stream": True, "model": gate.WIRE_MODEL_ID,
            "messages": [{"role": "system", "chars": 1}, {"role": "user", "chars": 2}],
        },
    }]
    with pytest.raises(gate.GateFailure) as missing:
        gate.continuation_evidence(without_context)
    assert missing.value.code == "HERMES_GATE_ROUND2_CONTEXT_MISSING"

    over_ceiling = [{
        "structure": {
            "maxTokens": 4096, "stream": True, "model": gate.WIRE_MODEL_ID,
            "messages": [
                {"role": "user", "containsRound1User": True},
                {"role": "assistant", "containsRound1Assistant": True},
            ],
        },
    }]
    with pytest.raises(gate.GateFailure) as ceiling:
        gate.continuation_evidence(over_ceiling)
    assert ceiling.value.code == "HERMES_GATE_OUTPUT_CEILING_EXCEEDED"


def test_the_wire_model_is_the_product_id_and_is_asserted(gate):
    """The provider request carries the product id itself, and that is pinned.

    The prepared configuration declares `model.default: deepseek-flash` through
    Hermes' user-defined-provider kind (`custom`), which passes the id through
    unchanged, so the provider must receive exactly the product id. The value this
    gate previously accepted (`deepseek-chat`, Hermes' fold under the built-in
    provider) is now a hard failure: a harness that silently re-resolves the
    model, or a deployment that changes it, cannot pass.
    """
    observed: list = []
    assert gate.WIRE_MODEL_ID == "deepseek-flash"
    assert gate.NATIVE_MODEL_SELECTION == "custom:deepseek-flash"
    assert gate.NATIVE_PROVIDER_IDENTITY == "custom"
    assert production.config_document()["model"]["default"] == production.PRODUCT_MODEL_ID
    assert production.config_document()["model"]["provider"] == production.MODEL_PROVIDER_DECLARATION
    assert production.NATIVE_MODEL_VALUE == production.PRODUCT_MODEL_ID == gate.WIRE_MODEL_ID
    gate.assert_wire_model({"model": gate.WIRE_MODEL_ID}, "unit", observed)
    assert observed == [{"phase": "unit", "model": "deepseek-flash"}]
    for drifted in ("deepseek-chat", "deepseek/deepseek-flash", "deepseek-v4-flash", "", None):
        with pytest.raises(gate.GateFailure) as failure:
            gate.assert_wire_model({"model": drifted}, "unit", observed)
        assert failure.value.code == "HERMES_GATE_WIRE_MODEL_DRIFT"


def test_the_credential_must_reach_the_provider_on_every_round(gate):
    """A provider request without the injected bearer is a gate failure.

    In live mode the request headers are not observable at all, so the field is
    `None` and the witness is the real answer - and that inference has to be
    *labelled* as one, or a constant would be passed off as an observation.
    """
    gate.assert_credential_delivery({
        "injectedTokenReachedProvider": True, "unauthorizedRequests": 0})
    gate.assert_credential_delivery({
        "injectedTokenReachedProvider": None, "unauthorizedRequests": None,
        "credentialObservation": "inferred-from-real-answer; request headers are not observable live",
    })
    for credential in (
        {"injectedTokenReachedProvider": False, "unauthorizedRequests": 1},
        {"injectedTokenReachedProvider": True, "unauthorizedRequests": 1},
        {"injectedTokenReachedProvider": False, "unauthorizedRequests": 0},
        {},
    ):
        with pytest.raises(gate.GateFailure) as refused:
            gate.assert_credential_delivery(credential)
        assert refused.value.code == "HERMES_GATE_CREDENTIAL_NOT_DELIVERED"

    # Live mode without the label is its own failure: an unlabelled `None` would
    # be indistinguishable from "nothing was checked".
    with pytest.raises(gate.GateFailure) as unlabelled:
        gate.assert_credential_delivery({
            "injectedTokenReachedProvider": None, "unauthorizedRequests": None})
    assert unlabelled.value.code == "HERMES_GATE_CREDENTIAL_OBSERVATION_UNLABELLED"


def test_the_native_model_state_is_read_back_from_the_guard(gate, tmp_path):
    """The ACP model state Hermes answered with is an observation, and it is pinned."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    audit = workspace / gate.ACP_AUDIT_NAME
    audit.write_text(
        "acp-instrumented new_session,load_session,resume_session,set_session_model,set_config_option\n"
        "acp-method new_session pid=1\n"
        "acp-model new_session current=custom:deepseek-flash available=custom:deepseek-flash\n"
        "acp-method resume_session pid=2\n"
        "acp-model resume_session current=custom:deepseek-flash available=custom:deepseek-flash\n",
        encoding="utf-8",
    )
    record = gate.native_model_observation(workspace)
    assert record["currentModelIds"] == [gate.NATIVE_MODEL_SELECTION]
    assert record["availableModelIds"] == [gate.NATIVE_MODEL_SELECTION]
    assert [item["method"] for item in record["records"]] == ["new_session", "resume_session"]
    assert record["expectedNativeProviderIdentity"] == "custom"
    # A harness that re-resolves the model is caught, whatever spelling it uses.
    audit.write_text(
        "acp-model new_session current=deepseek:deepseek-chat available=deepseek:deepseek-chat\n",
        encoding="utf-8",
    )
    with pytest.raises(gate.GateFailure) as drifted:
        gate.native_model_observation(workspace)
    assert drifted.value.code == "HERMES_GATE_NATIVE_MODEL_DRIFT"
    # No recorded model state at all is a failure too: the assertion must not
    # pass vacuously when the observation channel breaks.
    audit.write_text("acp-method new_session pid=1\n", encoding="utf-8")
    with pytest.raises(gate.GateFailure) as unobserved:
        gate.native_model_observation(workspace)
    assert unobserved.value.code == "HERMES_GATE_NATIVE_MODEL_UNOBSERVED"


def test_the_pass_through_declaration_is_derived_from_the_artifact_not_assumed(gate, tmp_path):
    """The conclusion cites the artifact's normalizer and evaluates its predicates."""
    # Both user-defined-provider spellings are recognized; the built-in provider
    # (and anything that only looks like a prefix) is not.
    assert gate.is_custom_provider_declaration("custom") is True
    assert gate.is_custom_provider_declaration("custom:deepseek") is True
    for value in ("deepseek", "customs", "custom ", "", None):
        assert gate.is_custom_provider_declaration(value) is False, value
    artifact = tmp_path / "artifact"
    normalizer = artifact / "site-packages" / "hermes_cli"
    normalizer.mkdir(parents=True)
    (normalizer / "model_normalize.py").write_text(
        "import re\n"
        "_DEEPSEEK_V_SERIES_RE = re.compile(r'^deepseek-v\\d+([-.].+)?$')\n"
        "def _normalize_for_deepseek(model_name):\n"
        "    bare = model_name.lower()\n"
        "    if _DEEPSEEK_V_SERIES_RE.match(bare):\n"
        "        return bare\n"
        "    return 'deepseek-chat'\n"
        "def normalize_model_for_provider(name, provider):\n"
        "    if provider == 'deepseek':\n"
        "        return _normalize_for_deepseek(name)\n"
        "    # --- Custom & all others: pass through as-is ---\n"
        "    return name\n".replace("'", '"'),
        encoding="utf-8",
    )
    record = gate.model_resolution_witness(artifact, "custom:deepseek", "deepseek-flash")
    assert record["configuredProviderDeclaration"] == "custom:deepseek"
    assert record["wireModel"] == gate.WIRE_MODEL_ID
    assert record["networkDependent"] is False
    assert record["witness"]["declarationIsCustomProvider"] is True
    assert record["witness"]["builtinProviderWouldFold"] is True
    assert record["witness"]["passthroughPatternMatched"] is False
    assert record["witness"]["reasonerPrefixMatched"] is False
    assert record["witness"]["foldReturnPresent"] is True
    assert record["witness"]["customPassThroughPresent"] is True
    assert record["artifactRuleFile"] == "site-packages/hermes_cli/model_normalize.py"
    # A first-class DeepSeek id would survive the built-in provider, so the
    # pass-through declaration would not be needed - the gate refuses that as
    # this deployment's declaration, exactly as it refuses a built-in provider.
    for provider in ("custom:deepseek",):
        with pytest.raises(gate.GateFailure) as unexpected:
            gate.model_resolution_witness(artifact, provider, "deepseek-v4-flash")
        assert unexpected.value.code == "HERMES_GATE_MODEL_DECLARATION_UNEXPECTED"
    with pytest.raises(gate.GateFailure) as builtin:
        gate.model_resolution_witness(artifact, "deepseek", "deepseek-flash")
    assert builtin.value.code == "HERMES_GATE_MODEL_DECLARATION_UNEXPECTED"
    # An artifact without the reviewed normalizer is a hard failure.
    (normalizer / "model_normalize.py").unlink()
    with pytest.raises(gate.GateFailure) as unreadable:
        gate.model_resolution_witness(artifact, "custom:deepseek", "deepseek-flash")
    assert unreadable.value.code == "HERMES_GATE_MODEL_NORMALIZER_UNREADABLE"


def test_egress_refusals_are_classified_fail_closed(gate):
    """Only the three reviewed non-loopback classes may appear in the audit."""
    classes = gate.EGRESS_CLASSES
    assert classes["guard-self-test"] == (gate.GUARD_SELF_TEST_HOST,)
    assert "models.dev" in classes["harness-catalog-probe"]
    assert "openrouter.ai" in classes["harness-catalog-probe"]
    assert classes["provider-default-endpoint"] == ("api.deepseek.com",)
    classified = "denied getaddrinfo models.dev:None"
    for name, hosts in classes.items():
        destination = classified.split()[2]
        host = destination.rsplit(":", 1)[0]
        if host in hosts:
            assert name == "harness-catalog-probe"
            break
    else:  # pragma: no cover - the class table itself is the assertion
        raise AssertionError("models.dev must be a reviewed class")
    for unknown in ("denied connect example.invalid:443", "denied create_connection 10.0.0.1:443"):
        destination = unknown.split()[2]
        host = destination.rsplit(":", 1)[0]
        assert all(host not in hosts for hosts in classes.values()), (
            f"{host} must not be silently classified")


def test_the_drift_check_detects_a_single_changed_byte(gate, tmp_path):
    artifact = tmp_path / "artifact"
    entry = artifact / "site-packages" / "hermes_cli"
    entry.mkdir(parents=True)
    (entry / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (artifact / ".agentbox-hermes-runtime-artifact").write_text("x", encoding="utf-8")
    outcome = gate.drift_check(artifact, tmp_path)
    assert outcome["detected"] is True
    assert outcome["originalDigest"] != outcome["changedDigest"]
    # The artifact under test is untouched and the copy is gone.
    assert (entry / "main.py").read_text(encoding="utf-8").startswith("def main")


# -- cleanup -----------------------------------------------------------------

def test_cleanup_refuses_a_directory_this_run_did_not_create(gate, tmp_path, monkeypatch):
    monkeypatch.setattr(gate.tempfile, "gettempdir", lambda: str(tmp_path))
    created = tmp_path / f"{gate.TEMPORARY_PREFIX}created"
    created.mkdir()
    os.chmod(created, 0o700)
    other = tmp_path / f"{gate.TEMPORARY_PREFIX}other"
    other.mkdir()
    os.chmod(other, 0o700)
    with pytest.raises(gate.GateFailure) as refused:
        gate.cleanup_root(other, created=created)
    assert refused.value.code == "HERMES_GATE_CLEANUP_NOT_OWNED"
    assert other.exists()
    outcome = gate.cleanup_root(created, created=created)
    assert outcome["removed"] is True


def test_cleanup_fails_loudly_when_a_tree_cannot_be_removed(gate, tmp_path, monkeypatch):
    monkeypatch.setattr(gate.tempfile, "gettempdir", lambda: str(tmp_path))
    created = tmp_path / f"{gate.TEMPORARY_PREFIX}stuck"
    (created / "nested").mkdir(parents=True)
    os.chmod(created, 0o700)
    (created / "nested" / "file").write_text("x", encoding="utf-8")

    def explode(_path, *_args, **_kwargs):
        raise OSError("injected removal failure")

    monkeypatch.setattr(gate.shutil, "rmtree", explode)
    with pytest.raises(gate.GateFailure) as failed:
        gate.remove_tree(created)
    assert failed.value.code == "HERMES_GATE_CLEANUP_FAILED"
    assert created.exists()
    monkeypatch.undo()
    shutil.rmtree(created)


# -- the deployment layer the gate hands to the Server -----------------------

def deployment_file(tmp_path: Path, harness: dict) -> Path:
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps({
        "schemaVersion": 1, "harnesses": [harness],
    }), encoding="utf-8")
    return path


def test_the_production_document_is_accepted_by_the_server(tmp_path, monkeypatch):
    import ordessa_server.bootstrap.runtime as runtime_module

    # A connector is only needed to actually dispatch; this test is about the
    # deployment document being accepted and registered without a Harness branch.
    monkeypatch.setattr(runtime_module, "_builtin_connector", lambda _id: object())
    document = production.deployment_document(
        artifact_token="hermes-runtime",
        tree_digest="sha256:" + "b" * 64,
    )
    path = deployment_file(tmp_path, document["harnesses"][0])
    runtime = build_runtime_from_sidecar_deployment(
        tmp_path / "server", path, secret_store=None, plugin_root=production.PLUGIN_ROOT,
        # The document names the token; where the tree lives is this binding.
        mount_bindings={"hermes-runtime": "/srv/agentbox/artifacts/hermes-runtime"},
    )
    try:
        # No Hermes branch anywhere: the registered descriptor is the generic one.
        descriptor = runtime.plugin_host.provided_port('harness.directory').get("hermes")
        assert descriptor.credential_kind == "api-key"
        assert descriptor.credential_environment == "DEEPSEEK_API_KEY"
        assert descriptor.model_control_id is None
    finally:
        runtime.stop()


def test_a_credential_shaped_environment_key_is_refused_by_the_deployment_layer(tmp_path, monkeypatch):
    import ordessa_server.bootstrap.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_builtin_connector", lambda _id: object())
    """The measured reason the output ceiling is not an adapter environment key."""
    harness = production.deployment_document(
        artifact_token="hermes-runtime",
        tree_digest="sha256:" + "b" * 64,
    )["harnesses"][0]
    harness["adapter"]["environment"] = {
        **harness["adapter"]["environment"], "HERMES_MAX_TOKENS": "64",
    }
    path = deployment_file(tmp_path, harness)
    with pytest.raises(RuntimeError) as refused:
        build_runtime_from_sidecar_deployment(
            tmp_path / "server", path, secret_store=None, plugin_root=production.PLUGIN_ROOT)
    assert "SIDECAR_DEPLOYMENT_INVALID" in str(refused.value)
    assert "HERMES_MAX_TOKENS" not in production.ADAPTER_ENVIRONMENT


def test_a_runtime_artifact_mount_without_a_digest_is_refused(tmp_path, monkeypatch):
    import ordessa_server.bootstrap.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_builtin_connector", lambda _id: object())
    harness = production.deployment_document(
        artifact_token="hermes-runtime",
        tree_digest="sha256:" + "b" * 64,
    )["harnesses"][0]
    harness["runtimeArtifactMounts"] = [{
        "token": "hermes-runtime",
        "target": production.ARTIFACT_TARGET, "treeDigest": "sha256:short",
    }]
    with pytest.raises(RuntimeError) as refused:
        build_runtime_from_sidecar_deployment(
            tmp_path / "server", deployment_file(tmp_path, harness), secret_store=None,
            plugin_root=production.PLUGIN_ROOT,
            mount_bindings={"hermes-runtime": "/srv/agentbox/artifacts/hermes-runtime"})
    assert str(refused.value).startswith(
        ("SIDECAR_DEPLOYMENT_INVALID", "SIDECAR_DEPLOYMENT_HOST_PATH"))


def test_a_user_directory_cannot_be_declared_as_the_runtime_artifact(tmp_path, monkeypatch):
    import ordessa_server.bootstrap.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_builtin_connector", lambda _id: object())
    """The artifact is a built, digest-verified tree, never a raw install root."""
    harness = production.deployment_document(
        artifact_token="hermes-runtime",
        tree_digest="sha256:" + "b" * 64,
    )["harnesses"][0]
    harness["runtimeArtifactMounts"][0]["target"] = "/runtime/artifacts/../site-packages"
    with pytest.raises(RuntimeError) as refused:
        build_runtime_from_sidecar_deployment(
            tmp_path / "server", deployment_file(tmp_path, harness), secret_store=None,
            plugin_root=production.PLUGIN_ROOT,
            mount_bindings={"hermes-runtime": "/srv/agentbox/artifacts/hermes-runtime"})
    assert str(refused.value).startswith(
        ("SIDECAR_DEPLOYMENT_INVALID", "SIDECAR_DEPLOYMENT_HOST_PATH"))
    for item in production.deployment_document(
        artifact_token="hermes-runtime",
        tree_digest="sha256:" + "b" * 64,
    )["harnesses"][0]["runtimeArtifactMounts"]:
        assert item["target"].startswith("/runtime/artifacts/")


def test_the_gate_script_never_writes_into_the_repository():
    """A gate run publishes its artifact and reports outside the worktree."""
    text = GATE_PATH.read_text(encoding="utf-8")
    assert "mkdtemp(prefix=TEMPORARY_PREFIX)" in text
    assert "assert_owned_root" in text
    assert "REPO / \"artifact\"" not in text
    builder = (REPO / "scripts" / "server-round1" / "build-hermes-runtime-artifact.mjs").read_text(
        encoding="utf-8")
    assert "HERMES_OUTPUT_INSIDE_REPOSITORY" in builder
    assert "HERMES_OUTPUT_RESERVED" in builder


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
