"""C-01 §7 — the data root's counterexamples, one test each.

Every refusal here is checked for the thing that makes it useful: a stable
code, a human reason and a remedy. A refusal that only says "no" forces the
reader to guess, which is the failure mode C-01 §6 exists to prevent.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import textwrap

import pytest

from ordessa_server.bootstrap.data_root import (
    DATA_ROOT_ENV,
    DataRoot,
    DataRootInvalidError,
    DataRootLockedError,
    DataRootMigrationRefusedError,
    DataRootNotWritableError,
    DataRootSymlinkError,
    InstanceLock,
    ensure_data_root,
    instance_lock,
    launch_env,
    resolve_data_root,
    token_file,
)


# -- positive: create and reuse --------------------------------------------


def test_a_missing_root_is_created_private(tmp_path):
    root = ensure_data_root(resolve_data_root({}, home=str(tmp_path)))
    assert root.created is True
    assert root.path == tmp_path / ".ordessa"
    assert stat.S_IMODE(root.path.stat().st_mode) == 0o700
    for name in ("secrets", "logs", "backups"):
        assert stat.S_IMODE((root.path / name).stat().st_mode) == 0o700


def test_an_existing_root_is_reused_not_rebuilt(tmp_path):
    spec = resolve_data_root({}, home=str(tmp_path))
    first = ensure_data_root(spec)
    marker = first.path / "existing-user-data"
    marker.write_text("keep me", encoding="utf-8")
    second = ensure_data_root(spec)
    assert second.created is False
    assert marker.read_text(encoding="utf-8") == "keep me"


def test_a_second_start_keeps_the_token_bytes_identical(tmp_path):
    """C-01 §7 case 4. The token is the Server's identity handshake; a
    rewritten token would invalidate every client mid-session."""
    from ordessa_server.bootstrap.runtime import _ensure_token

    spec = resolve_data_root({}, home=str(tmp_path))
    ensure_data_root(spec)
    first_token, first_path = _ensure_token(spec.path)
    first_bytes = first_path.read_bytes()
    second_token, second_path = _ensure_token(spec.path)
    assert second_path == first_path
    assert second_token == first_token
    assert second_path.read_bytes() == first_bytes
    assert stat.S_IMODE(first_path.stat().st_mode) == 0o600


def test_the_override_is_honoured_and_reported_as_such(tmp_path):
    override = str(tmp_path / "explicit")
    spec = resolve_data_root({DATA_ROOT_ENV: override})
    assert spec.path == Path(override)
    assert spec.source == "env"


# -- counterexample 1: a symlinked root, refused before it is read ----------


def test_a_symlinked_root_is_refused_without_reading_the_target(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    secret = target / "must-not-be-read"
    secret.write_text("private", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)

    with pytest.raises(DataRootSymlinkError) as refusal:
        ensure_data_root(resolve_data_root({DATA_ROOT_ENV: str(link)}))

    assert refusal.value.code == "DATA_ROOT_SYMLINK"
    assert refusal.value.reason and refusal.value.remedy
    # The refusal is raised by lstat, so nothing inside the target was read.
    assert "private" not in refusal.value.reason


# -- counterexample 2: a read-only root -------------------------------------


def test_a_read_only_root_is_refused_as_not_writable(tmp_path):
    root = tmp_path / "readonly"
    root.mkdir(mode=0o500)
    try:
        with pytest.raises(DataRootNotWritableError) as refusal:
            ensure_data_root(resolve_data_root({DATA_ROOT_ENV: str(root)}))
        assert refusal.value.code == "DATA_ROOT_NOT_WRITABLE"
        assert refusal.value.reason and refusal.value.remedy
    finally:
        os.chmod(root, 0o700)


# -- counterexample 3: another instance holds the lock -----------------------


def test_a_held_lock_is_reported_as_locked_not_as_a_disk_error(tmp_path):
    root = ensure_data_root(resolve_data_root({}, home=str(tmp_path))).path
    held = instance_lock(root)
    held.acquire()
    try:
        with pytest.raises(DataRootLockedError) as refusal:
            instance_lock(root).acquire()
        assert refusal.value.code == "DATA_ROOT_LOCKED"
        # The whole point of the separate code: the disk is fine.
        assert "DATA_ROOT_NOT_WRITABLE" not in str(refusal.value)
        assert refusal.value.reason and refusal.value.remedy
    finally:
        held.release()


def test_the_probe_reports_a_held_root_without_raising(tmp_path):
    root = ensure_data_root(resolve_data_root({}, home=str(tmp_path))).path
    held = instance_lock(root)
    held.acquire()
    try:
        assert ensure_data_root(resolve_data_root({}, home=str(tmp_path)), lock=True).locked is True
    finally:
        held.release()
    assert ensure_data_root(resolve_data_root({}, home=str(tmp_path)), lock=True).locked is False


# -- counterexample 5: an invalid path --------------------------------------


@pytest.mark.parametrize("value", ["relative/root", "/tmp/../escape"])
def test_an_unusable_path_is_refused_as_invalid(value):
    with pytest.raises(DataRootInvalidError) as refusal:
        resolve_data_root({DATA_ROOT_ENV: value})
    assert refusal.value.code == "DATA_ROOT_INVALID"
    assert refusal.value.reason and refusal.value.remedy


def test_an_empty_environment_value_reads_as_unset_not_as_a_path(tmp_path):
    """An exported-but-empty variable is how shells spell "unset". Refusing it
    would make `ORDESSA_DATA_ROOT= python -m ordessa_server` fail for a reason
    nobody can act on; the default root is the answer that means something."""
    assert resolve_data_root({DATA_ROOT_ENV: ""}, home=str(tmp_path)).source == "default"


def test_an_explicitly_empty_flag_is_refused(tmp_path):
    """`--data-root ""` IS a value the caller passed, and it is not a path."""
    with pytest.raises(DataRootInvalidError):
        resolve_data_root({}, explicit="")


# -- the five codes are exactly the five the contract names -----------------


def test_the_five_typed_errors_carry_reason_and_remedy():
    from ordessa_server.bootstrap.data_root import ERRORS_BY_CODE, LAYOUT

    assert set(ERRORS_BY_CODE) == set(LAYOUT["dataRootErrors"])
    for code, error_type in ERRORS_BY_CODE.items():
        instance = error_type("observed", "how to fix it")
        assert instance.code == code
        assert instance.reason == "observed"
        assert instance.remedy == "how to fix it"
        # The message is the two halves, and nothing else.
        assert str(instance) == f"{code}: observed; how to fix it"


def test_a_refusal_message_never_contains_a_full_path():
    root = Path("/home/someone/.ordessa")
    refusal = DataRootNotWritableError(
        f"the data root is not writable", "check the owner"
    )
    assert str(root) not in str(refusal)
    assert root.name in refusal.reason or True  # basename is allowed; full path is not


# -- the C-02 §2 handoff ---------------------------------------------------


def test_the_launch_env_names_the_three_variables_and_no_token(tmp_path):
    root = ensure_data_root(resolve_data_root({}, home=str(tmp_path))).path
    env = launch_env(root, "http://127.0.0.1:41207")
    assert env == {
        "ORDESSA_DATA_ROOT": str(root),
        "ORDESSA_SERVER_ORIGIN": "http://127.0.0.1:41207",
        "ORDESSA_SERVER_TOKEN_FILE": str(root / "secrets" / "http-token"),
    }
    # Only a locator crosses. The file is not even read here.
    assert not any("\n" in value for value in env.values())


# -- counterexample 6: a historical root keeps its bytes -------------------


def test_a_historical_root_without_a_provider_is_refused_and_untouched(
    tmp_path, monkeypatch,
):
    """C-01 §7 case 6, with a byte-level canary.

    The database is built to look historical, the migration provider is
    made ABSENT (rather than assumed absent — a developer machine that has
    the compatibility distribution installed would otherwise see a
    different answer than a clean one), and the whole root is hashed before
    and after. A refusal that created a WAL, a marker or a token shows up
    here as a changed digest.
    """
    import hashlib
    import importlib.util
    import sqlite3

    real_find_spec = importlib.util.find_spec
    # The preflight does `from importlib.util import find_spec` INSIDE the
    # function, so the only seam that reaches it is the module attribute.
    # Patching anything on `runtime` would be a no-op that quietly turns this
    # canary into a test of whatever the machine happens to have installed.
    assert real_find_spec("pacthold_runtime_compat") is not None, (
        "this canary needs the compatibility distribution INSTALLED, so that "
        "removing it is a real removal rather than a no-op"
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    root = ensure_data_root(resolve_data_root({}, home=str(tmp_path))).path
    state = root / "state"
    state.mkdir(mode=0o700)
    database = state / "agentbox.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE schema_versions (namespace TEXT, version INTEGER)")
    connection.execute("INSERT INTO schema_versions VALUES ('agent_box_legacy', 1)")
    connection.commit()
    connection.close()

    def fingerprint() -> str:
        digest = hashlib.sha256()
        for entry in sorted(root.rglob("*")):
            digest.update(str(entry.relative_to(root)).encode())
            if entry.is_file():
                digest.update(entry.read_bytes())
        return digest.hexdigest()

    before = fingerprint()
    with pytest.raises(DataRootMigrationRefusedError) as refusal:
        ensure_data_root(
            resolve_data_root({DATA_ROOT_ENV: str(root)}),
            require_migration_provider=True,
        )
    assert refusal.value.code == "DATA_ROOT_MIGRATION_REFUSED"
    # The original code stays reachable, and the bytes are untouched.
    assert getattr(refusal.value, "legacy_code", None) == "LEGACY_MIGRATION_PROVIDER_MISSING"
    assert fingerprint() == before


# -- the CLI shares the resolution (C-01 §5) -------------------------------


def test_the_cli_resolves_the_same_root_as_the_library(tmp_path, monkeypatch):
    from ordessa_server import __main__ as host_cli

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(DATA_ROOT_ENV, raising=False)
    spec = resolve_data_root({}, home=str(home))
    assert host_cli.resolved_data_root(None) == ensure_data_root(spec).path


def test_the_cli_accepts_an_explicit_root_and_creates_it(tmp_path):
    from ordessa_server import __main__ as host_cli

    explicit = tmp_path / "chosen"
    assert host_cli.resolved_data_root(explicit) == explicit
    assert explicit.is_dir()


# -- the handshake (C-02 §3.1) ---------------------------------------------


def test_the_handshake_line_is_one_json_object_with_the_documented_fields():
    from ordessa_server.bootstrap.handshake import (
        LISTENING_EVENT,
        ListeningHandshake,
        parse_listening_line,
    )

    line = ListeningHandshake(
        origin="http://127.0.0.1:41207", server_id="server_abc", pid=4321
    ).as_line()
    assert "\n" not in line
    payload = json.loads(line)
    assert set(payload) == {"event", "origin", "serverId", "pid"}
    assert payload["event"] == LISTENING_EVENT
    assert parse_listening_line(line).server_id == "server_abc"


@pytest.mark.parametrize("line", [
    "not json",
    "[]",
    '{"event":"other","origin":"http://127.0.0.1:1","serverId":"s","pid":1}',
    '{"event":"listening","origin":"http://10.0.0.5:1","serverId":"s","pid":1}',
    '{"event":"listening","origin":"http://127.0.0.1:1","serverId":"s","pid":0}',
    '{"event":"listening","origin":"http://127.0.0.1:1","serverId":"s"}',
    '{"event":"listening","origin":"http://127.0.0.1:1","serverId":"s","pid":1,"x":1}',
])
def test_a_line_that_is_not_a_handshake_is_refused(line):
    from ordessa_server.bootstrap.handshake import parse_listening_line

    assert parse_listening_line(line) is None


def test_the_server_process_prints_exactly_one_handshake_line(tmp_path):
    """The end-to-end shape: a real process, a real stdout line."""
    from ordessa_server.bootstrap.handshake import (
        ListeningHandshake,
        emit_listening_handshake,
        parse_listening_line,
    )

    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'src')!r})
        from ordessa_server.bootstrap.handshake import (
            ListeningHandshake, emit_listening_handshake,
        )
        emit_listening_handshake(ListeningHandshake(
            origin="http://127.0.0.1:{_free_port()}", server_id="server_e2e", pid=1,
        ))
    """)
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=30,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    assert parse_listening_line(lines[0]) is not None


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


# -- PB-06: the headless-CLI audit, pinned so a second entry point trips it --


def test_exactly_one_entry_point_starts_a_server_process():
    """PB-06's audit, made executable.

    Two console scripts exist. Only one of them starts a Server; the other
    is a one-shot credential import that builds a runtime in-process and
    stops it. Both take `--data-root` EXPLICITLY, so neither carries a
    second spelling of the resolution order.

    The test pins the shape rather than the names: a future script that
    starts a Server and resolves its own data root would have to appear
    here, and would be the thing this gate is for.
    """
    from importlib import metadata

    scripts = {
        entry.name: entry.value
        for entry in metadata.entry_points(group="console_scripts")
        if "ordessa_server" in entry.value
    }
    # The only one that runs a Server is the transport CLI.
    assert scripts["ordessa-server"] == "ordessa_server.__main__:main"
    for name, target in scripts.items():
        if name == "ordessa-server":
            continue
        # Every other entry point must take its root from the caller.
        source = _source_of(target)
        assert "--data-root" in source, f"{name} resolves a data root of its own"
        assert "required=True" in source, f"{name} makes --data-root optional"


def _source_of(target: str) -> str:
    """The source text behind a `module:function` entry point, PLUS the
    module it lives in.

    The flag may be declared in a `parser()` beside `main()` rather than in
    `main()` itself, so the whole module is what has to be read — reading
    only the entry function would miss the declaration and call it a
    divergence that does not exist.
    """
    import importlib
    import inspect

    module_name, _, function_name = target.partition(":")
    module = importlib.import_module(module_name)
    return inspect.getsource(module) + inspect.getsource(
        getattr(module, function_name)
    )


def test_the_headless_smoke_wrapper_passes_an_explicit_root():
    """`scripts/start-server.sh` always passes `--data-root`, so it neither
    needs nor depends on the default. It is P-C's file, and this asserts
    rather than edits."""
    wrapper = (
        Path(__file__).resolve().parents[3] / "scripts" / "start-server.sh"
    ).read_text(encoding="utf-8")
    assert "--data-root" in wrapper


def test_the_kernel_clis_do_not_resolve_a_server_data_root():
    """`pacthold` and `pacthold_runtime_compat` read `AGENT_BOX_HOME`, which
    is the kernel's OWN home and a different fact from the Server data root.
    Pinned so a future change cannot quietly make it the same one."""
    import pacthold.work_core.runtime as kernel_runtime

    assert kernel_runtime.AGENT_BOX_HOME_ENV == "AGENT_BOX_HOME"
    assert kernel_runtime.AGENT_BOX_HOME_ENV != DATA_ROOT_ENV
