"""T10 remaining cell: the ``mcp.probe`` WIRE combination over the real
ServerPluginHost dispatch face (tests/service precedent) with the REAL probe
transport (``backend.probe`` default runner, no injection) against
millisecond-level loopback fakes.

Closes specs/011-q4-mcp/reports/t10-integration.md §五.3 ("mcp.probe 的
wire+真 transport+probe_authority 组合格"): t03 proved the transport at the
domain layer, tests/service proved the wire row with an injected double — the
combination (wire envelope → registration shape wall → permission gate →
store read → real handshake transport → graded facts / typed refusal mapping)
was the open cell.

Discipline: transport cells request ``contract_primitives`` (the tests/probe
lifting precedent) — every other cell here runs under the package-wide
socket/Popen lockdown, so "the refusal happened before any transport" is
proven by the harness itself, not by a mock book. All endpoints are
127.0.0.1/stdio-pipe fakes; nothing leaves the machine; no model, no cost.
"""
from __future__ import annotations

import sys

import pytest

from backend.probe_policy import ProbePolicy
from contract_helpers import (
    FAKE_STDIO_SERVER,
    AllowProbeAuthority,
    DenyProbeAuthority,
    LoopbackHttpFake,
    Stack,
    remote_definition,
    seed,
    stdio_definition,
)

GRADED_FACT_KEYS = {"status", "transport", "evidence", "serverInfo",
                    "protocolVersion", "negotiation", "credentialScope",
                    "credentialsExcluded", "proves", "doesNotProve"}


def stdio_stack(tmp_path, authority=None):
    ports = {}
    if authority is not None:
        ports["permission.probe_authority"] = authority
    return Stack(tmp_path, host_ports=ports)


def test_pcp01_probe_stdio_full_chain_graded_facts(tmp_path, contract_primitives):
    """PCP-01: legal stdio definition, wire → real probe transport (fake
    loopback server, ms-level) → graded facts with the six-tier semantics."""
    authority = AllowProbeAuthority()
    stack = stdio_stack(tmp_path, authority)
    definition = stdio_definition(name="demo", command=sys.executable,
                                  args=[str(FAKE_STDIO_SERVER)],
                                  env={"TOKEN": {"secretRef": "cred-1"},
                                       "LIT": "visible"})
    seed(stack, definition=definition)
    answer = stack.call("mcp.probe", serverScope="s1", principal="alice",
                        definitionId="demo", revision=1)
    # the envelope the wire row answers with (service.probe's own wrapper)
    assert set(answer) == {"definitionId", "revision", "probe"}, answer
    assert answer["definitionId"] == "demo" and answer["revision"] == 1
    facts = answer["probe"]
    # the graded FR-02 fact keys, exactly and completely (no catalog, no
    # credential verdict, no connection claim — the six-tier ladder level 3)
    assert set(facts) == GRADED_FACT_KEYS, sorted(facts)
    assert facts["status"] == "ok"
    assert facts["transport"] == "stdio"
    assert facts["evidence"] == "initialize-handshake"
    assert facts["proves"] == ["initialize-handshake"]
    assert facts["doesNotProve"] == ["tool-catalog", "credential-usability",
                                     "connection-lease", "tool-invocability"]
    assert facts["credentialScope"] == "unproven"
    # the secretRef env entry is EXCLUDED and reported, never resolved
    assert facts["credentialsExcluded"] == ["TOKEN"], facts
    assert facts["serverInfo"] == {"name": "contract-fake-stdio", "version": "0.1"}
    assert facts["protocolVersion"] == "2025-11-25"
    assert facts["negotiation"]["negotiated"] == "2025-11-25"
    assert facts["negotiation"]["requested"] == "2025-11-25"
    # the fake stuffs a tools[] into the initialize answer: a handshake probe
    # must ignore it (verification.md counterexample 8, proven at the wire face)
    assert "tools" not in facts
    # the authority saw exactly the bound the wire carried
    assert authority.calls == [("alice", "s1", "demo", 1)]


def test_pcp02_probe_wire_shape_wall_refuses_every_malformed_request(tmp_path):
    """PCP-02: the registration-face param validation, all counterexamples.

    The shape wall is the host dispatch (`missing`/`unexpected` == the
    descriptor sets); none of these reaches the store, the authority or a
    transport (the lockdown covers the whole cell: no primitives requested).
    """
    authority = AllowProbeAuthority()
    stack = stdio_stack(tmp_path, authority)
    seed(stack)
    base = {"serverScope": "s1", "principal": "alice", "definitionId": "demo",
            "revision": 1}
    for missing in ("serverScope", "principal", "definitionId", "revision"):
        params = {k: v for k, v in base.items() if k != missing}
        error = stack.expect_refusal("mcp.probe", family="INVALID_REQUEST", **params)
        assert f"missing {missing}" in error.message, error.message
    error = stack.expect_refusal("mcp.probe", serverScope="s1", principal="alice",
                                 definitionId="demo", revision="1",
                                 family="INVALID_REQUEST")
    assert "non-negative safe integer" in error.message
    error = stack.expect_refusal("mcp.probe", serverScope="s1", principal="alice",
                                 definitionId=7, revision=1, family="INVALID_REQUEST")
    assert "definitionId must be a bounded string" in error.message
    error = stack.expect_refusal("mcp.probe", family="INVALID_REQUEST",
                                 **base, notAParam=True)
    assert "unexpected notAParam" in error.message
    # shape refusal: the authority was never asked (only seed's save/approve ran)
    assert authority.calls == []


def test_pcp02b_probe_missing_definition_is_a_typed_not_found(tmp_path):
    """PCP-02b: a well-shaped probe for a definition that does not exist
    (「缺 definition」) answers NOT_FOUND `MCP_ASSET_MISSING: …` — no transport."""
    stack = stdio_stack(tmp_path, AllowProbeAuthority())
    stack.expect_refusal("mcp.probe", family="NOT_FOUND",
                         internal_code="MCP_ASSET_MISSING",
                         serverScope="s1", principal="alice",
                         definitionId="never-saved", revision=1)


def test_pcp03_probe_gate_is_a_wire_visible_refusal(tmp_path):
    """PCP-03: authority absent → PERMISSION_AUTHORITY_ABSENT (UNAVAILABLE);
    authority denies → PERMISSION_REFUSED (FORBIDDEN). Both before any
    transport — under the lockdown, a spawn attempt would die, and it does
    not (both refusals carry the domain's `{code}: {message}` text)."""
    stack = Stack(tmp_path)  # no probe_authority port
    seed(stack)
    stack.expect_refusal("mcp.probe", family="UNAVAILABLE",
                         internal_code="PERMISSION_AUTHORITY_ABSENT",
                         serverScope="s1", principal="alice",
                         definitionId="demo", revision=1)
    denied = stdio_stack(tmp_path / "denied", DenyProbeAuthority())
    seed(denied)
    error = denied.expect_refusal("mcp.probe", family="FORBIDDEN",
                                  internal_code="PERMISSION_REFUSED",
                                  serverScope="s1", principal="alice",
                                  definitionId="demo", revision=1)
    assert error.message.startswith("PERMISSION_REFUSED: "), error.message


def test_pcp04_probe_remote_definition_via_loopback_http_wire(tmp_path,
                                                              contract_primitives):
    """PCP-04: remote definition, real probe_http against a 127.0.0.1 fake.
    The server-side witness proves the wire probe carried NO credential; the
    declared secretRef header is reported excluded with scope unproven."""
    with LoopbackHttpFake(mode="ok") as fake:
        authority = AllowProbeAuthority()
        stack = stdio_stack(tmp_path, authority)
        seed(stack, definition_id="remote-demo",
             definition=remote_definition(name="remote-demo", url=fake.url,
                                         headers={"Authorization":
                                                  {"secretRef": "cred-9"}}))
        answer = stack.call("mcp.probe", serverScope="s1", principal="alice",
                            definitionId="remote-demo", revision=1)
        facts = answer["probe"]
        assert set(facts) == GRADED_FACT_KEYS, sorted(facts)
        assert facts["transport"] == "remote"
        assert facts["status"] == "ok"
        assert facts["credentialScope"] == "unproven"
        assert facts["credentialsExcluded"] == ["Authorization"]
        assert facts["serverInfo"] == {"name": "contract-http-fake",
                                       "version": "0.3"}
        assert facts["protocolVersion"] == "2025-11-25"
    # exactly one request reached the fake, and it carried no credential header
    assert len(fake.witnesses) == 1, fake.witnesses
    sent_headers = {k.lower() for k in fake.witnesses[0]["headers"]}
    assert "authorization" not in sent_headers, sorted(sent_headers)
    assert '"initialize"' in fake.witnesses[0]["body"]
    assert authority.calls == [("alice", "s1", "remote-demo", 1)]


def test_pcp05a_spawn_failure_keeps_its_typed_code_through_the_wire(tmp_path,
                                                                     contract_primitives):
    """PCP-05a: PROBE_SPAWN_FAILED travels as `{code}: {message}` through the
    WireError mapping (family UNAVAILABLE, retryable, internalCode) — the wire
    layer does not flatten it into a generic fault."""
    stack = stdio_stack(tmp_path, AllowProbeAuthority())
    seed(stack, definition=stdio_definition(command="/nonexistent-ordessa-probe-binary"))
    error = stack.expect_refusal("mcp.probe", family="UNAVAILABLE",
                                 internal_code="PROBE_SPAWN_FAILED",
                                 serverScope="s1", principal="alice",
                                 definitionId="demo", revision=1)
    assert error.message.startswith("PROBE_SPAWN_FAILED: "), error.message
    assert error.details["retryable"] is True, error.details


@pytest.mark.parametrize("mode,family,code", [
    ("auth", "UNAUTHENTICATED", "PROBE_AUTH_REQUIRED"),
    ("redirect", "CAPABILITY_UNSUPPORTED", "PROBE_REDIRECT_REFUSED"),
])
def test_pcp05b_http_refusals_keep_their_families(tmp_path, contract_primitives,
                                                  mode, family, code):
    """PCP-05b: 401/302 loopback answers → typed, family-correct refusals."""
    with LoopbackHttpFake(mode=mode) as fake:
        stack = stdio_stack(tmp_path, AllowProbeAuthority())
        seed(stack, definition_id="remote-demo",
             definition=remote_definition(name="remote-demo", url=fake.url))
        error = stack.expect_refusal("mcp.probe", family=family,
                                     internal_code=code,
                                     serverScope="s1", principal="alice",
                                     definitionId="remote-demo", revision=1)
        assert error.message.startswith(f"{code}: "), error.message


def test_pcp05c_timeout_is_policy_bounded_and_typed(tmp_path, contract_primitives):
    """PCP-05c: a slow loopback answer dies inside the composed ProbePolicy
    bound (0.3s wall), not the 5s default — PROBE_TIMEOUT/UNAVAILABLE keeps
    its code through the wire, and the cell itself stays millisecond-class."""
    policy = ProbePolicy(timeout=0.3, kill_grace=0.1)
    with LoopbackHttpFake(mode="slow", slow_seconds=2.0) as fake:
        ports = {"permission.probe_authority": AllowProbeAuthority()}
        stack = Stack(tmp_path, host_ports=ports, probe_policy=policy)
        seed(stack, definition_id="remote-demo",
             definition=remote_definition(name="remote-demo", url=fake.url))
        error = stack.expect_refusal("mcp.probe", family="UNAVAILABLE",
                                     internal_code="PROBE_TIMEOUT",
                                     serverScope="s1", principal="alice",
                                     definitionId="remote-demo", revision=1)
        assert error.message.startswith("PROBE_TIMEOUT: "), error.message
