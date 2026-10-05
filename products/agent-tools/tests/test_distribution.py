"""Source boundary plus wheel execution in an isolated Python environment."""
import ast
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import zipfile

from test_discovery import SECRET, config
from test_profile_cli import profile_server
from test_provider_cli import provider_server
from test_configuration_cli import setup as node_setup, node_fixture, explicit_capabilities, observation_server

ROOT = Path(__file__).resolve().parents[1]


def imports_are_client_only(source):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [value.name.split(".")[0] for value in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        if any(name not in sys.stdlib_module_names and name != "ordessa_agent_tools" for name in names):
            return False
    return True


def test_client_import_boundary_with_adversarial_imports():
    for source in (ROOT / "src").rglob("*.py"):
        assert imports_are_client_only(source.read_text()), source
    for source in ("import pacthold", "from ordessa_server.bootstrap import runtime", "import ordessa_harness", "from ordessa_agent import submission_service"):
        assert not imports_are_client_only(source)


def test_wheel_isolated_install_and_actual_http_discovery(tmp_path, node_setup):
    wheel_dir = tmp_path / "wheels"
    # Build fresh source in a temporary tree: old ignored build/lib files must
    # not silently enter the wheel after package exclusions change.
    source = tmp_path / "wheel-source"
    source.mkdir()
    shutil.copy2(ROOT / "pyproject.toml", source / "pyproject.toml")
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
    build = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", str(wheel_dir), str(source)], capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = list(wheel_dir.glob("ordessa_agent_tools-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        assert "ordessa_agent_tools/schema.json" in archive.namelist()
        assert "ordessa_agent_tools/schema-management.json" in archive.namelist()
        assert not any(name.startswith("ordessa_agent_tools/native_clients/") for name in archive.namelist())
        commands = json.loads(archive.read("ordessa_agent_tools/harness_commands.json"))["catalog"]["candidates"]
        assert all(not name.startswith(("pacthold/", "ordessa_server/", "ordessa_harness/", "ordessa_agent/")) for name in archive.namelist())
    environment = tmp_path / "isolated"
    created = subprocess.run([sys.executable, "-m", "venv", str(environment)], capture_output=True, text=True)
    assert created.returncode == 0, created.stderr
    python = environment / "bin/python"
    install = subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheels[0])], capture_output=True, text=True)
    assert install.returncode == 0, install.stderr
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    env["TOOLS_TEST_TOKEN"] = SECRET
    absence = subprocess.run([str(python), "-I", "-c", "import importlib.util; assert all(importlib.util.find_spec(n) is None for n in ('pacthold','ordessa_server','ordessa_harness','ordessa_agent','ordessa_agent_tools.native_clients'))"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert absence.returncode == 0, absence.stderr
    executable = environment / "bin/ordessa-agent"
    help_result = subprocess.run([str(executable), "--help"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert help_result.returncode == 0 and "profiles" in help_result.stdout and "providers" in help_result.stdout and "nodes" in help_result.stdout
    node_help = subprocess.run([str(executable), "nodes", "configuration", "describe", "--help"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert node_help.returncode == 0 and "node_ref" in node_help.stdout
    binary_directory = tmp_path / "local-binaries"
    binary_directory.mkdir()
    marker = tmp_path / "must-not-run"
    candidate = binary_directory / commands[0]["commands"][0]
    candidate.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
    candidate.chmod(0o700)
    initialized = subprocess.run([str(executable), "init", "--path", str(binary_directory), "--json"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    observed = json.loads(initialized.stdout)
    assert observed["data"]["foundFamilies"] == [commands[0]["familyId"]]
    assert observed["evidence"]["runtimeVerified"] is False
    assert not marker.exists()
    with profile_server() as (endpoint, calls):
        path = config(tmp_path, endpoint)
        checked = subprocess.run([str(executable), "doctor", "--config", str(path), "--service", "local", "--json"], cwd=tmp_path, env=env, capture_output=True, text=True)
        assert checked.returncode == 0, checked.stdout + checked.stderr
        result = json.loads(checked.stdout)
        assert result["data"]["coreAgent"]["supports"]["managedInput"] is False
        assert len(calls) == 2
        assert SECRET not in checked.stdout + checked.stderr

    with provider_server() as (endpoint, calls, definition):
        path = config(tmp_path, endpoint)
        checked = subprocess.run([str(executable), "providers", "list", "--config", str(path), "--service", "local", "--json"], cwd=tmp_path, env=env, capture_output=True, text=True)
        assert checked.returncode == 0, checked.stdout + checked.stderr
        result = json.loads(checked.stdout)
        assert result["data"]["providers"][0]["descriptor"]["definitionRef"] == dict(definition)
        assert result["evidence"] == {"level": "providerRegistryObserved", "runtimeVerified": False}
        assert len(calls) == 3 and SECRET not in checked.stdout + checked.stderr

        reference = tmp_path / "definition-ref.json"
        reference.write_text(json.dumps(dict(definition)))
        described = subprocess.run([str(executable), "providers", "describe", "@" + str(reference), "--config", str(path), "--service", "local", "--json"], cwd=tmp_path, env=env, capture_output=True, text=True)
        assert described.returncode == 0, described.stdout + described.stderr
        assert json.loads(described.stdout)["data"]["descriptor"]["definitionRef"] == dict(definition)
        assert SECRET not in described.stdout + described.stderr and len(calls) == 6

    with observation_server(node_setup, managing=True) as (endpoint, calls):
        path = config(tmp_path, endpoint)
        reference = tmp_path / "node-ref.json"
        reference.write_text(json.dumps({"environmentNamespace": "env", "instanceId": "node", "generation": 1}))
        for action in ("describe", "inspect"):
            checked = subprocess.run([str(executable), "nodes", "configuration", action, "@" + str(reference),
                "--config", str(path), "--service", "local", "--json"], cwd=tmp_path, env=env, capture_output=True, text=True)
            assert checked.returncode == 0, checked.stdout + checked.stderr
            result = json.loads(checked.stdout)
            assert result["evidence"]["runtimeVerified"] is False
            assert result["evidence"]["configurationValuesObserved"] is (action == "inspect")
            if action == "inspect":
                assert result["data"]["configuration"] == {"model": "old"}
                assert result["data"]["sourceRevision"] == "native-1"
            else: assert result["data"]["descriptions"][0]["configurationKind"] == "model"
            assert SECRET not in checked.stdout + checked.stderr
        assert len(calls) == 6
        assert node_setup[7]["calls"] == 0 and node_setup[7]["queryCalls"] == 0

        change = tmp_path / "change.json"
        change.write_text(json.dumps(node_setup[6].to_dict()))
        applied = subprocess.run([str(executable), "nodes", "configuration", "apply", "@" + str(reference),
            "--file", str(change), "--config", str(path), "--service", "local", "--json"], cwd=tmp_path, env=env, capture_output=True, text=True)
        assert applied.returncode == 0, applied.stdout + applied.stderr
        result = json.loads(applied.stdout)
        assert result["requestId"] == node_setup[6].request_id and result["status"] == "confirmed"
        assert result["data"]["configurationResult"]["overallOutcome"] == "applied"
        assert result["evidence"]["allDeclarationsApplied"] is True
        queried = subprocess.run([str(executable), "nodes", "configuration", "query", "@" + str(reference), result["operationRef"],
            "--config", str(path), "--service", "local", "--json"], cwd=tmp_path, env=env, capture_output=True, text=True)
        assert queried.returncode == 0, queried.stdout + queried.stderr
        assert json.loads(queried.stdout)["data"] == result["data"]
        assert node_setup[7]["calls"] == 1 and node_setup[7]["queryCalls"] == 0
        assert len(calls) == 12 and SECRET not in applied.stdout + applied.stderr + queried.stdout + queried.stderr
