"""Generic assembly of one frozen runtime composition.

This module is the only shared place that turns the Core Dispatch handoff and
a Harness projector's declared runtime sources into a RuntimeBundle.  It has
no knowledge of any resource contract (workspace/profile/credential), any
provider, or any guest path convention: the Harness projector owns the guest
layout and declares it verbatim; the assembler validates, registers and
assembles — fail closed, before any attempt starts — and only the Sandbox
sees the final MountPlan.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence
from ..credentials import PreparedSecretMount

from .coordinator import ResolvedComposition, RuntimeCompositionCoordinator
from .protocol import (
    HarnessCommandSpec, MountPlan, PreparedMountSource, RuntimeBinding,
    RuntimeBundle, RuntimeHostV1, SandboxV1, TerminalSessionV1, content_digest,
    digest, guest_path,
)


def assemble_runtime_composition(request: Any, command: HarnessCommandSpec, *, secret_mounts: Sequence[PreparedSecretMount] = ()) -> tuple[RuntimeBinding, RuntimeCompositionCoordinator]:
    """Assemble one exact, provider-neutral RuntimeBundle from a projector plan."""
    required = (RuntimeHostV1.contract_id, SandboxV1.contract_id, TerminalSessionV1.contract_id)
    values: dict[str, object] = {}
    for item in request.resolved_inputs:
        if item.contract_id not in required:
            continue
        if item.contract_id in values:
            raise ValueError(f"runtime composition input is not 1..1: {item.contract_id}")
        values[item.contract_id] = item.value
    if any(contract not in values for contract in required):
        raise ValueError("exact RuntimeHost, Sandbox and TerminalSession inputs are required")
    host, sandbox, terminal = (values[contract] for contract in required)
    if not isinstance(host, RuntimeHostV1) or not isinstance(sandbox, SandboxV1) or not isinstance(terminal, TerminalSessionV1):
        raise TypeError("runtime host, sandbox and terminal inputs must be typed ports")
    binding = RuntimeBinding(host.ref, sandbox.ref, terminal.ref)
    provider = getattr(sandbox, "provider", None)
    register = getattr(provider, "register_prepared_source", None)
    if not callable(register):
        raise ValueError("composition requires a prepared source registry on the resolved Sandbox port")

    # Validate and prepare the projector's declared plan exactly once, before
    # any attempt starts.  The Sandbox independently re-verifies each source
    # digest at wrap time (read-back), so assembly-time checks are the early,
    # fail-closed gate — never the only one.
    mounts = []
    seen_targets: set[str] = set()
    for source in command.runtime_sources:
        target = guest_path(source.guest_target)
        if target in seen_targets or any(target == prior or target.startswith(prior + "/") or prior.startswith(target + "/") for prior in seen_targets):
            raise ValueError(f"overlapping runtime guest targets: {target}")
        path = Path(source.source_path)
        actual = content_digest(path)
        if source.expected_digest != actual:
            raise ValueError(f"runtime source digest drift: {source.kind}")
        token = "projection:" + digest((source.kind, source.provenance, str(path), actual))
        register(token, path, authorized_scope=source.authorized_scope)
        mounts.append((PreparedMountSource(token, actual, source.provenance, source.authorized_scope), target, source.access))
        seen_targets.add(target)
    cwd = command.cwd_token
    if not cwd.startswith("/") or not any(cwd == target or cwd.startswith(target + "/") for target in seen_targets):
        raise ValueError("command cwd is not inside the declared guest filesystem")
    plan = MountPlan(tuple(mounts), secret_mounts=tuple(secret_mounts))

    def bundle_factory(resolved_host: object, _spec: HarnessCommandSpec, execution_id: str, dispatch_id: str) -> RuntimeBundle:
        return RuntimeBundle(resolved_host.ref, plan, digest((execution_id, dispatch_id, _spec.digest, tuple((m.guest_target, m.access, m.materialization_method) for m in secret_mounts))))

    def resolve(frozen: RuntimeBinding) -> ResolvedComposition:
        if frozen != binding:
            raise ValueError("runtime binding differs from frozen inputs")
        return ResolvedComposition(host.port, sandbox.port, terminal.port)

    return binding, RuntimeCompositionCoordinator(resolve, bundle_factory=bundle_factory)
