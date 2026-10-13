"""Local environment: real process, real byte channel, real release semantics.

Every case here runs a real OS process. Nothing is mocked: the point of P0 is
that the environment performs the actual spawn and that ``release`` is not
``destroy``.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import pytest

from ordessa_environments import (
    BYTE_CHANNEL_CAPABILITY,
    Capabilities,
    EnvironmentGuaranteeUnmet,
    EnvironmentRefused,
    ProcessHandleStale,
    ProcessRequest,
    ProcessStartFailed,
    require_guarantees,
)
from ordessa_environments_local import LocalEnvironmentProvider, spawn

#: A controlled peer: echoes one stdin line on stdout and one on stderr.
ECHO_PEER = (
    "import sys\n"
    "line = sys.stdin.readline()\n"
    "sys.stderr.write('diag:' + line)\n"
    "sys.stderr.flush()\n"
    "sys.stdout.write('echo:' + line)\n"
    "sys.stdout.flush()\n"
)


@pytest.fixture
def environment(tmp_path):
    provider = LocalEnvironmentProvider(default_root=str(tmp_path / "environment"))
    handle = provider.open({"isolation": "none"})
    try:
        yield handle
    finally:
        # The environment owns these; stop anything a test left alive so the
        # release guard is not the thing under test here.
        for process in handle.execution.handles():
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        if not handle.released:
            handle.release()


def _request(handle, *, argv=None, name="work"):
    return ProcessRequest.build(
        argv or [sys.executable, "-u", "-c", ECHO_PEER],
        cwd=handle.files.ensure(name),
        env={"HOME": handle.files.ensure("home"), "PATH": "/usr/bin:/bin"},
    )


def test_isolation_none_is_reported_honestly(environment):
    assert environment.capabilities.isolation == "none"
    assert BYTE_CHANNEL_CAPABILITY in environment.capabilities.provides
    assert environment.identity.startswith("local-environment/")


def test_real_process_round_trips_through_the_handle(environment):
    process = environment.execution.start(_request(environment))
    try:
        assert process.poll() is None
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(b"hello\n")
        process.stdin.flush()
        # The channel is bidirectional and byte-exact.
        assert process.stdout.readline() == b"echo:hello\n"
        process.stdin.close()
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_stderr_is_a_real_separate_stream(environment):
    process = environment.execution.start(_request(environment))
    try:
        process.stdin.write(b"hello\n")
        process.stdin.flush()
        assert process.stdout.readline() == b"echo:hello\n"
        assert process.stderr.readline() == b"diag:hello\n"
        process.stdin.close()
        process.wait(timeout=15)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_start_failure_owns_no_process(environment, tmp_path):
    missing = str(tmp_path / "no-such-executable")
    request = ProcessRequest.build([missing], cwd=environment.files.ensure("work2"),
                                   env={"HOME": environment.files.ensure("home")})
    with pytest.raises(ProcessStartFailed):
        environment.execution.start(request)
    # Nothing is owned after a failed start: no half-open handle leaks out.
    assert environment.execution.owned() == ()
    assert environment.execution.running() == ()


def test_release_is_not_destroy(environment):
    """Releasing must leave the working directory and its files intact."""
    request = _request(environment, name="keepme")
    process = environment.execution.start(request)
    process.stdin.close()
    process.wait(timeout=15)

    marker = os.path.join(request.cwd, "artifact.txt")
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write("kept\n")

    facts = process.release()
    assert facts["exitCode"] == '0'

    assert os.path.isdir(request.cwd), "release removed the working directory"
    assert os.path.isfile(marker), "release removed a file the process created"
    with open(marker, encoding="utf-8") as handle:
        assert handle.read() == "kept\n"

    environment_facts = environment.release()
    assert environment_facts["rootPreserved"] is True
    assert os.path.isdir(request.cwd), "environment release removed the working directory"
    assert os.path.isfile(marker), "environment release removed the process's file"


def test_process_transport_release_is_idempotent(environment):
    process = environment.execution.start(_request(environment))
    process.stdin.close()
    process.wait(timeout=15)
    facts=process.release()
    assert process.release()==facts
    assert facts['processState']=='exited'


def test_transport_release_does_not_fake_exit_or_kill_running_process(environment):
    process = environment.execution.start(_request(environment,argv=[sys.executable,'-c','import time;time.sleep(30)']))
    try:
        assert process.poll() is None
        facts=process.release()
        assert facts['transportReleased'] is True
        assert facts['processState']=='running' and 'exitCode' not in facts
        assert process.observe().state=='running'
        assert process.release()==facts
        # Transport release did not fake a stop: the process is still alive.
        assert process.poll() is None
    finally:
        process.kill()
        process.wait(timeout=10)


def test_environment_release_refuses_while_it_owns_a_running_process(environment):
    process = environment.execution.start(_request(environment))
    try:
        with pytest.raises(EnvironmentRefused):
            environment.release()
        assert environment.released is False
    finally:
        process.kill()
        process.wait(timeout=10)


def test_a_released_environment_handle_is_stale(environment):
    environment.release()
    with pytest.raises(EnvironmentRefused):
        environment.execution.start(_request(environment))
    assert environment.release()['rootPreserved'] is True


def test_unsupported_isolation_reference_is_refused(tmp_path):
    provider = LocalEnvironmentProvider(default_root=str(tmp_path / "env"))
    for isolation in ("container", "vm", "pool", "snapshot"):
        with pytest.raises(EnvironmentRefused):
            provider.resolve({"isolation": isolation})
    # The honest report is available without opening anything.
    assert provider.probe()["isolation"] == "none"


def test_unknown_reference_key_is_refused(tmp_path):
    provider = LocalEnvironmentProvider(default_root=str(tmp_path / "env"))
    with pytest.raises(EnvironmentRefused):
        provider.resolve({"isolation": "none", "dockerImage": "x"})


def test_file_area_refuses_to_escape_its_root(environment, tmp_path):
    with pytest.raises(EnvironmentRefused):
        environment.files.path("../outside")
    with pytest.raises(EnvironmentRefused):
        environment.files.path("/etc/passwd")
    # The area is real and bounded to its own root.
    created = environment.files.ensure("inner")
    assert created.startswith(environment.files.root())
    assert environment.files.path("inner") == created


def test_guarantee_check_refuses_a_capability_the_handle_lacks():
    @dataclass(frozen=True)
    class _Handle:
        identity: str
        capabilities: Capabilities

    handle = _Handle("fixture", Capabilities(isolation="none", provides=frozenset({"process"})))
    require_guarantees(handle, ["process"])  # present -> allowed
    with pytest.raises(EnvironmentGuaranteeUnmet):
        require_guarantees(handle, ["process", "terminal"])


def test_spawn_rejects_a_foreign_request_object(tmp_path):
    with pytest.raises(EnvironmentRefused):
        spawn("not-a-request")


def test_file_area_refuses_symlink_escape(environment, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (tmp_path / 'environment' / 'link').symlink_to(outside, target_is_directory=True)
    with pytest.raises(EnvironmentRefused, match='escapes'):
        environment.files.path('link/private.txt')
    with pytest.raises(EnvironmentRefused, match='escapes'):
        environment.files.ensure('link/created')
    assert not (outside / 'created').exists()


def test_file_area_root_itself_can_be_a_symlink(tmp_path):
    actual = tmp_path / 'actual'
    actual.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(actual, target_is_directory=True)
    handle = LocalEnvironmentProvider(default_root=str(alias)).open()
    try:
        assert handle.files.ensure('inside') == str(alias / 'inside')
        assert (actual / 'inside').is_dir()
    finally:
        handle.release()


def test_different_local_providers_do_not_reuse_handle_identity(tmp_path):
    left = LocalEnvironmentProvider(default_root=str(tmp_path / 'left')).open()
    right = LocalEnvironmentProvider(default_root=str(tmp_path / 'right')).open()
    try:
        assert left.identity != right.identity
    finally:
        left.release()
        right.release()
