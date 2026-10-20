"""Local environment: real process, real byte channel, real release semantics.

Every case here runs a real OS process through the managed ``EnvironmentUse``
(the v1 ``LocalUse`` composition) and a real SQLite registry. Nothing is
mocked: the point is that the Use performs the actual spawn and that ``release``
is not ``destroy``. The retired ``LocalEnvironmentHandle`` /
``LocalEnvironmentProvider`` path no longer exists and is not exercised.
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import suppress

import pytest

from ordessa_environments import (
    BYTE_CHANNEL_CAPABILITY,
    PROCESS_CAPABILITY,
    TERMINAL_CAPABILITY,
    CapabilityReport,
    EnvironmentGuaranteeUnmet,
    EnvironmentManager,
    EnvironmentRefused,
    ProcessRequest,
    ProcessStartFailed,
    SQLiteEnvironmentStore,
    require_capabilities,
)
from ordessa_environments_local import (
    LocalEnvironmentResourceProvider,
    probe_local,
    spawn,
)

#: A controlled peer: echoes one stdin line on stdout and one on stderr.
ECHO_PEER = (
    "import sys\n"
    "line = sys.stdin.readline()\n"
    "sys.stderr.write('diag:' + line)\n"
    "sys.stderr.flush()\n"
    "sys.stdout.write('echo:' + line)\n"
    "sys.stdout.flush()\n"
)


def _manager(tmp_path, root):
    provider = LocalEnvironmentResourceProvider(default_root=str(root))
    return EnvironmentManager(
        store=SQLiteEnvironmentStore(tmp_path / "env.db"),
        providers={"local": provider},
    )


@pytest.fixture
def managed(tmp_path):
    root = tmp_path / "environment"
    manager = _manager(tmp_path, root)
    instance = manager.create("local", {"root": str(root)})
    use = instance.acquire("local-test", sharing=False)
    yield use
    # Test-owned processes are released by each case; this only guarantees no
    # real OS process leaks on a mid-test failure, then best-effort releases.
    with suppress(Exception):
        for handle in use._backend.execution.owned():  # owner's own reaping view
            if handle.observe().state != "exited":
                asyncio.run(handle.cancel(force=True))
                asyncio.run(handle.wait_exit(timeout=10))
            handle.release()
    with suppress(EnvironmentRefused):
        use.release()


def _request(use, *, argv=None, name="work"):
    return ProcessRequest.build(
        argv or [sys.executable, "-u", "-c", ECHO_PEER],
        cwd=use.files.ensure(name),
        env={"HOME": use.files.ensure("home"), "PATH": "/usr/bin:/bin"},
    )


def test_isolation_none_is_reported_honestly(managed):
    assert isinstance(managed.capabilities, CapabilityReport)
    assert managed.capabilities.isolation == "none"
    assert BYTE_CHANNEL_CAPABILITY in managed.capabilities.provides
    assert managed.identity.startswith("environment-use/")


def test_real_process_round_trips_through_the_use(managed):
    async def exercise():
        process = managed.execution.start(_request(managed))
        try:
            assert process.observe().state == "running"
            # The channel is bidirectional and byte-exact.
            assert await process.write_stdin(b"hello\n") == 6
            assert await process.read_stdout(4096, timeout=15) == b"echo:hello\n"
            await process.close_stdin()
            assert (await process.wait_exit(timeout=15)).exit_code == 0
        finally:
            process.release()
    asyncio.run(exercise())


def test_stderr_is_a_real_separate_stream(managed):
    async def exercise():
        process = managed.execution.start(_request(managed))
        try:
            await process.write_stdin(b"hello\n")
            assert await process.read_stdout(4096, timeout=15) == b"echo:hello\n"
            assert await process.read_stderr(4096, timeout=15) == b"diag:hello\n"
            await process.close_stdin()
            assert (await process.wait_exit(timeout=15)).state == "exited"
        finally:
            process.release()
    asyncio.run(exercise())


def test_start_failure_owns_no_process(managed, tmp_path):
    missing = str(tmp_path / "no-such-executable")
    request = ProcessRequest.build(
        [missing], cwd=managed.files.ensure("work2"), env={"HOME": managed.files.ensure("home")}
    )
    with pytest.raises(ProcessStartFailed):
        managed.execution.start(request)
    # Nothing is owned after a failed start: no half-open handle leaks out.
    assert managed._backend.execution.owned() == ()


def test_release_is_not_destroy(managed):
    """Releasing must leave the working directory and its files intact."""
    request = _request(managed, name="keepme")

    async def exercise():
        process = managed.execution.start(request)
        await process.close_stdin()
        return process, await process.wait_exit(timeout=15)

    process, observation = asyncio.run(exercise())
    assert observation.state == "exited"

    marker = os.path.join(request.cwd, "artifact.txt")
    with open(marker, "w", encoding="utf-8") as stream:
        stream.write("kept\n")

    facts = process.release()
    assert facts["exitCode"] == "0"

    assert os.path.isdir(request.cwd), "release removed the working directory"
    assert os.path.isfile(marker), "release removed a file the process created"

    use_facts = managed.release()
    assert use_facts["resourcePreserved"] is True
    assert use_facts["providerFacts"]["rootPreserved"] is True
    assert os.path.isdir(request.cwd), "use release removed the working directory"
    assert os.path.isfile(marker), "use release removed the process's file"
    with open(marker, encoding="utf-8") as stream:
        assert stream.read() == "kept\n"


def test_process_transport_release_is_idempotent(managed):
    async def exercise():
        process = managed.execution.start(_request(managed))
        await process.close_stdin()
        await process.wait_exit(timeout=15)
        return process

    process = asyncio.run(exercise())
    facts = process.release()
    assert process.release() == facts
    assert facts["processState"] == "exited"


def test_transport_release_does_not_fake_exit_or_kill_running_process(managed):
    process = managed.execution.start(
        _request(managed, argv=[sys.executable, "-c", "import time;time.sleep(30)"])
    )
    try:
        assert process.observe().state == "running"
        facts = process.release()
        assert facts["transportReleased"] is True
        assert facts["processState"] == "running" and "exitCode" not in facts
        assert process.observe().state == "running"
        assert process.release() == facts
    finally:
        if process.observe().state != "exited":
            asyncio.run(process.cancel(force=True))
            asyncio.run(process.wait_exit(timeout=10))


def test_use_release_refuses_while_it_owns_a_running_process(managed):
    process = managed.execution.start(_request(managed))
    try:
        with pytest.raises(EnvironmentRefused):
            managed.release()
    finally:
        asyncio.run(process.cancel(force=True))
        asyncio.run(process.wait_exit(timeout=10))
        process.release()
    assert managed.release()["resourcePreserved"] is True


def test_a_released_use_is_stale(managed):
    async def exercise():
        process = managed.execution.start(_request(managed))
        await process.close_stdin()
        await process.wait_exit(timeout=15)
        return process

    process = asyncio.run(exercise())
    process.release()
    managed.release()
    with pytest.raises(EnvironmentRefused):
        managed.execution
    assert managed.release()["providerFacts"]["rootPreserved"] is True


def test_unsupported_isolation_reference_is_refused(tmp_path):
    provider = LocalEnvironmentResourceProvider(default_root=str(tmp_path / "env"))
    for isolation in ("container", "vm", "pool", "snapshot"):
        with pytest.raises(EnvironmentRefused):
            provider.create({"isolation": isolation}, operation_id="op")
    # The honest report is available without opening anything.
    probe = probe_local(default_root=str(tmp_path / "env"))
    assert probe["isolation"] == "none"


def test_unknown_reference_key_is_refused(tmp_path):
    provider = LocalEnvironmentResourceProvider(default_root=str(tmp_path / "env"))
    with pytest.raises(EnvironmentRefused):
        provider.create({"isolation": "none", "dockerImage": "x"}, operation_id="op")


def test_file_area_refuses_to_escape_its_root(managed):
    with pytest.raises(EnvironmentRefused):
        managed.files.path("../outside")
    with pytest.raises(EnvironmentRefused):
        managed.files.path("/etc/passwd")
    # The area is real and bounded to its own root.
    created = managed.files.ensure("inner")
    assert created.startswith(managed.files.root())
    assert managed.files.path("inner") == created


def test_capability_check_refuses_a_capability_the_use_lacks(managed):
    require_capabilities(managed.capabilities, [PROCESS_CAPABILITY])  # present -> allowed
    with pytest.raises(EnvironmentGuaranteeUnmet):
        require_capabilities(managed.capabilities, [PROCESS_CAPABILITY, TERMINAL_CAPABILITY])


def test_spawn_rejects_a_foreign_request_object(tmp_path):
    with pytest.raises(EnvironmentRefused):
        spawn("not-a-request")


def test_file_area_refuses_symlink_escape(managed, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "environment" / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(EnvironmentRefused, match="escapes"):
        managed.files.path("link/private.txt")
    with pytest.raises(EnvironmentRefused, match="escapes"):
        managed.files.ensure("link/created")
    assert not (outside / "created").exists()


def test_file_area_root_itself_can_be_a_symlink(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    manager = _manager(tmp_path, alias)
    instance = manager.create("local", {"root": str(alias)})
    # The managed backend identity is the canonical directory root, so the
    # bounded area is rooted at the physical path rather than the alias.
    assert instance.snapshot.backend_id == str(actual)
    use = instance.acquire("alias-test", sharing=False)
    try:
        assert use.files.ensure("inside") == str(actual / "inside")
        assert (actual / "inside").is_dir()
    finally:
        use.release()


def test_different_uses_do_not_reuse_identity(tmp_path):
    left = _manager(tmp_path, tmp_path / "left").create("local", {"root": str(tmp_path / "left")})
    right = _manager(tmp_path, tmp_path / "right").create("local", {"root": str(tmp_path / "right")})
    left_use = left.acquire("left-test", sharing=False)
    right_use = right.acquire("right-test", sharing=False)
    try:
        assert left_use.identity != right_use.identity
        assert left_use.identity.startswith("environment-use/")
    finally:
        left_use.release()
        right_use.release()
