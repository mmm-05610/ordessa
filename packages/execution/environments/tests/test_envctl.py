"""Acceptance tests for ``examples/envctl.py`` (real subprocesses, no mocks).

Every test runs the reference driver as a child process with the runbook
interpreter and PYTHONPATH, against a ``tmp_path`` state directory. This proves
the CLI contract (exit codes, one JSON envelope, refusal-before-effect) rather
than the package internals, which have their own tests.

OpenShell is tested honestly: the provider is expected to be ``UNAVAILABLE``
because this design has no standalone authenticated-client bootstrap. A test
that needs a real gateway prints its reason and is skipped; a skip is not a pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parents[4]
ENVCTL = FIX / "packages/execution/environments/examples/envctl.py"
PYTHON = os.environ.get("ENVCTL_TEST_PYTHON") or sys.executable

#: The runbook PYTHONPATH plus the Local provider plugin, which the CLI needs.
PYTHONPATH_PARTS = [
    FIX / "packages/execution/units/src",
    FIX / "packages/execution/agents/src",
    FIX / "packages/execution/environments/src",
    FIX / "packages/execution/decision/src",
    FIX / "packages/infrastructure/src",
    FIX / "packages/backend/pacthold/src",
    FIX / "plugins/environments/local/src",
]


def _child_env():
    env = dict(os.environ)
    parts = [str(path) for path in PYTHONPATH_PARTS]
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("ENVCTL_STATE", None)  # tests pass --state explicitly
    return env


def run_envctl(state, *args, stdin=None, expect=None):
    result = subprocess.run(
        [PYTHON, str(ENVCTL), "--state", str(state), *args],
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_child_env(),
        cwd=str(FIX),
    )
    if expect is not None:
        assert result.returncode == expect, (
            f"args={args!r} expected exit {expect}, got {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    return result


def envelope(result):
    """Parse a single pure JSON envelope from stdout."""
    lines = [line for line in result.stdout.decode("utf-8").splitlines() if line.strip()]
    assert len(lines) == 1, f"expected one JSON line, got {len(lines)}: {lines!r}"
    parsed = json.loads(result.stdout.decode("utf-8"))
    assert parsed["apiVersion"] == "agent-tools/1"
    assert set(parsed) == {"apiVersion", "requestId", "command", "status", "data", "error"}
    return parsed


def create_local(state, alias="demo", root_name="root"):
    result = run_envctl(
        state, "create", "local", "--root", str(Path(state) / root_name), "--alias", alias, expect=0
    )
    listed = envelope(run_envctl(state, "list", "--json", expect=0))
    matches = [item for item in listed["data"]["resources"] if alias in item["aliases"]]
    assert len(matches) == 1, listed
    return matches[0]["identity"]


def processes_matching(sentinel):
    """Real process census from /proc; no pgrep dependency."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if sentinel.encode() in cmdline:
            found.append((entry.name, cmdline.replace(b"\x00", b" ").decode("utf-8", "replace")))
    return found


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


# ---------------------------------------------------------------------------
# C1 providers
# ---------------------------------------------------------------------------

def test_providers_reports_local_probe_and_openshell_unavailable(state):
    result = run_envctl(state, "providers", "--json", expect=0)
    data = envelope(result)["data"]
    by_id = {item["id"]: item for item in data["providers"]}
    assert by_id["local"]["available"] is True
    assert by_id["local"]["isolation"] == "none"
    assert {"process", "files", "byte-channel", "stderr"} <= set(by_id["local"]["capabilities"])
    assert by_id["openshell"]["available"] is False
    assert by_id["openshell"]["status"] == "UNAVAILABLE"
    assert by_id["openshell"]["reason"]

    human = run_envctl(state, "providers", expect=0)
    assert b"local available isolation=none" in human.stdout
    assert b"openshell UNAVAILABLE" in human.stdout


# ---------------------------------------------------------------------------
# C2/C3 create and list
# ---------------------------------------------------------------------------

def test_create_local_and_list_contains_alias(state):
    identity = create_local(state)
    assert identity.startswith("environment/")
    assert (Path(state) / "root").is_dir()

    listed = envelope(run_envctl(state, "list", "--json", expect=0))["data"]
    assert listed["orphanAliases"] == []
    entry = listed["resources"][0]
    assert entry["identity"] == identity
    assert entry["aliases"] == ["demo"]
    assert entry["provider"] == "local"
    assert entry["state"] == "running"
    assert entry["phase"] == "ready"
    assert entry["activeUses"] == 0
    assert entry["capabilities"] == {
        "isolation": "none",
        "provides": ["byte-channel", "files", "process", "stderr"],
    }


# ---------------------------------------------------------------------------
# C4-C7 use
# ---------------------------------------------------------------------------

def test_use_echo_exits_zero_and_streams_stdout(state):
    create_local(state)
    result = run_envctl(state, "use", "demo", "--", "/bin/echo", "hi", expect=0)
    assert result.stdout == b"hi\n"


def test_use_false_propagates_child_exit_code(state):
    create_local(state)
    result = run_envctl(state, "use", "demo", "--", "/bin/false", expect=1)
    assert result.stdout == b""


def test_use_shell_streams_stdout_and_stderr(state):
    create_local(state)
    result = run_envctl(
        state, "use", "demo", "--", "/bin/sh", "-c", "echo out; echo err >&2", expect=0
    )
    assert b"out" in result.stdout
    assert b"err" in result.stderr


def test_use_stdin_pipe_is_forwarded(state):
    create_local(state)
    result = run_envctl(state, "use", "demo", "--", "/bin/cat", stdin=b"x\n", expect=0)
    assert result.stdout == b"x\n"


def test_use_json_reports_exit_code_without_mixing_stdout(state):
    create_local(state)
    result = run_envctl(state, "use", "demo", "--json", "--", "/bin/echo", "j", expect=0)
    data = envelope(result)["data"]
    assert data["exitCode"] == 0
    assert data["stdout"] == "j\n"
    assert data["useReleased"] is True
    assert data["truncated"] == {"stdout": False, "stderr": False}

    # JSON mode still propagates the child's real exit code.
    failed = run_envctl(state, "use", "demo", "--json", "--", "/bin/false", expect=1)
    assert envelope(failed)["data"]["exitCode"] == 1


# ---------------------------------------------------------------------------
# C8 persistence across processes
# ---------------------------------------------------------------------------

def test_state_persists_across_processes(state):
    identity = create_local(state, alias="keep", root_name="persist")
    # Every run_envctl call is a fresh OS process.
    listed = envelope(run_envctl(state, "list", "--json", expect=0))["data"]
    assert [item["identity"] for item in listed["resources"]] == [identity]
    assert listed["resources"][0]["aliases"] == ["keep"]

    inspected = envelope(run_envctl(state, "inspect", identity, "--json", expect=0))["data"]
    assert inspected["identity"] == identity
    assert inspected["backendId"] == str(Path(state) / "persist")


# ---------------------------------------------------------------------------
# C9 inspect / capabilities JSON
# ---------------------------------------------------------------------------

def test_inspect_json_carries_isolation_assurance_and_capabilities(state):
    create_local(state)
    data = envelope(run_envctl(state, "inspect", "demo", "--json", expect=0))["data"]
    capabilities = data["capabilities"]
    assert capabilities["isolation"] == "none"
    assert capabilities["provides"]
    assurance = capabilities["assurance"]
    assert assurance["isolationIsSecurityBoundary"] is False
    assert assurance["statement"]
    assert isinstance(capabilities["values"], dict)
    assert isinstance(data["activeUses"], int)

    recorded = envelope(run_envctl(state, "capabilities", "demo", "--json", expect=0))["data"]
    assert recorded["capabilities"] == capabilities


# ---------------------------------------------------------------------------
# C10 refusals
# ---------------------------------------------------------------------------

def test_invalid_reference_refuses_exit_two(state):
    create_local(state)
    plain = run_envctl(state, "inspect", "nope", expect=2)
    assert b"unknown alias or identity" in plain.stderr

    result = run_envctl(state, "inspect", "nope", "--json", expect=2)
    parsed = envelope(result)
    assert parsed["status"] == "refused"
    assert parsed["error"]["code"] == "ENVCTL_INVALID_REFERENCE"
    assert parsed["error"]["retryable"] is False


def test_relative_root_and_alias_conflict_refuse(state):
    create_local(state)
    relative = run_envctl(state, "create", "local", "--root", "relative/path", expect=2)
    assert b"absolute path" in relative.stderr

    conflict = run_envctl(
        state, "create", "local", "--root", str(Path(state) / "root"), "--alias", "demo", expect=5
    )
    assert b"already exists" in conflict.stderr


def test_openshell_create_is_unavailable_not_fallback(state):
    result = run_envctl(state, "create", "openshell", "--root", str(Path(state) / "o"), expect=4)
    assert b"SandboxClient" in result.stderr
    listed = envelope(run_envctl(state, "list", "--json", expect=0))["data"]
    assert listed["resources"] == []


def test_stop_and_delete_refuse_and_preserve_user_files(state):
    create_local(state)
    run_envctl(state, "files", "demo", "write", "keep.txt", "user-data", expect=0)
    stop = run_envctl(state, "stop", "demo", expect=2)
    assert b"refuses resource stop" in stop.stderr and b"preserved" in stop.stderr
    delete = run_envctl(state, "delete", "demo", "--json", expect=2)
    parsed = envelope(delete)
    assert parsed["status"] == "refused"
    assert parsed["error"]["code"] == "ENVCTL_LOCAL_LIFECYCLE_UNSUPPORTED"
    assert (Path(state) / "root" / "keep.txt").read_text(encoding="utf-8") == "user-data"


# ---------------------------------------------------------------------------
# C11 no-command refusal
# ---------------------------------------------------------------------------

def test_use_without_command_refuses_before_effect(state):
    create_local(state)
    for args in (("use", "demo"), ("use", "demo", "--")):
        result = run_envctl(state, *args, expect=2)
        assert b"terminal sessions are unavailable in v1; pass a command" in result.stderr
    listed = envelope(run_envctl(state, "list", "--json", expect=0))["data"]
    assert listed["resources"][0]["activeUses"] == 0


# ---------------------------------------------------------------------------
# C13 hygiene: timeout releases the use and leaks no process
# ---------------------------------------------------------------------------

def test_use_timeout_exits_seven_and_leaks_no_process(state):
    create_local(state)
    # A unique sleep duration doubles as the process sentinel in /proc.
    sentinel = "987654321"
    result = run_envctl(state, "use", "demo", "--timeout", "1", "--", "/bin/sleep", sentinel, expect=7)
    assert b"timed out" in result.stderr
    # The timeout path cancels and re-observes within a grace window; wait past it.
    time.sleep(1)
    leaked = processes_matching(sentinel)
    assert leaked == [], f"leaked processes: {leaked}"
    listed = envelope(run_envctl(state, "list", "--json", expect=0))["data"]
    assert listed["resources"][0]["activeUses"] == 0


def test_no_secrets_in_envelopes_or_alias_store(state):
    create_local(state)
    sentinel = "envctl-sentinel-secret-value"
    env_backup = os.environ.get("ENVCTL_SENTINEL")
    os.environ["ENVCTL_SENTINEL"] = sentinel
    try:
        outputs = [
            run_envctl(state, "providers", "--json", expect=0).stdout,
            run_envctl(state, "inspect", "demo", "--json", expect=0).stdout,
            run_envctl(state, "list", "--json", expect=0).stdout,
        ]
    finally:
        if env_backup is None:
            os.environ.pop("ENVCTL_SENTINEL", None)
        else:
            os.environ["ENVCTL_SENTINEL"] = env_backup
    for output in outputs:
        assert sentinel.encode() not in output
        lowered = output.decode("utf-8").lower()
        assert "sentinel" not in lowered

    alias_text = (Path(state) / "aliases.json").read_text(encoding="utf-8")
    assert sentinel not in alias_text
    parsed = json.loads(alias_text)
    assert set(parsed) == {"apiVersion", "aliases"}
    for name, identity in parsed["aliases"].items():
        assert name == "demo" and identity.startswith("environment/")


# ---------------------------------------------------------------------------
# C12 OpenShell: blocked without a gateway, honest skip otherwise
# ---------------------------------------------------------------------------

def test_openshell_blocked_without_gateway(state):
    data = envelope(run_envctl(state, "providers", "--json", expect=0))["data"]
    openshell = next(item for item in data["providers"] if item["id"] == "openshell")
    assert openshell["available"] is False
    assert openshell["status"] == "UNAVAILABLE"
    assert "authenticated" in openshell["reason"].lower()


def test_openshell_gateway_roundtrip(state):
    gateway = os.environ.get("ENVCTL_OPENSHELL_GATEWAY")
    if not gateway or not Path(gateway).exists():
        reason = (
            "openshell gateway absent: no standalone authenticated SandboxClient bootstrap "
            "exists in this design; set ENVCTL_OPENSHELL_GATEWAY to a real gateway binding "
            "to exercise a round trip"
        )
        print(f"SKIP REASON: {reason}")
        pytest.skip(reason)
    # A gateway binding is present, but envctl must still not invent auth or a
    # fallback: the reference driver refuses explicitly.
    result = run_envctl(state, "create", "openshell", "--root", str(Path(state) / "o"), expect=4)
    assert b"SandboxClient" in result.stderr
