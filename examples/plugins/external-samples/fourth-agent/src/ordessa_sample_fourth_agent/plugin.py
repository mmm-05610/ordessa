"""External sample #1 — a fourth controlled Agent with a different protocol.

A minimal third-party participant composed only through the public
`server_plugin_api` contract. Unlike the three brands (codex/pi/claude-code,
which speak ACP), this sample speaks its own interaction schema
``sample-agent/1`` and declares, honestly and in typed form, that reliable
submissions are **unsupported**: it carries no protected fingerprint and no
durable intent store (C1/Q-table: unsupported means typed refusal, never a
silent downgrade and never an empty success).

Wire surface (three methods):

* ``sample.agent.capabilities`` — the declaration above, exact bytes pinned
  by tests;
* ``sample.agent.status`` — read-only liveness, no effects;
* ``sample.agent.echo`` — a controlled fake interaction with stable
  request-id semantics: replaying the same requestId + payload returns the
  same receipt (idempotent), while the same requestId with a different
  payload is a typed conflict — never a second dispatch (C2 discipline).

Exit: `runtime.stop()` retires the methods with the round; the idempotency
ledger lives in memory only and dies with the composition.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    WireError,
)

PLUGIN_ID = "ordessa.sample-fourth-agent"
PLUGIN_DISPLAY_NAME = "Fourth controlled agent (sample-agent/1)"
PLUGIN_VERSION = "1"

METHOD_CAPABILITIES = "sample.agent.capabilities"
METHOD_STATUS = "sample.agent.status"
METHOD_ECHO = "sample.agent.echo"

#: The declared interaction schema — deliberately NOT acp: this sample exists
#: to prove the public contract admits a foreign protocol without core
#: brand branches (R03/R11).
INTERACTION_SCHEMA = "sample-agent/1"

CAPABILITIES = {
    "interactionSchema": INTERACTION_SCHEMA,
    "methods": [METHOD_CAPABILITIES, METHOD_STATUS, METHOD_ECHO],
    "reliableSubmission": "unsupported",
    "reliableSubmissionReason": (
        "this sample's protocol declares no protected fingerprint and no "
        "durable intent store; reliable requests are typed-refused before "
        "dispatch and the raw path is unaffected (M06 semantics)"),
    "history": "unsupported",
    "historyReason": "the sample keeps no session history; there is nothing to decode",
}


class SampleFourthAgentPlugin:
    """Fourth controlled agent: foreign protocol, honest unsupported claims."""

    def __init__(self) -> None:
        # request_id -> {"digest": str, "receipt": dict} — the C2 idempotency
        # ledger, memory-only by contract.
        self._ledger: dict[str, dict[str, Any]] = {}

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name=PLUGIN_DISPLAY_NAME, version=PLUGIN_VERSION,
            requires=(),
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        def sample_agent_capabilities(params: Mapping[str, Any]) -> dict[str, Any]:
            return json.loads(json.dumps(CAPABILITIES))

        def sample_agent_status(params: Mapping[str, Any]) -> dict[str, Any]:
            return {"state": "ready", "schema": INTERACTION_SCHEMA}

        def sample_agent_echo(params: Mapping[str, Any]) -> dict[str, Any]:
            request_id = params["requestId"]
            payload = params["payload"]
            if (not isinstance(request_id, str) or not request_id
                    or len(request_id) > 128):
                raise WireError("INVALID_REQUEST", "requestId must be a bounded string")
            if not isinstance(payload, str) or len(payload) > 4096:
                raise WireError("INVALID_REQUEST", "payload must be a bounded string")
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            entry = self._ledger.get(request_id)
            if entry is not None:
                if entry["digest"] != digest:
                    # Same key, different input digest: a conflict, never a
                    # second dispatch (C2).
                    raise WireError(
                        "INVALID_REQUEST",
                        f"request {request_id!r} is spent with a different payload",
                        {"internalCode": "REQUEST_DIGEST_CONFLICT"})
                return entry["receipt"]  # replay: the original receipt
            receipt = {
                "requestId": request_id,
                "digest": digest,
                "echo": payload,
                "delivery": "acknowledged",
            }
            self._ledger[request_id] = {"digest": digest, "receipt": receipt}
            return receipt

        methods = (
            ServerMethodDescriptor(
                method_id=METHOD_CAPABILITIES,
                required_params=frozenset(),
                optional_params=frozenset(),
                handler=sample_agent_capabilities, owner=PLUGIN_ID,
            ),
            ServerMethodDescriptor(
                method_id=METHOD_STATUS,
                required_params=frozenset(),
                optional_params=frozenset(),
                handler=sample_agent_status, owner=PLUGIN_ID,
            ),
            ServerMethodDescriptor(
                method_id=METHOD_ECHO,
                required_params=frozenset({"requestId", "payload"}),
                optional_params=frozenset(),
                handler=sample_agent_echo, owner=PLUGIN_ID,
            ),
        )
        return ServerPluginRegistration(
            methods=methods,
            provided_ports={},
        )
