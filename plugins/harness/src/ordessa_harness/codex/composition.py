"""Codex-only projection into the public runtime composition port.

This module deliberately has no knowledge of a host, sandbox, terminal, or
their implementations.  The Codex projector owns the guest layout and
declares it as typed runtime sources (workspace, profile overlay, executable,
helpers, credential target); the single Root generic assembler consumes that
plan verbatim — there is no second assembly path.
"""
from __future__ import annotations

from typing import Any
from pathlib import Path

from pacthold_runtime_compat.runtime_composition import (
    CompositionCoordinator,
    HarnessCommandSpec,
    RuntimeBinding,
    RuntimeCompositionCoordinator,
    SandboxV1,
    TerminalRunHandle,
    assemble_runtime_composition,
    declare_source,
)
from pacthold_runtime_compat.resource_contracts import CredentialRefV1


def command_from_plan(plan: Any, *, execution_id: str, io_mode: str,
                      requires_control_plane_network: bool = False) -> HarnessCommandSpec:
    """Project a Codex launch plan without exposing local paths publicly."""
    environment = {
        str(key): f"execution-overlay:{execution_id}:{key}"
        if key == "CODEX_HOME" else str(value)
        for key, value in dict(getattr(plan, "env", {})).items()
        if str(key).isidentifier() and str(key).upper() == str(key)
    }
    if "CODEX_HOME" in environment:
        # The projection is represented by the mounted execution workspace in
        # the runtime boundary; host projection paths never enter the guest.
        environment["CODEX_HOME"] = "/runtime/home"
    # A bounded, non-secret execution identity lets provider-owned offline
    # harnesses distinguish continuation executions without exposing host
    # paths or relying on PATH lookup.
    environment["AGENT_BOX_EXECUTION_ID"] = str(execution_id)
    raw_argv = [str(value) for value in plan.argv]
    executable_source = raw_argv[0]
    raw_argv[0] = "/runtime/bin/codex"
    # Hook invocation is projected into the guest; host interpreter/module
    # paths never cross the sandbox boundary.
    for index, value in enumerate(raw_argv):
        if "ordessa_harness.codex.hooks" in value:
            raw_argv[index] = value.replace("ordessa_harness.codex.hooks", "runpy.run_path('/runtime/hooks/session-start')")
            if index > 0: raw_argv[index - 1] = "/usr/bin/python3"
    argv = tuple(raw_argv)
    projection = getattr(plan, "projection_directory", None)
    hooks = (Path(projection).parent / (Path(projection).name + "-hooks")) if projection else None
    # The Codex projector owns the guest layout: the frozen workspace mounts
    # read-write at the Codex cwd, the profile overlay at CODEX_HOME, the
    # executable and helpers read-only.  These are Codex decisions only.
    sources = [declare_source("workspace", plan.cwd, "/workspace", access="rw", provenance="workspace")]
    if projection:
        sources.append(declare_source("profile-home", str(projection), "/runtime/home", access="rw", provenance="profile"))
    bundle = getattr(plan, "executable_bundle", None)
    if bundle is not None:
        sources.extend(bundle.runtime_sources())
    elif executable_source:
        sources.append(declare_source("executable", executable_source, "/runtime/bin/codex", access="ro", provenance="executable"))
    if hooks:
        sources.append(declare_source("helper", str(hooks), "/runtime/hooks", access="ro", provenance="helper"))
    return HarnessCommandSpec(
        argv=argv,
        # The command carries a guest cwd token.  Host-side paths are staged
        # and mounted by the composition bundle factory, never persisted here.
        cwd_token="/workspace",
        environment=environment,
        io_mode=io_mode,
        requires_control_plane_network=requires_control_plane_network,
        runtime_sources=tuple(sources),
        projector_id="codex",
    )


def compose(coordinator: CompositionCoordinator | None, binding: RuntimeBinding | None,
            command: HarnessCommandSpec, *, execution_id: str,
            dispatch_id: str) -> TerminalRunHandle:
    if coordinator is None or binding is None:
        raise RuntimeError("Codex Harness requires an injected RuntimeCompositionCoordinator and exact RuntimeBinding")
    return coordinator.start(binding, command, execution_id=execution_id,
                            dispatch_id=dispatch_id)


def composition_from_resolved_inputs(request: Any, command: HarnessCommandSpec, *, credential_materializer=None) -> tuple[RuntimeBinding, RuntimeCompositionCoordinator]:
    """Hand the projector command and frozen resolved inputs to the one shared
    Root assembler.  Registry resolution happened in Core before the provider
    received this request; the values here are the exact Ref-to-port handoff
    for this Dispatch only.  There is no fallback assembly path."""
    if command is None:
        raise TypeError("Codex composition requires the projector command")
    return assemble_runtime_composition(
        request, command,
        secret_mounts=_prepare_credential_mount(request, credential_materializer),
    )


def _prepare_credential_mount(request, materializer, sandbox=None):
    values = request.inputs.get(CredentialRefV1.contract_id, ())
    if len(values) > 1:
        raise ValueError("credential binding must be 0..1")
    if not values:
        return ()
    if materializer is None:
        raise ValueError("Codex credential materializer is unavailable")
    ref = values[0]
    if not isinstance(ref, CredentialRefV1):
        raise TypeError("credential input is not a typed CredentialRefV1")
    prepared = materializer.prepare_mount(ref, "execution:" + request.execution_id, "/runtime/home/auth.json", "ro")
    if sandbox is None:
        by_contract = {i.contract_id: i.value for i in request.resolved_inputs}
        sandbox = by_contract[SandboxV1.contract_id]
        if not isinstance(sandbox, SandboxV1):
            raise TypeError("Registry did not return a resolved Sandbox port")
    materializer.bind_to_sandbox(prepared, sandbox)
    return (prepared,)
