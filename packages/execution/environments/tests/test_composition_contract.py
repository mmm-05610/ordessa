"""Protocol-level checks for the v1 runtime-composition surface.

These are contract-shape checks: the v1 launch seam exists and is additive, the
isolated spec validates exactly one representation with bounded strings, and the
v1 path names no terminal port at all (the retired terminal-session surface is
gone, not merely unused).
"""
from __future__ import annotations

import dataclasses
import inspect
from typing import get_type_hints

import pytest

import ordessa_environments.composition as composition
from ordessa_environments.composition import (
    IsolatedProcessSpec,
    ProcessHandle,
    Sandbox,
)
from ordessa_environments.definitions import runtime_ports, runtime_resources


def test_v1_sandbox_launch_seam_is_present_and_additive():
    assert tuple(inspect.signature(Sandbox.launch).parameters) == ("self", "spec", "attempt_key")
    assert get_type_hints(Sandbox.launch)["return"] is ProcessHandle
    # The pre-existing wrap shape is untouched.
    assert tuple(inspect.signature(Sandbox.wrap).parameters) == (
        "self", "mount_plan", "command", "attempt_key",
    )
    assert get_type_hints(Sandbox.wrap)["return"] is IsolatedProcessSpec
    assert getattr(Sandbox, "_is_protocol", False) is True
    assert getattr(Sandbox, "__runtime_protocol__", False) is False


def test_composition_surface_exposes_the_v1_types_consumers_need():
    for name in (
        "RuntimeHost", "Sandbox", "CommandInput", "MountPlanInput", "RuntimeBundleInput",
        "IsolatedProcessSpec", "ProcessHandle", "RuntimeHostRef", "SandboxRef", "CapabilitySet",
    ):
        assert hasattr(composition, name), name
        assert name in composition.__all__, name


def test_isolated_process_spec_requires_exactly_one_representation():
    local = IsolatedProcessSpec("token", "attempt", "sha256:spec", local_argv=("/bin/echo",))
    remote = IsolatedProcessSpec("token", "attempt", "sha256:spec", provider_transport="remote")
    assert local.local_argv == ("/bin/echo",) and local.provider_transport is None
    assert remote.provider_transport == "remote" and remote.local_argv is None

    with pytest.raises(ValueError):
        IsolatedProcessSpec("token", "attempt", "sha256:spec")
    with pytest.raises(ValueError):
        IsolatedProcessSpec("token", "attempt", "sha256:spec", local_argv=("/bin/echo",),
                            provider_transport="remote")


def test_isolated_process_spec_carries_no_local_launch_facts():
    """The frozen public projection exposes identity and representation only.

    Local launch facts (the absolute cwd and the built environment mapping) are
    provider-private: they stay with the provider that wrapped the request and
    must neither appear on, nor be accepted by, the public spec.
    """
    spec = IsolatedProcessSpec("token", "attempt", "sha256:spec", local_argv=("/bin/echo",))
    assert tuple(field.name for field in dataclasses.fields(spec)) == (
        "spawn_token", "attempt_key", "spec_digest", "io_mode",
        "local_argv", "provider_transport", "carrier_argv",
    )
    for private in ("cwd", "env", "environment"):
        assert not hasattr(spec, private), private
        with pytest.raises(TypeError):
            IsolatedProcessSpec("token", "attempt", "sha256:spec",
                                local_argv=("/bin/echo",), **{private: "leak"})


def test_v1_launch_path_names_no_terminal_session_surface():
    # The v1 sandbox seam carries only ref/capabilities/resolve/wrap/launch/cleanup.
    v1_members = {name for name in vars(Sandbox) if not name.startswith("_")}
    assert v1_members == {"ref", "capabilities", "resolve", "wrap", "launch", "cleanup"}
    for terminal_verb in ("allocate", "run", "release"):
        assert not hasattr(Sandbox, terminal_verb), terminal_verb

    # The v1 surface names no terminal type, and the retired port and resource
    # names are gone from `definitions` rather than kept as aliases.
    for legacy_name in ("TerminalSession", "TerminalRunHandle", "TerminalAllocation",
                        "TerminalSessionRef"):
        assert not hasattr(composition, legacy_name), legacy_name
    for retired in ("TerminalSession", "TerminalSessionProvider"):
        assert not hasattr(runtime_ports, retired), retired
    for retired in ("TERMINAL_SESSION_CONTRACT_ID", "TerminalSessionRef", "TerminalSessionV1",
                    "TerminalAllocation", "AttachDescriptor", "TerminalRunHandle"):
        assert not hasattr(runtime_resources, retired), retired
