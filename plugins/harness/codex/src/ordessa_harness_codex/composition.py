"""Codex-only guest-layout declaration (no assembly path).

This module projects a Codex launch plan into a typed
``HarnessCommandSpec`` (guest argv, cwd token, environment, runtime sources).
It starts or coordinates no runtime: the legacy second coordinator
(``pacthold_runtime_compat.runtime_composition`` assembler/coordinator/fake)
is retired with no successor in this round, so this declaration currently
has no consumer.  Contract types come from the neutral port
``ordessa_execution_api.environment.runtime_composition``.
"""
from __future__ import annotations

from typing import Any
from pathlib import Path

from ordessa_execution_api.environment.runtime_composition import (
    HarnessCommandSpec,
    declare_source,
)


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
        if "ordessa_harness_codex.hooks" in value:
            raw_argv[index] = value.replace("ordessa_harness_codex.hooks", "runpy.run_path('/runtime/hooks/session-start')")
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
