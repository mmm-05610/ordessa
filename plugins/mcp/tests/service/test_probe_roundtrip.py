"""§1 row 2 (probe) both paths through the real dispatch: the unauthorised
refusal (port absent AND authority denial) and the authorised run against
the composition-injected fake transport. The probe NEVER carries
credentials and NEVER claims a catalog — the facts shape pins that."""
from __future__ import annotations

from service_helpers import (
    AllowProbeAuthority,
    DenyProbeAuthority,
    Stack,
    fake_probe_runner,
    raising_probe_runner,
    seed_revision,
)

from backend.errors import McpError
from backend.probe import PROBE_TIMEOUT


def test_probe_without_authority_refuses_and_never_runs_the_transport(tmp_path):
    calls = []
    stack = Stack(tmp_path, probe_runner=lambda canonical, **kw: calls.append(1))
    stack.expect_refusal("mcp.probe", family="UNAVAILABLE",
                         internal_code="PERMISSION_AUTHORITY_ABSENT",
                         serverScope="s1", principal="alice",
                         definitionId="demo", revision=1)
    assert calls == []  # the refusal happened before any transport


def test_probe_authorised_runs_and_answers_graded_facts(tmp_path):
    authority = AllowProbeAuthority()
    stack = Stack(tmp_path, host_ports={"permission.probe_authority": authority},
                  probe_runner=fake_probe_runner)
    seed_revision(stack)
    answer = stack.call("mcp.probe", serverScope="s1", principal="alice",
                        definitionId="demo", revision=1)
    assert authority.calls == [("alice", "s1", "demo", 1)]
    facts = answer["probe"]
    assert facts["status"] == "ok"
    assert facts["credentialScope"] == "unproven"
    # FR-02: a handshake probe proves the handshake and nothing else
    assert "tool-catalog" in facts["doesNotProve"]
    assert "credential-usability" in facts["doesNotProve"]
    assert answer["definitionId"] == "demo" and answer["revision"] == 1


def test_probe_denied_by_authority_refuses_before_transport(tmp_path):
    runs = []
    stack = Stack(tmp_path, host_ports={"permission.probe_authority": DenyProbeAuthority()},
                  probe_runner=lambda canonical, **kw: runs.append(1))
    seed_revision(stack)
    stack.expect_refusal("mcp.probe", family="FORBIDDEN",
                         internal_code="PERMISSION_REFUSED",
                         serverScope="s1", principal="alice",
                         definitionId="demo", revision=1)
    assert runs == []


def test_probe_transport_refusal_keeps_its_own_family(tmp_path):
    stack = Stack(tmp_path,
                  host_ports={"permission.probe_authority": AllowProbeAuthority()},
                  probe_runner=raising_probe_runner(
                      McpError(PROBE_TIMEOUT, "the server did not answer in time")))
    seed_revision(stack)
    error = stack.expect_refusal(
        "mcp.probe", family="UNAVAILABLE", internal_code="PROBE_TIMEOUT",
        serverScope="s1", principal="alice", definitionId="demo", revision=1)
    assert error.details["retryable"] is True


def test_probe_missing_revision_refuses_not_found(tmp_path):
    stack = Stack(tmp_path, host_ports={"permission.probe_authority": AllowProbeAuthority()})
    stack.expect_refusal("mcp.probe", family="NOT_FOUND",
                         internal_code="MCP_ASSET_MISSING",
                         serverScope="s1", principal="alice",
                         definitionId="demo", revision=99)
