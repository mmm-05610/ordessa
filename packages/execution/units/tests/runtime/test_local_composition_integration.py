"""Real local v1 composition pairing under the Units coordinator.

This proves the exact integration the A4a risk was about: a real
``LocalCompositionProvider`` declares the semantic capabilities the coordinator
preflight requires, ``preflight`` accepts the exact host/sandbox binding, and
``start`` runs a real local process through ``stage`` -> ``wrap`` -> ``launch``
inside the real coordinator (not a fake).

Boundary: the full ``assemble_runtime_composition`` path additionally requires a
prepared-source registry on the resolved Sandbox port and a non-empty declared
projector plan with a cwd inside a declared guest target. The local composition
deliberately exposes neither (a local sandbox has no staging/mount step and
declares no sources), so this test drives the same coordinator seam directly
with the exact refs and an explicit empty ``MountPlan``.
"""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from ordessa_environments.composition import (
    CapabilityStatus,
    CompositionPreflightReceipt,
    MountPlan,
    RuntimeBinding,
    RuntimeBundle,
)
from ordessa_environments_local import LocalCompositionProvider
from ordessa_agents.harness.definitions.command_projection import HarnessCommandSpec
from ordessa_infrastructure.encoding.content_identity import digest
from ordessa_units.assembly.runtime.coordinator import (
    ResolvedComposition,
    RuntimeCompositionCoordinator,
)


def _coordinator(host, sandbox):
    """The real v1 coordinator over the real local host/sandbox ports."""
    binding = RuntimeBinding(host.ref, sandbox.ref)
    plan = MountPlan()

    def bundle_factory(resolved_host, command, execution_id: str, dispatch_id: str) -> RuntimeBundle:
        return RuntimeBundle(
            resolved_host.ref, plan, digest((execution_id, dispatch_id, command.digest))
        )

    def resolve(frozen: RuntimeBinding) -> ResolvedComposition:
        return ResolvedComposition(host, sandbox)

    return binding, RuntimeCompositionCoordinator(resolve, bundle_factory=bundle_factory)


def test_local_composition_declares_the_semantic_preflight_capabilities(tmp_path):
    provider = LocalCompositionProvider(root=str(tmp_path / "root"))
    for component in (provider.host, provider.sandbox):
        values = component.capabilities.values
        assert values["process.spawn.typed@1"] is CapabilityStatus.SUPPORTED
        assert values["isolation.wrap@1"] is CapabilityStatus.SUPPORTED
        # The managed keys stay declared alongside the semantic ones.
        for key in ("process", "byte-channel", "files", "stderr"):
            assert values[key] is CapabilityStatus.SUPPORTED
        assert values["terminal"] is CapabilityStatus.UNSUPPORTED

    binding, coordinator = _coordinator(provider.host, provider.sandbox)
    receipt = coordinator.preflight(binding)
    assert isinstance(receipt, CompositionPreflightReceipt)
    assert receipt.accepted is True
    assert receipt.rejection_code is None
    assert receipt.rejection_capability is None
    assert receipt.affinity == provider.host.ref.affinity


def test_preflight_refuses_a_component_with_undeclared_semantic_capabilities(tmp_path):
    """The accepted preflight is real: an undeclared component still refuses."""
    provider = LocalCompositionProvider(root=str(tmp_path / "root"))
    binding = RuntimeBinding(provider.host.ref, provider.sandbox.ref)
    _, coordinator = _coordinator(provider.host, provider.sandbox)
    undeclared_host = SimpleNamespace(ref=provider.host.ref, capabilities={})
    receipt = coordinator.preflight(
        binding, ResolvedComposition(undeclared_host, provider.sandbox)
    )
    assert receipt.accepted is False
    assert receipt.rejection_code == "CAPABILITY_UNDECLARED"
    assert receipt.rejection_capability == "process.spawn.typed@1"


def test_local_composition_start_runs_a_real_process_through_the_coordinator(tmp_path):
    provider = LocalCompositionProvider(root=str(tmp_path / "root"))
    binding, coordinator = _coordinator(provider.host, provider.sandbox)
    command = HarnessCommandSpec(
        (sys.executable, "-u", "-c", "import sys; sys.stdout.write('composed\\n'); sys.stdout.flush()"),
        "/",
        environment={"PATH": "/usr/bin:/bin"},
        projector_id="local-integration",
    )

    execution = coordinator.start(
        binding, command, execution_id="exec-local", dispatch_id="dispatch-local"
    )
    assert execution.preflight.accepted is True
    assert execution.host_ref == provider.host.ref
    assert execution.sandbox_ref == provider.sandbox.ref
    assert execution.staged_bundle.host_ref == provider.host.ref

    async def observe():
        output = bytearray()
        while True:
            chunk = await execution.handle.read_stdout(4096, timeout=10)
            if not chunk:
                break
            output.extend(chunk)
        return bytes(output), await execution.handle.wait_exit(timeout=10)

    output, observation = asyncio.run(observe())
    assert output == b"composed\n"
    assert observation.state == "exited"
    assert observation.exit_code == 0

    execution.handle.release()
    cleanup = coordinator.cleanup(execution.attempt_key)
    # Cleanup is a receipt, never an exit or compensation claim.
    assert cleanup["sandbox"]["exitClaimed"] is False
    assert "exitCode" not in cleanup["sandbox"]
    assert cleanup["host"]["compensationSupported"] is False
    assert cleanup["host"]["state"] == "no-op"
