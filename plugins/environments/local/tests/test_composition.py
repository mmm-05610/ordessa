"""Local v1 composition: stage -> wrap -> launch -> observe -> cleanup.

Every case runs a real OS process through the v1 seam; the local host's
unsupported effects (transport, compensation) must refuse rather than pretend.
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import sys

import pytest

from ordessa_environments import (
    BYTE_CHANNEL_CAPABILITY,
    FILE_AREA_CAPABILITY,
    PROCESS_CAPABILITY,
    STREAMING_STDERR_CAPABILITY,
    TERMINAL_CAPABILITY,
    EnvironmentRefused,
)
from ordessa_environments.composition import (
    CapabilityStatus,
    CompositionErrorCode,
    CompositionRejected,
    IsolatedProcessSpec,
    ProcessHandle,
    ProjectionRejected,
    RuntimeHostRef,
    SandboxRef,
    SandboxUnsupported,
)
from ordessa_environments_local import LocalCompositionProvider


class _Command:
    """A structural CommandInput view for the seam under test."""

    def __init__(self, argv, cwd_token, environment=None, io_mode="stdio"):
        self.argv = tuple(argv)
        self.cwd_token = cwd_token
        self.environment = {} if environment is None else dict(environment)
        self.io_mode = io_mode
        self.command_digest = "sha256:command"
        self.runtime_sources = ()
        self.requires_control_plane_network = False
        self.tool_network_requirement = "none"
        self.projector_id = "test"

    @property
    def digest(self) -> str:
        return self.command_digest


class _Plan:
    """A structural MountPlanInput view for the seam under test."""

    mounts = ()
    tmpfs_targets = ()
    plan_digest = "sha256:mount-plan"
    secret_mounts = ()

    @property
    def digest(self) -> str:
        return self.plan_digest


class _Bundle:
    """A structural RuntimeBundleInput view for the seam under test."""

    def __init__(self, host_ref):
        self.host_ref = host_ref
        self.mount_plan = _Plan()
        self.bundle_digest = "sha256:bundle"
        self.staging_tokens = ()


def _provider(tmp_path):
    return LocalCompositionProvider(root=str(tmp_path / "root"))


async def _drain_stdout(handle):
    chunks = bytearray()
    while True:
        data = await handle.read_stdout(4096, timeout=5)
        if not data:
            return bytes(chunks)
        chunks.extend(data)


async def _launch_and_capture(sandbox, argv, guest_cwd, *, attempt_key, environment=None):
    """Wrap -> launch -> drain stdout -> wait; returns (spec, stdout, exit code)."""
    spec = sandbox.wrap(_Plan(), _Command(argv, guest_cwd, environment), attempt_key=attempt_key)
    handle = sandbox.launch(spec, attempt_key=attempt_key)
    try:
        output = await _drain_stdout(handle)
        observation = await handle.wait_exit(timeout=10)
        assert observation.state == "exited"
        return spec, output, observation.exit_code
    finally:
        handle.release()


def test_stage_wrap_launch_echo_round_trip_and_cleanup(tmp_path):
    async def exercise():
        provider = _provider(tmp_path)
        host, sandbox = provider.host, provider.sandbox
        bundle = _Bundle(host.ref)
        assert host.stage(bundle) is bundle  # no fake staging step

        spec = sandbox.wrap(
            _Plan(), _Command(["/bin/echo", "hello"], "/work"), attempt_key="attempt-1",
        )
        assert spec.local_argv == ("/bin/echo", "hello")
        assert spec.attempt_key == "attempt-1"
        assert spec.spec_digest.startswith("sha256:")
        # The local cwd/env are provider-private: they never reach the public spec.
        assert not hasattr(spec, "cwd") and not hasattr(spec, "env")

        handle = sandbox.launch(spec, attempt_key="attempt-1")
        try:
            assert isinstance(handle, ProcessHandle)
            assert await _drain_stdout(handle) == b"hello\n"
            observation = await handle.wait_exit(timeout=5)
            assert observation.state == "exited"
            assert observation.exit_code == 0
        finally:
            handle.release()

        receipt = sandbox.cleanup(spec)
        assert receipt["specDigest"] == spec.spec_digest
        assert receipt["exitClaimed"] is False
        assert "exitCode" not in receipt
    asyncio.run(exercise())


def test_non_zero_exit_is_preserved(tmp_path):
    async def exercise():
        sandbox = _provider(tmp_path).sandbox
        spec = sandbox.wrap(
            _Plan(),
            _Command([sys.executable, "-c", "import sys; sys.exit(3)"], "/work"),
            attempt_key="attempt-2",
        )
        handle = sandbox.launch(spec, attempt_key="attempt-2")
        try:
            observation = await handle.wait_exit(timeout=10)
            assert observation.state == "exited"
            assert observation.exit_code == 3
        finally:
            handle.release()
    asyncio.run(exercise())


def test_cwd_maps_under_the_root_and_escapes_are_refused(tmp_path):
    root = str(tmp_path / "root")
    sandbox = _provider(tmp_path).sandbox

    async def exercise():
        # The private cwd really is the mapped guest path, even though the
        # public spec no longer carries it.
        _, output, code = await _launch_and_capture(
            sandbox, [sys.executable, "-c", "import os; print(os.getcwd())"],
            "/nested/dir", attempt_key="attempt-3",
        )
        assert code == 0
        assert output.decode().strip() == os.path.join(root, "nested", "dir")
    asyncio.run(exercise())

    for guest in ("relative", "", "../escape", "/work/../../etc", "/work/", "/work//dir"):
        with pytest.raises(ProjectionRejected):
            sandbox.wrap(_Plan(), _Command(["/bin/echo"], guest), attempt_key="attempt-3")


def test_wrap_keeps_the_environment_private_and_the_spec_digest_is_stable(tmp_path):
    sandbox = _provider(tmp_path).sandbox
    command = _Command(["/bin/echo", "x"], "/work", {"A": "1", "B": ""})
    first = sandbox.wrap(_Plan(), command, attempt_key="attempt-4")
    again = sandbox.wrap(_Plan(), command, attempt_key="attempt-4")
    other = sandbox.wrap(_Plan(), command, attempt_key="attempt-5")

    # The provider-private environment never crosses into the public projection.
    assert not hasattr(first, "env") and not hasattr(first, "cwd")
    assert first.spec_digest == again.spec_digest
    assert first.spec_digest != other.spec_digest
    assert first.spawn_token != other.spawn_token

    async def exercise():
        # ...but it really does reach the spawned process.
        _, output, code = await _launch_and_capture(
            sandbox, [sys.executable, "-c", "import os; print(os.environ.get('A', ''))"],
            "/work", attempt_key="attempt-4", environment={"A": "1", "B": ""},
        )
        assert code == 0
        assert output.strip() == b"1"
    asyncio.run(exercise())


def test_ref_mismatch_capability_and_launch_refusals(tmp_path):
    provider = _provider(tmp_path)
    host, sandbox = provider.host, provider.sandbox

    assert provider.resolve(host.ref, sandbox.ref) == (host, sandbox)
    assert host.ref.affinity == sandbox.ref.affinity
    assert host.ref.provider == sandbox.ref.provider == "local"

    other_host = RuntimeHostRef("local", "other-host", "sha256:other", "other-affinity")
    other_sandbox = SandboxRef("local", "other-sandbox", "sha256:other", "other-affinity")
    with pytest.raises(CompositionRejected) as host_mismatch:
        host.resolve(other_host)
    assert host_mismatch.value.code is CompositionErrorCode.INVALID_BINDING
    with pytest.raises(CompositionRejected):
        sandbox.resolve(other_sandbox)
    with pytest.raises(CompositionRejected):
        host.stage(_Bundle(other_host))

    # The local host provides no host transport and no compensation: refuse.
    with pytest.raises(CompositionRejected) as terminate:
        host.terminate(object())
    assert terminate.value.code is CompositionErrorCode.CAPABILITY_UNSUPPORTED
    with pytest.raises(CompositionRejected):
        host.transport.submit(object())

    # Capability report: proven keys supported, terminal explicitly unsupported.
    values = sandbox.capabilities.values
    for capability in (PROCESS_CAPABILITY, FILE_AREA_CAPABILITY,
                       BYTE_CHANNEL_CAPABILITY, STREAMING_STDERR_CAPABILITY):
        assert values[capability] is CapabilityStatus.SUPPORTED
    assert values[TERMINAL_CAPABILITY] is CapabilityStatus.UNSUPPORTED
    assert host.capabilities.values[TERMINAL_CAPABILITY] is CapabilityStatus.UNSUPPORTED

    # A provider-transport spec is not a local launch representation.
    remote = IsolatedProcessSpec("token", "attempt-6", "sha256:remote", provider_transport="remote")
    with pytest.raises(SandboxUnsupported):
        sandbox.launch(remote, attempt_key="attempt-6")

    # The attempt key must match the wrapped spec; private launch facts are
    # looked up by attempt and must exist and match the presented spec.
    spec = sandbox.wrap(_Plan(), _Command(["/bin/echo"], "/work"), attempt_key="attempt-6")
    with pytest.raises(CompositionRejected) as replay:
        sandbox.launch(spec, attempt_key="other-attempt")
    assert replay.value.code is CompositionErrorCode.ATTEMPT_REPLAY
    unwrapped = IsolatedProcessSpec(
        "token", "attempt-6", "sha256:escape", local_argv=("/bin/echo",),
    )
    with pytest.raises(CompositionRejected) as no_facts:
        sandbox.launch(unwrapped, attempt_key="attempt-6")
    assert no_facts.value.code is CompositionErrorCode.INVALID_BINDING
    tampered = dataclasses.replace(spec, spec_digest="sha256:tampered")
    with pytest.raises(CompositionRejected) as mismatch:
        sandbox.launch(tampered, attempt_key="attempt-6")
    assert mismatch.value.code is CompositionErrorCode.INVALID_BINDING


def test_inconsistent_refs_are_refused_by_the_factory(tmp_path):
    root = str(tmp_path / "root")
    host_ref = RuntimeHostRef("local", "local-host", "sha256:host", "affinity-a")
    sandbox_ref = SandboxRef("local", "local-sandbox", "sha256:policy", "affinity-b")
    with pytest.raises(EnvironmentRefused):
        LocalCompositionProvider(root=root, host_ref=host_ref, sandbox_ref=sandbox_ref)
    with pytest.raises(EnvironmentRefused):
        LocalCompositionProvider(
            root=root,
            host_ref=RuntimeHostRef("openshell", "host", "sha256:host", "affinity-a"),
            sandbox_ref=SandboxRef("openshell", "sandbox", "sha256:policy", "affinity-a"),
        )


def test_cleanup_claims_no_exit_and_does_not_stop_the_process(tmp_path):
    async def exercise():
        sandbox = _provider(tmp_path).sandbox
        spec = sandbox.wrap(
            _Plan(),
            _Command([sys.executable, "-c", "import time; time.sleep(30)"], "/work"),
            attempt_key="attempt-7",
        )
        handle = sandbox.launch(spec, attempt_key="attempt-7")
        try:
            receipt = sandbox.cleanup(spec)
            assert receipt["exitClaimed"] is False
            assert "exitCode" not in receipt
            # Cleanup is a receipt, not a stop: the process is still running.
            assert handle.observe().state == "running"
            # Cleanup also clears the private launch facts: the cleaned spec
            # cannot be launched again, so cleanup never re-spawns.
            with pytest.raises(CompositionRejected) as cleared:
                sandbox.launch(spec, attempt_key="attempt-7")
            assert cleared.value.code is CompositionErrorCode.INVALID_BINDING
        finally:
            await handle.cancel(force=True)
            await handle.wait_exit(timeout=5)
            handle.release()
    asyncio.run(exercise())
