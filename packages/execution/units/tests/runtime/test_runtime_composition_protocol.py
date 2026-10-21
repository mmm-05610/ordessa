"""v1 composition protocol: launch-backed process, attempt fuse, no terminal."""
from __future__ import annotations

import dataclasses

import pytest

from .peers import (
    FakeHost, FakeProcessHandle, FakeSandbox, TargetCreationSentinel, coordinator_for,
)
from ordessa_units.assembly.runtime.coordinator import (
    CompositionExecution, ResolvedComposition, RuntimeCompositionCoordinator,
)
from ordessa_agents.harness.definitions.command_projection import HarnessCommandSpec
from ordessa_environments.composition import MountPlan, RuntimeBinding, RuntimeBundle, StartAmbiguous
from ordessa_environments.definitions.runtime_resources import RuntimeHostRef, SandboxRef


def make_stack(*, lose_response=False):
    affinity = "fake:linux:amd64"
    host_ref = RuntimeHostRef("fake-host", "host-1", "host-digest", affinity)
    sandbox_ref = SandboxRef("fake-sandbox", "sandbox-1", "policy-digest", affinity)
    sentinel = TargetCreationSentinel()
    host = FakeHost(host_ref)
    sandbox = FakeSandbox(sandbox_ref, sentinel, lose_response=lose_response)
    binding, coordinator = coordinator_for(host, sandbox)
    return coordinator, sentinel, binding, host, sandbox


def test_v1_composition_has_no_terminal_surface():
    assert tuple(field.name for field in dataclasses.fields(ResolvedComposition)) == ("host", "sandbox")
    assert tuple(field.name for field in dataclasses.fields(CompositionExecution)) == (
        "handle", "spec", "attempt_key", "host_ref", "sandbox_ref", "preflight", "staged_bundle",
    )
    assert not hasattr(RuntimeCompositionCoordinator, "present")
    for terminal_verb in ("allocate", "run", "release"):
        assert not hasattr(FakeSandbox, terminal_verb), terminal_verb


def test_resolve_assemble_wrap_do_not_spawn_and_launch_is_the_entrypoint():
    coordinator, sentinel, binding, host, sandbox = make_stack()
    command = HarnessCommandSpec(("harness", "--once"), "cwd-token")
    bundle = host.stage(RuntimeBundle(host.ref, MountPlan(), "sha256:bundle"))
    isolated = sandbox.wrap(bundle.mount_plan, command, attempt_key="attempt")
    assert sentinel.count == 0
    handle = sandbox.launch(isolated, attempt_key="attempt")
    assert sentinel.count == 1
    assert isinstance(handle, FakeProcessHandle)
    handle.release()


def test_start_returns_a_launch_backed_execution_and_replay_never_spawns_twice():
    coordinator, sentinel, binding, host, sandbox = make_stack()
    command = HarnessCommandSpec(("harness",), "cwd-token")
    first = coordinator.start(binding, command, execution_id="e1", dispatch_id="d1")
    assert isinstance(first, CompositionExecution)
    assert isinstance(first.handle, FakeProcessHandle)
    assert first.spec.local_argv == ("harness",)
    assert first.attempt_key in coordinator.ledger
    assert first.host_ref == host.ref and first.sandbox_ref == sandbox.ref
    assert first.preflight.accepted
    assert first.staged_bundle is host.staged[0]  # the host staging receipt is retained

    second = coordinator.start(binding, command, execution_id="e1", dispatch_id="d1")
    assert first is second
    assert sentinel.count == 1
    assert host.staged == [first.staged_bundle]
    assert coordinator.ledger[first.attempt_key].target_creation_count <= 1


def test_response_loss_is_ambiguous_and_replay_does_not_start_again():
    coordinator, sentinel, binding, host, sandbox = make_stack(lose_response=True)
    command = HarnessCommandSpec(("harness",), "cwd-token")
    with pytest.raises(StartAmbiguous):
        coordinator.start(binding, command, execution_id="e1", dispatch_id="d1")
    assert sentinel.count == 1
    key = next(iter(coordinator.ledger))
    assert coordinator.ledger[key].state == "AMBIGUOUS"
    with pytest.raises(StartAmbiguous):
        coordinator.start(binding, command, execution_id="e1", dispatch_id="d1")
    assert sentinel.count == 1


def test_both_refs_are_required_and_affinity_is_checked():
    coordinator, _, binding, host, sandbox = make_stack()
    with pytest.raises(Exception):
        RuntimeBinding(binding.runtime_host_ref, None)
    mismatched = RuntimeBinding(
        binding.runtime_host_ref,
        SandboxRef("fake-sandbox", "sandbox-2", "other", "other:realm"),
    )
    assert not coordinator.preflight(mismatched).accepted


def test_cleanup_compensates_sandbox_then_host_then_releases_the_process():
    coordinator, sentinel, binding, host, sandbox = make_stack()
    command = HarnessCommandSpec(("harness",), "cwd-token")
    execution = coordinator.start(binding, command, execution_id="e1", dispatch_id="d1")
    results = coordinator.cleanup(execution.attempt_key)
    # Inner-to-outer: the sandbox spec, then the host execution, then the
    # process owner; none of them claims an exit.
    assert sandbox.cleaned == [execution.spec]
    assert host.cleaned == ["e1"]
    assert results["sandbox"]["exitClaimed"] is False
    assert results["process"] == {"released": True, "exitClaimed": False, "handle": execution.handle.identity}
    assert execution.handle.released == 1
    assert coordinator.cleanup(execution.attempt_key) == {"status": "already_cleaned"}
    assert execution.handle.released == 1
