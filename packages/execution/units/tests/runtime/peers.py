"""In-memory conformance fakes for the v1 runtime composition protocol.

The v1 seam has no terminal: ``FakeSandbox.launch`` is the single effectful
call and owns the returned process handle. The attempt-key check, the
single-use spawn-token fuse and the target-creation sentinel therefore live at
the launch seam itself, and the host has no transport to submit to.
"""
from __future__ import annotations

from typing import Mapping

from ordessa_environments.composition import (
    CapabilityStatus,
    CompositionErrorCode,
    CompositionRejected,
    IsolatedProcessSpec,
    MountPlan,
    RuntimeBinding,
    RuntimeBundle,
    StartAmbiguous,
)
from ordessa_environments.definitions.runtime_resources import (
    CapabilitySet,
    RuntimeHostRef,
    SandboxRef,
)
from ordessa_infrastructure.encoding.content_identity import digest

from ordessa_units.assembly.runtime.coordinator import (
    ResolvedComposition,
    RuntimeCompositionCoordinator,
)


class TargetCreationSentinel:
    def __init__(self) -> None:
        self.count = 0


class FakeProcessHandle:
    """Minimal managed-process stand-in: identity plus an honest release."""

    def __init__(self, identity: str) -> None:
        self.identity = identity
        self.released = 0

    def release(self) -> Mapping[str, object]:
        self.released += 1
        return {"released": True, "exitClaimed": False, "handle": self.identity}


class FakeHost:
    def __init__(self, ref: RuntimeHostRef) -> None:
        self.ref = ref
        self.transport = self
        self.capabilities = CapabilitySet(
            {"process.spawn.typed@1": CapabilityStatus.SUPPORTED}, affinity=ref.affinity,
        )
        self.staged: list[object] = []
        self.cleaned: list[str | None] = []

    def resolve(self, ref: RuntimeHostRef) -> "FakeHost":
        if ref != self.ref:
            raise ValueError("host ref mismatch")
        return self

    def stage(self, bundle: RuntimeBundle) -> RuntimeBundle:
        if getattr(bundle, "host_ref", None) != self.ref:
            raise CompositionRejected(CompositionErrorCode.INVALID_BINDING, "bundle host ref mismatch")
        self.staged.append(bundle)
        return bundle

    def submit(self, operation: object) -> str:
        raise CompositionRejected(
            CompositionErrorCode.CAPABILITY_UNSUPPORTED, "fake host exposes no host transport",
        )

    def terminate(self, op: object) -> object:
        raise CompositionRejected(
            CompositionErrorCode.CAPABILITY_UNSUPPORTED, "fake host provides no compensation",
        )

    def cleanup(self, execution_id: str | None = None) -> Mapping[str, object]:
        self.cleaned.append(execution_id)
        return {"state": "no-op", "exitClaimed": False, "execution": execution_id}


class FakeSandbox:
    def __init__(self, ref: SandboxRef, sentinel: TargetCreationSentinel,
                 *, lose_response: bool = False) -> None:
        self.ref = ref
        self.sentinel = sentinel
        self.lose_response = lose_response
        self.capabilities = CapabilitySet(
            {"isolation.wrap@1": CapabilityStatus.SUPPORTED}, affinity=ref.affinity,
        )
        self._consumed_tokens: set[str] = set()
        self.cleaned: list[object] = []

    def resolve(self, ref: SandboxRef) -> "FakeSandbox":
        if ref != self.ref:
            raise ValueError("sandbox ref mismatch")
        return self

    def wrap(self, mount_plan: MountPlan, command, *, attempt_key: str) -> IsolatedProcessSpec:
        return IsolatedProcessSpec(
            "token:" + attempt_key, attempt_key,
            digest((mount_plan.digest, command.digest)), local_argv=tuple(command.argv),
        )

    def launch(self, spec: IsolatedProcessSpec, *, attempt_key: str) -> FakeProcessHandle:
        if spec.attempt_key != attempt_key:
            raise CompositionRejected(
                CompositionErrorCode.ATTEMPT_REPLAY, "launch attempt key does not match the wrapped spec",
            )
        if spec.spawn_token in self._consumed_tokens:
            raise CompositionRejected(
                CompositionErrorCode.SPAWN_TOKEN_INVALID, "single-use token replay",
            )
        self._consumed_tokens.add(spec.spawn_token)
        self.sentinel.count += 1
        if self.lose_response:
            raise StartAmbiguous("native response lost")
        return FakeProcessHandle("native:" + digest((spec.spec_digest, attempt_key))[:24])

    def cleanup(self, spec: IsolatedProcessSpec) -> Mapping[str, object]:
        self.cleaned.append(spec)
        return {
            "specDigest": spec.spec_digest,
            "attemptKey": spec.attempt_key,
            "exitClaimed": False,
            "state": "no-op",
        }


def coordinator_for(host: FakeHost, sandbox: FakeSandbox, *, plan: MountPlan | None = None) -> tuple[RuntimeBinding, RuntimeCompositionCoordinator]:
    """Build the real v1 coordinator over the in-memory provider fakes."""
    binding = RuntimeBinding(host.ref, sandbox.ref)
    frozen_plan = plan if plan is not None else MountPlan()

    def bundle_factory(resolved_host: object, command, execution_id: str, dispatch_id: str) -> RuntimeBundle:
        return RuntimeBundle(resolved_host.ref, frozen_plan, digest((execution_id, dispatch_id, command.digest)))

    def resolve(frozen: RuntimeBinding) -> ResolvedComposition:
        return ResolvedComposition(host, sandbox)

    return binding, RuntimeCompositionCoordinator(resolve, bundle_factory=bundle_factory)
