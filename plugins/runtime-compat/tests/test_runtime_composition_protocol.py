from __future__ import annotations

import pytest

from pacthold_runtime_compat.runtime_composition import (
    FakeCompositionCoordinator, FakeHost, FakeSandbox, FakeTerminal,
    HarnessCommandSpec, RuntimeBinding, RuntimeHostRef, SandboxRef,
    TargetCreationSentinel, TerminalSessionRef, StartAmbiguous,
)


def make_stack(*, lose_response=False):
    affinity = "fake:linux:amd64"
    host_ref = RuntimeHostRef("fake-host", "host-1", "host-digest", affinity)
    sandbox_ref = SandboxRef("fake-sandbox", "sandbox-1", "policy-digest", affinity)
    terminal_ref = TerminalSessionRef("direct-stdio", "stdio-1", "terminal-digest", affinity)
    sentinel = TargetCreationSentinel()
    host = FakeHost(host_ref, sentinel, lose_response=lose_response)
    sandbox = FakeSandbox(sandbox_ref)
    terminal = FakeTerminal(terminal_ref, host)
    return FakeCompositionCoordinator(host, sandbox, terminal), sentinel, RuntimeBinding(host_ref, sandbox_ref, terminal_ref)


def test_resolve_assemble_wrap_allocate_do_not_spawn_and_run_is_entrypoint():
    coordinator, sentinel, binding = make_stack()
    host, sandbox, terminal = coordinator.resolve(binding)
    command = HarnessCommandSpec(("harness", "--once"), "cwd-token")
    bundle = coordinator.assemble(host, command, execution_id="e1", dispatch_id="d1")
    isolated = sandbox.wrap(bundle.mount_plan, command, attempt_key="attempt")
    allocation = terminal.allocate()
    assert sentinel.count == 0
    terminal.run(host, isolated, "attempt")
    assert sentinel.count == 1


def test_repeated_dispatch_reuses_handle_and_never_spawns_twice():
    coordinator, sentinel, binding = make_stack()
    command = HarnessCommandSpec(("harness",), "cwd-token")
    first = coordinator.start(binding, command, execution_id="e1", dispatch_id="d1")
    second = coordinator.start(binding, command, execution_id="e1", dispatch_id="d1")
    assert first == second
    assert sentinel.count == 1
    assert coordinator.ledger[first.attempt_key].target_creation_count <= 1


def test_response_loss_is_ambiguous_and_replay_does_not_start_again():
    coordinator, sentinel, binding = make_stack(lose_response=True)
    command = HarnessCommandSpec(("harness",), "cwd-token")
    with pytest.raises(StartAmbiguous):
        coordinator.start(binding, command, execution_id="e1", dispatch_id="d1")
    assert sentinel.count == 1
    with pytest.raises(StartAmbiguous):
        coordinator.start(binding, command, execution_id="e1", dispatch_id="d1")
    assert sentinel.count == 1


def test_all_three_refs_are_required_and_affinity_is_checked():
    coordinator, _, binding = make_stack()
    with pytest.raises(Exception):
        RuntimeBinding(binding.runtime_host_ref, binding.sandbox_ref, None)
    mismatched = RuntimeBinding(
        binding.runtime_host_ref, binding.sandbox_ref,
        TerminalSessionRef("direct-stdio", "stdio-2", "other", "other:realm"),
    )
    assert not coordinator.preflight(mismatched).accepted
