from __future__ import annotations
from pacthold_runtime_compat.runtime_composition import (
    HarnessCommandSpec, assemble_runtime_composition, declare_source,
)

def command_from_plan(plan, *, io_mode="stdio"):
    """Declare the Hermes guest layout; the Root assembler consumes it verbatim."""
    sources=[declare_source("workspace", plan.cwd, "/workspace", access="rw", provenance="workspace"),
             declare_source("profile-home", plan.home, "/runtime/home", access="rw", provenance="profile"),
             declare_source("executable", plan.executable, "/runtime/bin", access="ro", provenance="executable")]
    if plan.helper: sources.append(declare_source("helper", plan.helper, "/runtime/helpers", access="ro", provenance="helper"))
    return HarnessCommandSpec(("/runtime/bin/hermes",), "/workspace", {**plan.env, "HERMES_HOME":"/runtime/home"}, io_mode, runtime_sources=tuple(sources), projector_id="hermes")

def composition_from_resolved_inputs(request, command):
    """Hand the projector command and frozen resolved inputs to the one shared
    Root assembler.  There is no second assembly path."""
    if command is None:
        raise TypeError("Hermes composition requires the projector command")
    return assemble_runtime_composition(request, command)
