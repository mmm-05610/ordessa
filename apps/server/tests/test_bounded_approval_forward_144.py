"""Work Order 144 (needs_validation → conclusion 2): bounded-scope forwarding is verbatim.

AUD-B-026: `approvals.decide`'s `scope.bounded.environmentId` is only shape-checked (in the
locked wire schema) - the Server never validates it against the actual execution environment
and has no consumer. `grep environmentId` in this tree's non-`wire` src returns nothing; the
decision + scope are forwarded *verbatim* to the harness (`SidecarHarnessPort.decide_approval`
-> `permission_decision`), and `records.py` stores `scope_json` only as evidence.

Conclusion (see docs/server-round1/bounded-approval-environment-binding-144.md): **2 - the
harness/plugin owns the native binding** (AGENTS.md: "Server composes plugins; plugins own
native Harness semantics"). The Server's job is to forward the authorized scope faithfully,
not to silently rewrite or drop it. This gate pins that fact: it drives the real
`register_approval` + `decide_approval` methods with a recording channel and asserts the
`bounded` scope (including `environmentId`) reaches the harness byte-identical.

Counterexample: if the forward mutated or dropped any scope key, `assert captured == scope`
would be red - the boundary is on the books, not implied.
"""
from __future__ import annotations

from ordessa_server_compat.execution.sidecar import SidecarHarnessPort


class _RecordingChannel:
    """Stands in for the harness-side `SidecarEnvelope`; records the forwarded frame."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def request(self, payload, *, timeout=None):
        self.requests.append(dict(payload))
        return {}


def _port_with_channel():
    port = SidecarHarnessPort(object(), environment={})
    channel = _RecordingChannel()
    port._sessions["exec-1"] = channel
    return port, channel


def test_bounded_scope_forwards_verbatim_to_the_harness():
    port, channel = _port_with_channel()
    scope = {"kind": "bounded", "until": "session_end", "environmentId": "env-X"}
    port.register_approval("ap-1", "exec-1", "sidecar-req-9")
    port.decide_approval("ap-1", "allow", scope)

    assert len(channel.requests) == 1
    frame = channel.requests[0]
    assert frame["op"] == "permission_decision"
    assert frame["requestId"] == "sidecar-req-9"
    assert frame["decision"] == "allow"
    # The whole authorized scope, environmentId included, arrives unchanged.
    assert frame["scope"] == scope


def test_server_does_not_bind_or_rewrite_the_environment_field():
    # Whatever environmentId the user approved is forwarded untouched; the Server
    # neither maps nor drops it (conclusion 2: the harness decides what it means).
    port, channel = _port_with_channel()
    scope = {"kind": "bounded", "until": "session_end", "environmentId": "totally-other"}
    port.register_approval("ap-2", "exec-1", "req-2")
    port.decide_approval("ap-2", "allow", scope)
    assert channel.requests[0]["scope"]["environmentId"] == "totally-other"
