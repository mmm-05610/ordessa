"""The native verifier must survive non-editable installation and private Node PATHs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest


PLUGIN = Path(__file__).resolve().parents[5] / 'plugins' / 'harness'


@pytest.mark.parametrize("brand", ["pi", "codex", "claude-code"])
def test_verifier_uses_selected_node_and_keeps_complete_policy(monkeypatch, tmp_path, brand):
    from ordessa_server.composition.configuration.model import live_service

    selected = tmp_path / "node"
    selected.symlink_to(shutil.which("node"))
    monkeypatch.setenv("PATH", str(tmp_path))
    calls = []

    def observe(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=json.dumps({"digest": "sha256:" + "a" * 64}))

    import importlib
    verifier = importlib.import_module({"pi": "ordessa_harness_pi", "codex": "ordessa_harness_codex", "claude-code": "ordessa_harness_claude_code"}[brand] + ".configuration.service")
    monkeypatch.setattr(verifier.subprocess, "run", observe)
    installation = live_service.verified_installation(brand, "/trusted/artifacts")
    argv, options = calls[0]
    assert Path(argv[0]).resolve() == selected.resolve()
    assert argv[0] == str(selected), "The verifier must honor the product's Node PATH"
    assert Path(argv[4]).read_bytes() == (Path(__file__).resolve().parents[5] / 'packages/execution/agents/src/ordessa_agents/harness/providers/resolution/_deployment/native-artifact-policy.mjs').read_bytes()
    assert "verifyInstalledArtifact" in argv[3]
    assert "variant:'native-profile'" in argv[3] if brand != "pi" else "variant:'pi-profile'" in argv[3]
    assert options["check"] is True and options["timeout"] == 30
    assert installation.harness_id == brand


@pytest.mark.parametrize("brand", ["pi", "codex", "claude-code"])
def test_verification_failure_is_never_replaced_with_another_policy(monkeypatch, brand):
    from ordessa_server.composition.configuration.model import live_service

    def refuse(argv, **kwargs):
        raise subprocess.CalledProcessError(1, argv, stderr="installed artifact digest mismatch")

    import importlib
    verifier = importlib.import_module({"pi": "ordessa_harness_pi", "codex": "ordessa_harness_codex", "claude-code": "ordessa_harness_claude_code"}[brand] + ".configuration.service")
    monkeypatch.setattr(verifier.subprocess, "run", refuse)
    with pytest.raises(subprocess.CalledProcessError, match="non-zero exit"):
        live_service.verified_installation(brand, "/untrusted/artifacts")


def test_missing_node_does_not_fall_back_to_system_node(monkeypatch):
    from ordessa_agents.harness.providers.resolution.verifier_deployment import installed_verifier

    monkeypatch.setenv("PATH", "")
    with pytest.raises(RuntimeError, match="NATIVE_VERIFIER_NODE_MISSING"):
        with installed_verifier():
            pytest.fail("An absent deployment interpreter must refuse")


def test_missing_installed_policy_does_not_search_other_trees(monkeypatch, tmp_path):
    from ordessa_agents.harness.providers.resolution import verifier_deployment

    monkeypatch.setattr(verifier_deployment, "__file__", str(tmp_path / "site-packages/ordessa_agents/harness/providers/resolution/verifier_deployment.py"))
    monkeypatch.setattr(verifier_deployment.resources, "files", lambda name: tmp_path / "site-packages/ordessa_agents/harness/providers/resolution")
    with pytest.raises(RuntimeError, match="NATIVE_VERIFIER_POLICY_MISSING"):
        with verifier_deployment.installed_verifier():
            pytest.fail("An incomplete installation must refuse")


def test_wheel_contains_original_policy_without_source_tree(tmp_path):
    """The unique Agents distribution supplies the complete neutral verifier."""
    kernel = Path(__file__).resolve().parents[5] / "packages/execution/agents"
    project = tmp_path / "build-input"
    project.mkdir()
    shutil.copytree(kernel / "src", project / "src",
                    ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    shutil.copyfile(kernel / "pyproject.toml", project / "pyproject.toml")
    shutil.copyfile(kernel / "README.md", project / "README.md")
    wheels = tmp_path / "wheels"
    build_python = os.environ.get("ORDESSA_HARNESS_BUILD_PYTHON", sys.executable)
    result = subprocess.run([build_python, "-m", "pip", "wheel", "--no-deps",
        "--no-build-isolation", "--wheel-dir", str(wheels), str(project)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    installed = tmp_path / "installed"
    with zipfile.ZipFile(next(wheels.glob("*.whl"))) as wheel:
        wheel.extractall(installed)
    policy = installed / "ordessa_agents/harness/providers/resolution/_deployment/native-artifact-policy.mjs"
    assert policy.is_file(), "The non-editable distribution omits the complete verifier"
    assert policy.read_bytes() == (Path(__file__).resolve().parents[5] / 'packages/execution/agents/src/ordessa_agents/harness/providers/resolution/_deployment/native-artifact-policy.mjs').read_bytes()
    private_bin = tmp_path / "private-bin"
    private_bin.mkdir()
    selected_node = private_bin / "node"
    selected_node.symlink_to(shutil.which("node"))
    from ordessa_harness_pi.acp_artifact_declarations import artifact_declaration
    extension = artifact_declaration()["profileExtension"]
    extension_policy = {**extension, "mode": "profile", "variant": "pi-profile"}
    script = """import hashlib,json,sys,subprocess
sys.path.insert(0,sys.argv[1])
from ordessa_agents.harness.providers.resolution.verifier_deployment import installed_verifier
with installed_verifier() as (node,policy):
 probe=subprocess.run([node,'--input-type=module','-e',
  'import {pathToFileURL} from "node:url"; const {verifyInstalledArtifact}=await import(pathToFileURL(process.argv[1]).href); verifyInstalledArtifact({artifactBase:"/ordessa-missing-verifier-test-root",artifact:"pi-profile-runtime",packageName:"@automatalabs/pi-acp",version:"0.5.0",variant:"pi-profile",extensionPolicy:JSON.parse(process.argv[2])});',str(policy),sys.argv[2]],capture_output=True,text=True)
 print(json.dumps({'node':node,'policy':str(policy),'digest':hashlib.sha256(policy.read_bytes()).hexdigest(),'rejected':probe.returncode != 0,'diagnostic':probe.stderr}))
"""
    observed = subprocess.run([sys.executable, "-I", "-c", script, str(installed), json.dumps(extension_policy)],
        cwd=tmp_path, env={**os.environ, "PATH": str(private_bin)},
        capture_output=True, text=True, check=True)
    data = json.loads(observed.stdout)
    assert Path(data["policy"]).is_relative_to(installed)
    assert data["digest"] == hashlib.sha256(policy.read_bytes()).hexdigest()
    assert data["node"] == str(selected_node)
    assert data["rejected"] is True
    assert "verifyInstalledArtifact" in data["diagnostic"]
