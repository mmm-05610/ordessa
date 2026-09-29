"""Registration-surface proofs: descriptors, owner validation, hello
availability, the dispatch shape wall, ports and the store start hook.

Every assertion here runs through the real `ServerPluginHost` activation
path (owner check, registry registration, contribution staging) and the
real `WireService.hello`/`dispatch` — the controlled proof the T09 dispatch
asks for, with no host file touched.
"""
from __future__ import annotations

import pytest
from service_helpers import AllowProbeAuthority, FakeSubmissionGate, Stack
from server_plugin_api import (
    InvalidDeclarationError,
    ServerMethodDescriptor,
    ServerPluginRegistration,
    WireError,
)

from backend.plugin import PLUGIN_ID, _PARAM_SHAPES, McpAssetServerPlugin

ALL_METHODS = set(_PARAM_SHAPES)


def _capabilities(stack):
    hello = stack.call("server.hello", clientVersions=["wire/1"],
                       clientPresentationSupports=["card"])
    return {entry["id"]: entry for entry in hello["capabilities"]}


def test_every_descriptor_is_atomic_owned_and_shape_declared(stack):
    descriptors = {d.method_id: d for d in stack.host.methods.descriptors()}
    assert ALL_METHODS <= set(descriptors)
    for method_id, descriptor in descriptors.items():
        if not method_id.startswith("mcp."):
            continue
        assert descriptor.owner == PLUGIN_ID, method_id
        required, optional = _PARAM_SHAPES[method_id]
        assert descriptor.required_params == required
        assert descriptor.optional_params == optional
        assert callable(descriptor.handler)


def test_descriptor_owner_mismatch_refuses_activation(tmp_path):
    """The host validates owner == descriptor.id at activation (host.py):
    a method owned by another plugin can never ride this registration."""
    from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost

    class Impostor(McpAssetServerPlugin):
        def build(self, context):
            registration = super().build(context)
            impostor = ServerMethodDescriptor(
                method_id="mcp.list",
                required_params=frozenset({"serverScope", "principal"}),
                optional_params=frozenset({"requestId"}),
                handler=lambda params: params, owner="ordessa.someone-else")
            return ServerPluginRegistration(
                methods=(impostor,) + tuple(
                    m for m in registration.methods if m.method_id != "mcp.list"),
                provided_ports=registration.provided_ports)

    host = ServerPluginHost(methods=MethodRegistry(), data_root=tmp_path)
    with pytest.raises(InvalidDeclarationError) as info:
        host.activate(Impostor())
    assert "owned by" in str(info.value)
    # the refused round registered nothing
    assert "mcp.list" not in host.methods.method_ids()


def test_hello_advertises_supported_and_planned_rows(stack):
    caps = _capabilities(stack)
    assert caps["mcp.list"]["supported"] is True
    assert caps["mcp.resolvePreview"]["supported"] is True
    # unwired-port rows: registered, honestly unsupported in hello...
    assert caps["mcp.probe"]["supported"] is False
    assert caps["mcp.probe"]["reason"] == "PROBE_AUTHORITY_UNWIRED"
    assert caps["mcp.planForSubmission"]["supported"] is False
    assert caps["mcp.planForSubmission"]["reason"] == "MCP_SUBMISSION_GATE_UNWIRED"
    # ...yet still dispatchable, as typed refusals (availability never
    # gates dispatch — order 097's two-question rule).
    stack.expect_refusal("mcp.probe", family="UNAVAILABLE",
                         internal_code="PERMISSION_AUTHORITY_ABSENT",
                         serverScope="s1", principal="alice",
                         definitionId="demo", revision=1)


def test_ports_present_flip_availability_to_supported(tmp_path):
    stack = Stack(tmp_path, host_ports={
        "permission.probe_authority": AllowProbeAuthority(),
        "harness.submission_gate": FakeSubmissionGate(),
    })
    caps = _capabilities(stack)
    assert caps["mcp.probe"]["supported"] is True
    assert caps["mcp.planForSubmission"]["supported"] is True


def test_provided_port_and_store_start_hook(stack):
    service = stack.host.provided_port("asset.mcp.v2")
    assert service is stack.plugin._service
    assert service is not None
    # start hook loaded the store layout under the data root (legacy-compatible
    # <root>/assets/mcp plus the domain's own assignment/managed tables);
    # the index file itself arrives with the first commit, the lock with the
    # first read — that is the store's own discipline, proven in T01/T02.
    assert (stack.root / "assets" / "mcp").is_dir()
    assert (stack.root / "assets" / "mcp" / ".lock").exists()
    assert (stack.root / "assets" / "assignments").is_dir()
    assert (stack.root / "assets" / "managed").is_dir()


def test_dispatch_shape_wall_rejects_missing_and_extra(stack):
    with pytest.raises(WireError) as info:
        stack.call("mcp.list")  # serverScope/principal missing
    assert info.value.family == "INVALID_REQUEST"
    assert "missing" in info.value.message
    with pytest.raises(WireError) as info:
        stack.call("mcp.list", serverScope="s1", principal="alice", hacker=True)
    assert "unexpected hacker" in info.value.message
    # requestId, when present, passes the host's own wall
    with pytest.raises(WireError) as info:
        stack.call("mcp.list", requestId="short", serverScope="s1", principal="alice")
    assert "requestId" in info.value.message
    answer = stack.call("mcp.list", requestId="req-list-0001",
                        serverScope="s1", principal="alice")
    assert answer == {"definitions": [], "nextCursor": None}


def test_error_family_contribution_answers_through_the_composition(stack):
    """MCP codes reach the wire through THIS host's aggregate: an MCP code
    resolves via the contributed row, and an unknown code keeps the
    documented fall-through — proving the contribution was committed."""
    families = stack.host.wire_error_families
    assert families.family_for("MCP_CAS_CONFLICT") == "CONFLICT_VERSION"
    assert families.family_for("APPLICATION_PORT_ABSENT") == "CAPABILITY_UNSUPPORTED"
    assert families.family_for("NO_SUCH_CODE_ANYWHERE") == "UNAVAILABLE"


def test_deactivation_retires_every_mcp_row(stack):
    stack.host.deactivate(PLUGIN_ID)
    for method_id in ALL_METHODS:
        assert stack.host.methods.lookup(method_id) is None
    assert stack.host.provided_port("asset.mcp.v2") is None
    with pytest.raises(WireError) as info:
        stack.call("mcp.list", serverScope="s1", principal="alice")
    assert "not a wire/1 method" in info.value.message
