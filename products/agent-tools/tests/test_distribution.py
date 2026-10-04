"""Source boundary plus wheel execution in an isolated Python environment."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from test_discovery import SECRET, config
from test_profile_cli import profile_server

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


def test_wheel_isolated_install_and_actual_http_discovery(tmp_path):
    wheel_dir = tmp_path / "wheels"
    build = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", str(wheel_dir), str(ROOT)], capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = list(wheel_dir.glob("ordessa_agent_tools-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        assert "ordessa_agent_tools/schema.json" in archive.namelist()
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
    absence = subprocess.run([str(python), "-I", "-c", "import importlib.util; assert all(importlib.util.find_spec(n) is None for n in ('pacthold','ordessa_server','ordessa_harness','ordessa_agent'))"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert absence.returncode == 0, absence.stderr
    executable = environment / "bin/ordessa-agent"
    help_result = subprocess.run([str(executable), "--help"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert help_result.returncode == 0 and "profiles" in help_result.stdout
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
