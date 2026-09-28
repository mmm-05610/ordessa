"""In-memory conformance fake for the runtime composition protocol."""
from __future__ import annotations

from typing import Dict

from .protocol import (
    CapabilitySet, CompositionAttemptRecord, CompositionPreflightReceipt,
    IsolatedProcessSpec, MountPlan, RuntimeBinding, RuntimeBundle, RuntimeHost,
    RuntimeHostRef, Sandbox, SandboxRef, TerminalAllocation, TerminalRunHandle,
    TerminalSession, TerminalSessionRef, attempt_key, digest, StartAmbiguous,
    CapabilityStatus, CompositionRejected, CompositionErrorCode,
)


class TargetCreationSentinel:
    def __init__(self) -> None:
        self.count = 0


class FakeHost:
    def __init__(self, ref: RuntimeHostRef, sentinel: TargetCreationSentinel, *, lose_response: bool = False) -> None:
        self.ref, self.sentinel, self.lose_response = ref, sentinel, lose_response
        self.transport = self
        self._consumed_tokens: set[str] = set()
        self.capabilities = CapabilitySet({"process.spawn.typed@1": CapabilityStatus.SUPPORTED}, affinity=ref.affinity)

    def resolve(self, ref: RuntimeHostRef) -> "FakeHost":
        if ref != self.ref:
            raise ValueError("host ref mismatch")
        return self

    def stage(self, bundle: RuntimeBundle) -> RuntimeBundle:
        return bundle

    def submit(self, operation: object) -> str:
        token = operation["spawn_token"]
        if token in self._consumed_tokens:
            raise CompositionRejected(CompositionErrorCode.SPAWN_TOKEN_INVALID, "single-use token replay")
        self._consumed_tokens.add(token)
        self.sentinel.count += 1
        if self.lose_response:
            raise StartAmbiguous("native response lost")
        return "native:" + digest(operation)[:24]


class FakeSandbox:
    def __init__(self, ref: SandboxRef) -> None:
        self.ref = ref
        self.capabilities = CapabilitySet({"isolation.wrap@1": CapabilityStatus.SUPPORTED}, affinity=ref.affinity)

    def resolve(self, ref: SandboxRef) -> "FakeSandbox":
        if ref != self.ref:
            raise ValueError("sandbox ref mismatch")
        return self

    def wrap(self, mount_plan: MountPlan, command, *, attempt_key: str) -> IsolatedProcessSpec:
        return IsolatedProcessSpec("token:" + attempt_key, attempt_key, digest((mount_plan.digest, command.digest)), local_argv=command.argv)


class FakeTerminal:
    def __init__(self, ref: TerminalSessionRef, host: FakeHost) -> None:
        self.ref, self.host = ref, host
        self.capabilities = CapabilitySet({"terminal.run@1": CapabilityStatus.SUPPORTED}, affinity=ref.affinity)
        self.allocations = 0
        self._allocation = None

    def resolve(self, ref: TerminalSessionRef) -> "FakeTerminal":
        if ref != self.ref:
            raise ValueError("terminal ref mismatch")
        return self

    def allocate(self) -> TerminalAllocation:
        self.allocations += 1
        self._allocation = TerminalAllocation("allocation:" + str(self.allocations), self.ref, "allocation-digest")
        return self._allocation

    def run(self, host_transport, spec, attempt_key) -> TerminalRunHandle:
        allocation = self._allocation
        if allocation is None:
            raise RuntimeError("allocate must precede run")
        native = host_transport.submit({"spec_digest": spec.spec_digest, "attempt_key": attempt_key, "spawn_token": spec.spawn_token})
        return TerminalRunHandle(attempt_key, native, "running", allocation.allocation_id)


class FakeCompositionCoordinator:
    def __init__(self, host: FakeHost, sandbox: FakeSandbox, terminal: FakeTerminal) -> None:
        self.host, self.sandbox, self.terminal = host, sandbox, terminal
        self.ledger: Dict[str, CompositionAttemptRecord] = {}

    def resolve(self, binding: RuntimeBinding) -> tuple[FakeHost, FakeSandbox, FakeTerminal]:
        return self.host.resolve(binding.runtime_host_ref), self.sandbox.resolve(binding.sandbox_ref), self.terminal.resolve(binding.terminal_session_ref)

    def assemble(self, host: FakeHost, command, *, execution_id: str, dispatch_id: str) -> RuntimeBundle:
        return RuntimeBundle(host.ref, MountPlan(), digest((execution_id, dispatch_id, command.digest)))

    def preflight(self, binding: RuntimeBinding) -> CompositionPreflightReceipt:
        if not (binding.runtime_host_ref.affinity == binding.sandbox_ref.affinity == binding.terminal_session_ref.affinity):
            return CompositionPreflightReceipt(digest(binding), digest("rejected"), False, binding.runtime_host_ref.affinity, "AFFINITY_MISMATCH")
        return CompositionPreflightReceipt(digest(binding), digest("accepted"), True, binding.runtime_host_ref.affinity)

    def start(self, binding: RuntimeBinding, command, *, execution_id: str, dispatch_id: str) -> TerminalRunHandle:
        preflight = self.preflight(binding)
        if not preflight.accepted:
            raise CompositionRejected(CompositionErrorCode.AFFINITY_MISMATCH, preflight.rejection_code or "")
        host, sandbox, terminal = self.resolve(binding)
        bundle = self.assemble(host, command, execution_id=execution_id, dispatch_id=dispatch_id)
        key = attempt_key(execution_id=execution_id, dispatch_id=dispatch_id, ref_digests=(binding.runtime_host_ref.identity_digest, binding.sandbox_ref.policy_digest, binding.terminal_session_ref.session_digest), preflight_digest=preflight.capability_digest, bundle_digest=bundle.bundle_digest, command_digest=command.digest, mount_plan_digest=bundle.mount_plan.digest)
        prior = self.ledger.get(key)
        if prior:
            if prior.state == "AMBIGUOUS":
                raise StartAmbiguous("replay remains ambiguous")
            return TerminalRunHandle(key, prior.native_correlation or "", prior.state.lower(), "allocation:1")
        isolated = sandbox.wrap(bundle.mount_plan, command, attempt_key=key)
        allocation = terminal.allocate()
        self.ledger[key] = CompositionAttemptRecord(key, "RUN_INTENT_RECORDED")
        try:
            handle = terminal.run(host, isolated, key)
        except StartAmbiguous:
            self.ledger[key] = CompositionAttemptRecord(key, "AMBIGUOUS", True, 1)
            raise
        self.ledger[key] = CompositionAttemptRecord(key, "RUNNING", True, 1, handle.native_correlation)
        return handle
