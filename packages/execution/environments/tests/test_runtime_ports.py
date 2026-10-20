import inspect
import ast
from typing import get_type_hints

import pytest

from ordessa_environments.definitions import runtime_ports
from ordessa_environments.definitions.runtime_resources import IsolatedProcessSpec


def test_provider_ports_keep_original_methods_and_environment_owned_results():
    assert tuple(inspect.signature(runtime_ports.RuntimeHost.stage).parameters) == ("self", "bundle")
    assert tuple(inspect.signature(runtime_ports.Sandbox.wrap).parameters) == (
        "self", "mount_plan", "command", "attempt_key",
    )
    assert get_type_hints(runtime_ports.Sandbox.wrap)["return"] is IsolatedProcessSpec

    assert get_type_hints(runtime_ports.RuntimeHost.resolve)["ref"].__name__ == "RuntimeHostRef"
    assert get_type_hints(runtime_ports.Sandbox.resolve)["ref"].__name__ == "SandboxRef"


def test_cross_owner_inputs_are_read_only_protocol_views():
    fields = (
        (runtime_ports.MountPlanInput, ("mounts", "tmpfs_targets", "plan_digest", "secret_mounts", "digest")),
        (runtime_ports.RuntimeBundleInput, ("host_ref", "mount_plan", "bundle_digest", "staging_tokens")),
        (runtime_ports.CommandInput, ("argv", "cwd_token", "environment", "io_mode", "command_digest",
                                      "runtime_sources", "requires_control_plane_network",
                                      "tool_network_requirement", "projector_id", "digest")),
        (runtime_ports.TransportOperationInput, ("attempt_key", "spawn_token", "spec_digest",
                                                 "transport_kind", "sealed_payload")),
    )
    for view, properties in fields:
        assert getattr(view, "_is_protocol", False)
        assert all(isinstance(inspect.getattr_static(view, name), property) for name in properties)

    assert getattr(runtime_ports.HostTransportInput, "_is_protocol", False)
    for view in (runtime_ports.RuntimeHost, runtime_ports.Sandbox,
                 runtime_ports.RuntimeHostProvider, runtime_ports.SandboxProvider):
        assert getattr(view, "_is_protocol", False)


def test_terminal_session_ports_are_retired():
    """The v1 seam names no terminal port; the retired names are not aliased."""
    for retired in ("TerminalSession", "TerminalSessionProvider"):
        assert retired not in vars(runtime_ports), retired
        with pytest.raises(AttributeError):
            getattr(runtime_ports, retired)
    with pytest.raises(ImportError):
        from ordessa_environments.definitions.runtime_ports import TerminalSession  # noqa: F401


def test_protocols_have_no_foreign_owner_imports_or_new_transport_translation():
    source = inspect.getsource(runtime_ports)
    assert "ordessa_execution_api" not in source
    assert "ordessa_execution_agents" not in source
    assert "ordessa_units" not in source
    def constructed_protocols(text):
        return {node.func.id for node in ast.walk(ast.parse(text))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"HostTransportOperation", "CommandInput"}}
    assert not constructed_protocols(source)
    assert constructed_protocols("value = CommandInput()") == {"CommandInput"}
