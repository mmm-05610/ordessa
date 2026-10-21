"""Acceptance tests for the in-process ``ordessa environments`` CLI.

Every test runs the real CLI as a child process (``python -m
ordessa_cli``) with the current interpreter and PYTHONPATH, against a
``tmp_path`` state directory and the real Local provider. There are no
mocks: real subprocesses, a real SQLite registry and real local files.

The boundary test scans every interface module: concrete owner imports belong
to application composition.

OpenShell is tested honestly: the provider is ``UNAVAILABLE`` because this
design has no standalone authenticated-client bootstrap. No auth, fallback or
retry is invented.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parents[3]
SRC = FIX / "packages/interfaces/src"
PYTHON = os.environ.get("ORDESSA_TEST_PYTHON") or sys.executable

#: Explicit source paths in this checkout; never another worktree interpreter.
PYTHONPATH_PARTS = [
    SRC,
    FIX / "apps/cli/src",
    FIX / "packages/interfaces/contracts/src",
    FIX / "packages/interfaces/system-access/src",
    FIX / "packages/interfaces/channels/src",
    FIX / "packages/interfaces/channels/cli/src",
    FIX / "packages/interfaces/transport/server/src",
    FIX / "packages/execution/agents/src",
    FIX / "packages/execution/environments/src",
    FIX / "packages/execution/decision/src",
    FIX / "packages/infrastructure/src",
    FIX / "plugins/environments/local/src",
    FIX / "plugins/decision/rules-cel/src",
]

FORBIDDEN_OWNER_IMPORTS = (
    "ordessa_environments",
    "ordessa_environments_local",
    "ordessa_engineering",
    "ordessa_agents",
)



def _child_env():
    env = dict(os.environ)
    if env.get("ORDESSA_TEST_INSTALLED") == "1":
        # Installed acceptance: the merged wheel layout is the source of truth.
        env.pop("PYTHONPATH", None)
    else:
        parts = [str(path) for path in PYTHONPATH_PARTS]
        if env.get("PYTHONPATH"):
            parts.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("ORDESSA_STATE", None)  # tests pass --state explicitly
    return env


def run_cli(state, *args, stdin=None, expect=None, env_overrides=None):
    env = _child_env()
    if env_overrides:
        env.update(env_overrides)
    command = [PYTHON, "-m", "ordessa_cli"]
    if state is not None:
        command += ["--state", str(state)]
    command += list(args)
    result = subprocess.run(
        command,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
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
    text = result.stdout.decode("utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 1, (
        f"expected one JSON line, got {len(lines)}: {lines!r}; "
        f"exit={result.returncode}; stderr={result.stderr!r}")
    parsed = json.loads(text)
    assert parsed["apiVersion"] == "agent-tools/1"
    assert set(parsed) == {"apiVersion", "requestId", "command", "status", "data", "error", "operationRef", "evidenceRefs"}
    return parsed


def human_json(result):
    """Normal mode prefixes the copyable request id; the rest is the payload."""
    lines = result.stdout.decode("utf-8").splitlines()
    if lines and lines[0].startswith("requestId: "):
        lines = lines[1:]
    return json.loads("\n".join(lines))


def create_local(state, alias="demo", root_name="root"):
    run_cli(
        state, "environments", "create", "local", "--root", str(Path(state) / root_name),
        "--alias", alias, expect=0,
    )
    listed = envelope(run_cli(state, "environments", "list", "--json", expect=0))
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


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module)
    return modules


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


# ---------------------------------------------------------------------------
# providers / list / create
# ---------------------------------------------------------------------------
def test_providers_reports_local_and_openshell_unavailable(state):
    result = run_cli(state, "environments", "providers", "--json", expect=0)
    data = envelope(result)["data"]
    by_id = {item["id"]: item for item in data["providers"]}
    assert by_id["local"]["available"] is True
    assert by_id["local"]["isolation"] == "none"
    assert {"process", "files", "byte-channel", "stderr"} <= set(by_id["local"]["capabilities"])
    assert by_id["local"]["endpointKind"] == "local-directory"
    assert by_id["openshell"]["available"] is False
    assert by_id["openshell"]["status"] == "UNAVAILABLE"
    assert by_id["openshell"]["reason"]

    human = run_cli(state, "environments", "providers", expect=0)
    assert human_json(human)["providers"][0]["isolation"] == "none"
    assert human_json(human)["providers"][1]["status"] == "UNAVAILABLE"


def test_create_local_and_list_contains_alias(state):
    identity = create_local(state)
    assert identity.startswith("environment/")
    assert (Path(state) / "root").is_dir()
    assert (Path(state) / "environments.sqlite").exists()

    listed = envelope(run_cli(state, "environments", "list", "--json", expect=0))["data"]
    assert listed["orphanAliases"] == []
    entry = listed["resources"][0]
    assert entry["identity"] == identity
    assert entry["aliases"] == ["demo"]
    assert entry["provider"] == "local"
    assert entry["state"] == "running"
    assert entry["phase"] == "ready"
    assert entry["generation"] == 0
    assert entry["activeUses"] == 0
    assert entry["isolation"] == "none"
    assert entry["endpointKind"] == "local-directory"
    assert entry["health"] == "ready"
    assert {"byte-channel", "files", "process", "stderr"} <= set(entry["capabilities"]["provides"])

    human = run_cli(state, "environments", "list", expect=0)
    assert identity.encode() in human.stdout
    assert human_json(human)["resources"][0]["aliases"] == ["demo"]


def test_register_local_existing_directory_and_conflict(state):
    Path(state).mkdir(mode=0o700, parents=True)
    backend = Path(state) / "registered"
    backend.mkdir()
    result = run_cli(
        state, "environments", "register", "local", str(backend), "--alias", "reg", expect=0
    )
    assert human_json(result)["identity"].startswith("environment/")
    listed = envelope(run_cli(state, "environments", "list", "--json", expect=0))["data"]
    assert listed["resources"][0]["aliases"] == ["reg"]
    assert listed["resources"][0]["backendId"] == str(backend)

    conflict = run_cli(
        state, "environments", "register", "local", str(backend), "--alias", "other", expect=5
    )
    assert b"already exists" in conflict.stderr


# ---------------------------------------------------------------------------
# exec
# ---------------------------------------------------------------------------
def test_exec_echo_exits_zero_and_streams_stdout(state):
    create_local(state)
    result = run_cli(state, "environments", "exec", "demo", "--", "/bin/echo", "hi", expect=0)
    assert result.stdout == b"hi\n"


def test_exec_false_propagates_child_exit_code(state):
    create_local(state)
    result = run_cli(state, "environments", "exec", "demo", "--", "/bin/false", expect=1)
    assert result.stdout == b""


def test_exec_streams_stdout_and_stderr(state):
    create_local(state)
    result = run_cli(
        state, "environments", "exec", "demo", "--", "/bin/sh", "-c",
        "echo out; echo err >&2", expect=0,
    )
    assert b"out" in result.stdout
    assert b"err" in result.stderr


def test_exec_stdin_pipe_is_forwarded(state):
    create_local(state)
    result = run_cli(
        state, "environments", "exec", "demo", "--", "/bin/cat", stdin=b"x\n", expect=0
    )
    assert result.stdout == b"x\n"


def test_exec_json_is_one_envelope_and_still_propagates_exit_code(state):
    create_local(state)
    result = run_cli(
        state, "environments", "exec", "demo", "--json", "--", "/bin/echo", "j", expect=0
    )
    parsed = envelope(result)
    assert parsed["command"].startswith("environments exec ")
    assert parsed["status"] == "completed"
    assert parsed["error"] is None
    assert parsed["data"]["exitCode"] == 0
    assert parsed["data"]["stdout"] == "j\n"
    assert parsed["data"]["useReleased"] is True
    assert parsed["data"]["truncated"] == {"stdout": False, "stderr": False}

    failed = run_cli(
        state, "environments", "exec", "demo", "--json", "--", "/bin/false", expect=1
    )
    parsed_failed = envelope(failed)
    assert parsed_failed["status"] == "completed"
    assert parsed_failed["error"] is None
    assert parsed_failed["data"]["exitCode"] == 1

    listed = envelope(run_cli(state, "environments", "list", "--json", expect=0))["data"]
    assert listed["resources"][0]["activeUses"] == 0


def test_exec_timeout_exits_seven_and_leaks_no_process(state):
    create_local(state)
    sentinel = "987654321"
    result = run_cli(
        state, "environments", "exec", "demo", "--timeout", "1", "--", "/bin/sleep", sentinel,
        expect=7,
    )
    assert b"timed out" in result.stderr
    time.sleep(1)
    leaked = processes_matching(sentinel)
    assert leaked == [], f"leaked processes: {leaked}"
    listed = envelope(run_cli(state, "environments", "list", "--json", expect=0))["data"]
    assert listed["resources"][0]["activeUses"] == 0


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------
def test_inspect_json_shape(state):
    create_local(state)
    parsed = envelope(run_cli(state, "environments", "inspect", "demo", "--json", expect=0))
    assert parsed["command"] == "environments inspect demo"
    assert parsed["status"] == "completed"
    data = parsed["data"]
    for field in (
        "identity", "alias", "aliases", "provider", "backendId", "phase", "generation",
        "state", "isolation", "capabilities", "endpointKind", "health", "activeUses",
        "operationStatus",
    ):
        assert field in data, field
    assert data["alias"] == "demo"
    assert data["aliases"] == ["demo"]
    assert data["isolation"] == "none"
    capabilities = data["capabilities"]
    assert capabilities["isolation"] == "none"
    assert capabilities["provides"]
    assert isinstance(capabilities["statuses"], dict)
    assert capabilities["statuses"]["process"] in ("supported", "conditional")
    assurance = capabilities["assurance"]
    assert assurance["isolationIsSecurityBoundary"] is False
    assert assurance["localDevelopmentOnly"] is True
    assert assurance["statement"]
    assert isinstance(capabilities["values"], dict)
    assert isinstance(data["activeUses"], int)
    assert data["operationStatus"]["phase"] == "ready"
    assert data["operationStatus"]["operation"] is None

    human = run_cli(state, "environments", "inspect", "demo", expect=0)
    assert human_json(human)["identity"] == data["identity"]
    assert human_json(human)["isolation"] == "none"


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------
def test_state_persists_across_processes(state):
    identity = create_local(state, alias="keep", root_name="persist")
    # Every run_cli call is a fresh OS process.
    listed = envelope(run_cli(state, "environments", "list", "--json", expect=0))["data"]
    assert [item["identity"] for item in listed["resources"]] == [identity]
    assert listed["resources"][0]["aliases"] == ["keep"]

    inspected = envelope(
        run_cli(state, "environments", "inspect", identity, "--json", expect=0)
    )["data"]
    assert inspected["identity"] == identity
    assert inspected["backendId"] == str(Path(state) / "persist")

    # ORDESSA_STATE is the environment-variable form of --state.
    from_env = envelope(
        run_cli(
            None, "environments", "list", "--json", expect=0,
            env_overrides={"ORDESSA_STATE": str(state)},
        )
    )["data"]
    assert [item["identity"] for item in from_env["resources"]] == [identity]


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------
def test_files_write_ls_cat_roundtrip(state):
    create_local(state)
    written = envelope(
        run_cli(state, "environments", "files", "demo", "write", "keep.txt", "user-data",
                "--json", expect=0)
    )["data"]
    assert written["operation"] == "write"
    assert written["path"] == "keep.txt"
    assert written["bytes"] == len("user-data")

    entries = envelope(
        run_cli(state, "environments", "files", "demo", "ls", "--json", expect=0)
    )["data"]["entries"]
    assert "keep.txt" in entries

    content = envelope(
        run_cli(state, "environments", "files", "demo", "cat", "keep.txt", "--json", expect=0)
    )["data"]["content"]
    assert content == "user-data"

    # Human mode must actually render the operation result (the label carries
    # the files sub-operation, not the environment reference).
    human_ls = run_cli(state, "environments", "files", "demo", "ls", expect=0)
    assert b"keep.txt" in human_ls.stdout
    human_cat = run_cli(state, "environments", "files", "demo", "cat", "keep.txt", expect=0)
    assert human_json(human_cat)["content"] == "user-data"


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------
def test_invalid_reference_refuses_exit_two(state):
    create_local(state)
    plain = run_cli(state, "environments", "inspect", "nope", expect=2)
    assert b"ordessa:" in plain.stderr

    parsed = envelope(run_cli(state, "environments", "inspect", "nope", "--json", expect=2))
    assert parsed["status"] == "refused"
    assert parsed["error"]["code"] == "INVALID_INPUT"
    assert parsed["error"]["retryable"] is False


def test_no_command_refuses_before_effect(state):
    create_local(state)
    for args in (
        ("environments", "exec", "demo"),
        ("environments", "exec", "demo", "--"),
    ):
        result = run_cli(state, *args, expect=2)
        assert b"argument needs at least one value" in result.stderr
    parsed = envelope(
        run_cli(state, "environments", "exec", "demo", "--json", expect=2)
    )
    assert parsed["status"] == "refused"
    assert parsed["error"]["code"] == "INVALID_INPUT"
    listed = envelope(run_cli(state, "environments", "list", "--json", expect=0))["data"]
    assert listed["resources"][0]["activeUses"] == 0


def test_relative_root_alias_conflict_and_missing_state_refuse(state):
    create_local(state)
    relative = run_cli(
        state, "environments", "create", "local", "--root", "relative/path", expect=2
    )
    assert b"invalid" in relative.stderr.lower()

    conflict = run_cli(
        state, "environments", "create", "local", "--root", str(Path(state) / "root"),
        "--alias", "demo", expect=5,
    )
    assert b"already exists" in conflict.stderr

    missing = run_cli(None, "environments", "list", expect=2)
    assert b"--state DIR or --config FILE --service NAME is required" in missing.stderr

    unknown = run_cli(state, "environments", "bogus", expect=4)
    assert b"unknown command" in unknown.stderr

    bad_option = run_cli(state, "environments", "list", "--nope", expect=2)
    assert b"unexpected arguments" in bad_option.stderr


def test_foreign_registry_database_refuses_exit_two(state):
    import sqlite3

    Path(state).mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(Path(state) / "environments.sqlite")
    connection.execute("CREATE TABLE foreign_table (value INTEGER)")
    connection.commit()
    connection.close()

    parsed = envelope(run_cli(state, "environments", "list", "--json", expect=2))
    assert parsed["status"] == "refused"
    assert parsed["error"]["code"] == "INVALID_INPUT"
    assert parsed["error"]["retryable"] is False


def test_openshell_create_and_exec_are_unavailable_exit_four(state):
    created = run_cli(
        state, "environments", "create", "openshell", "--root", str(Path(state) / "o"), expect=4
    )
    assert b"unavailable" in created.stderr.lower()

    executed = run_cli(state, "environments", "exec", "openshell", "--", "/bin/echo", "x", expect=4)
    assert b"unavailable" in executed.stderr.lower()

    parsed = envelope(
        run_cli(state, "environments", "exec", "openshell", "--json", "--", "/bin/echo", "x",
                expect=4)
    )
    assert parsed["status"] == "refused"
    assert parsed["error"]["code"] == "CAPABILITY_UNSUPPORTED"

    listed = envelope(run_cli(state, "environments", "list", "--json", expect=0))["data"]
    assert listed["resources"] == []


def test_stop_and_delete_refuse_and_preserve_user_files(state):
    create_local(state)
    run_cli(state, "environments", "files", "demo", "write", "keep.txt", "user-data", expect=0)

    stop = run_cli(state, "environments", "stop", "demo", expect=2)
    assert b"lifecycle refused" in stop.stderr and b"preserved" in stop.stderr

    delete = run_cli(state, "environments", "delete", "demo", "--json", expect=2)
    parsed = envelope(delete)
    assert parsed["status"] == "refused"
    assert parsed["error"]["code"] == "INVALID_INPUT"
    assert parsed["error"]["retryable"] is False
    assert (Path(state) / "root" / "keep.txt").read_text(encoding="utf-8") == "user-data"


def test_no_secrets_in_envelopes_or_alias_store(state):
    create_local(state)
    sentinel = "ordessa-sentinel-secret-value"
    env_backup = os.environ.get("ORDESSA_SENTINEL")
    os.environ["ORDESSA_SENTINEL"] = sentinel
    try:
        outputs = [
            run_cli(state, "environments", "providers", "--json", expect=0).stdout,
            run_cli(state, "environments", "inspect", "demo", "--json", expect=0).stdout,
            run_cli(state, "environments", "list", "--json", expect=0).stdout,
        ]
    finally:
        if env_backup is None:
            os.environ.pop("ORDESSA_SENTINEL", None)
        else:
            os.environ["ORDESSA_SENTINEL"] = env_backup
    for output in outputs:
        assert sentinel.encode() not in output

    alias_text = (Path(state) / "aliases.json").read_text(encoding="utf-8")
    assert sentinel not in alias_text
    parsed = json.loads(alias_text)
    assert set(parsed) == {"apiVersion", "aliases"}
    for name, identity in parsed["aliases"].items():
        assert name == "demo" and identity.startswith("environment/")


# ---------------------------------------------------------------------------
# boundary: assembly is the only owner-implementation importer
# ---------------------------------------------------------------------------
def test_channels_operations_queries_do_not_import_owner_implementations():
    for path in SRC.rglob("*.py"):
        for module in imported_modules(path):
            assert not any(module == f or module.startswith(f + ".") for f in FORBIDDEN_OWNER_IMPORTS), path


def test_application_assembly_is_the_owner_importer():
    assembly = FIX / "apps/cli/src/ordessa_cli/composition/environments.py"
    modules = imported_modules(assembly)
    assert "ordessa_environments" in modules
    assert "ordessa_environments_local" in modules
    assert not (SRC / "ordessa_interfaces/system_access/assembly/environments.py").exists()


def test_capability_adapter_only_needs_the_managed_report(tmp_path):
    """The single Phase A1 seam maps the managed ``CapabilityReport`` only."""
    from ordessa_environments import (
        PROCESS_CAPABILITY,
        TERMINAL_CAPABILITY,
        CapabilityReport,
        CapabilityStatus,
    )

    class _LegacyCapabilities:
        isolation = "none"
        provides = frozenset({"process", "files"})
        detail = {"root": "/tmp/example"}

    class _Observation:
        def __init__(self, capabilities):
            self.capabilities = capabilities

    # Projection moved to the owner; the host receives only declared JSON.
    from ordessa_environments.capability import EnvironmentCapabilityService
    from types import SimpleNamespace
    service = EnvironmentCapabilityService.__new__(EnvironmentCapabilityService)
    service._aliases = lambda: {}
    def project(capabilities):
        observation = SimpleNamespace(capabilities=capabilities, state="running", observed_at=None, endpoint_kind="local", health="ready")
        snapshot = SimpleNamespace(observation=observation, identity="environment/test", provider_id="local", backend_id="/tmp/example", phase="ready", generation=0, active_uses=0, operation=None)
        return service._project(snapshot)["capabilities"]
    report = CapabilityReport(
        values={
            PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED,
            TERMINAL_CAPABILITY: CapabilityStatus.UNSUPPORTED,
        },
        isolation="none",
        assurance="provider_self_report",
        details={"resourceKind": "directory"},
    )
    managed = project(report)
    assert managed["isolation"] == "none"
    assert managed["provides"] == ["process"]
    assert managed["statuses"] == {"process": "supported", "terminal": "unsupported"}
    assert managed["values"] == {"resourceKind": "directory"}
    assert managed["assurance"]["providerAssurance"] == "provider_self_report"
    assert managed["assurance"]["isolationIsSecurityBoundary"] is False

    # The retired legacy Capabilities shape (provides/detail) is not tolerated:
    # the adapter reads the managed report fields directly, so it fails closed.
    with pytest.raises(AttributeError):
        project(_LegacyCapabilities())


def test_console_script_entry_point_is_declared_once():
    cli = tomllib.loads((FIX / "apps/cli/pyproject.toml").read_text(encoding="utf-8"))
    assert cli["project"]["scripts"]["ordessa"] == "ordessa_cli.cli:main"
    server = tomllib.loads((FIX / "apps/server/pyproject.toml").read_text(encoding="utf-8"))
    assert "ordessa" not in server["project"].get("scripts", {})
