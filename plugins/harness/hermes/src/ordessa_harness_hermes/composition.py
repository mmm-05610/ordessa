"""Hermes guest-layout declaration (brand projector knowledge).

This module declares how a resolved Hermes launch plan maps to guest argv,
environment and runtime sources. It performs no assembly and starts nothing:
the retired shared assembler seam
(``pacthold_runtime_compat.runtime_composition``) this module once called into
is deleted, and there is no second runtime coordinator. The single composition
authority lives outside this brand package.
"""
from __future__ import annotations
from ordessa_execution_api.environment.runtime_composition import (
    HarnessCommandSpec, declare_source,
)

def command_from_plan(plan, *, io_mode="stdio"):
    """Declare the Hermes guest layout; the Root assembler consumes it verbatim."""
    sources=[declare_source("workspace", plan.cwd, "/workspace", access="rw", provenance="workspace"),
             declare_source("profile-home", plan.home, "/runtime/home", access="rw", provenance="profile"),
             declare_source("executable", plan.executable, "/runtime/bin", access="ro", provenance="executable")]
    if plan.helper: sources.append(declare_source("helper", plan.helper, "/runtime/helpers", access="ro", provenance="helper"))
    return HarnessCommandSpec(("/runtime/bin/hermes",), "/workspace", {**plan.env, "HERMES_HOME":"/runtime/home"}, io_mode, runtime_sources=tuple(sources), projector_id="hermes")
