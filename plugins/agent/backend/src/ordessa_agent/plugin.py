"""Agent domain plugin (T010-01): the A1 owners exposed as wire projections.

The wire methods below are projections of the ONE owner set per target.
Business validation and native application stay where A1 puts them; this
plugin never becomes a second writer. The provided port `agent.owners@1`
hands the owner registry to the 010-12 consumer migration.
"""
from __future__ import annotations

from typing import Any, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    WireError,
)

from .owners import AgentOwnerRegistry, AuthorityConflictError, UnknownOutcome

PLUGIN_ID = "ordessa.agent"
PLUGIN_DISPLAY_NAME = "Agent domain owners (A1)"
PLUGIN_VERSION = "1"


class AgentDomainPlugin:
    def __init__(self, registry: AgentOwnerRegistry | None = None) -> None:
        self._registry = registry or AgentOwnerRegistry()

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name=PLUGIN_DISPLAY_NAME, version=PLUGIN_VERSION,
            requires=(),
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        def ensure_target(params: Mapping[str, Any]) -> str:
            target = params.get("target")
            if not isinstance(target, str) or not target:
                raise WireError("INVALID_REQUEST", "target is required")
            owners = self._registry.owners_of(target)
            if owners is None:
                try:
                    owners = self._registry.register(target)
                except AuthorityConflictError as exc:  # pragma: no cover - race
                    raise WireError("INVALID_REQUEST", str(exc)) from exc
            return target

        def config_read(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            snapshot = self._registry.owners_of(target)["config"].snapshot()
            return {
                "ownerRef": snapshot.owner_ref,
                "revision": snapshot.revision,
                "observedEvidence": snapshot.observed_evidence,
                "fields": dict(snapshot.fields),
                "resolved": dict(snapshot.resolved),
            }

        def config_submit_operation(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            patch = params.get("patch", {})
            unset = params.get("unset", [])
            if not isinstance(patch, Mapping) or not isinstance(unset, list):
                raise WireError("INVALID_REQUEST", "patch must map and unset must list")
            summary = self._registry.owners_of(target)["config"].submit_operation(
                patch, str(params.get("sourceRef", "wire")), unset=tuple(str(u) for u in unset))
            return {
                "operationId": summary.operation_id,
                "patchKinds": list(summary.patch_kinds),
                "state": summary.state,
            }

        def submit_input(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            capture = params.get("capture", {})
            if not isinstance(capture, Mapping):
                raise WireError("INVALID_REQUEST", "capture must map")
            submission = self._registry.owners_of(target)["submission"]
            receipt = submission.submit(int(params.get("draftRevision", 0)), capture)
            if receipt.outcome == "unknown":
                # unknown keeps its request association; the wire answer says
                # so and NEVER invites an automatic re-send.
                return {
                    "submissionId": receipt.submission_id,
                    "outcome": "unknown",
                    "queryRequestKey": receipt.query_request_key,
                    "resend": False,
                }
            return {
                "submissionId": receipt.submission_id,
                "outcome": receipt.outcome,
                "consumedDraftRevision": receipt.consumed_draft_revision,
            }

        def session_list(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            sessions = self._registry.owners_of(target)["session"].list()
            return {"items": [dict(s) for s in sessions]}

        def run_query(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            run_id = str(params.get("runId", ""))
            run = self._registry.owners_of(target)["run"].query(run_id)
            if run is None:
                return {"outcome": "unknown", "queryHint": f"run:{run_id}", "resend": False}
            return {"run": dict(run)}

        def interaction_record(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            interaction_id = str(params.get("interactionId", ""))
            fields = params.get("fields", {})
            if not interaction_id or not isinstance(fields, Mapping):
                raise WireError("INVALID_REQUEST", "interactionId must name and fields must map")
            self._registry.owners_of(target)["interaction"].record(interaction_id, fields)
            return {"record": dict(fields)}

        def interaction_list(params: Mapping[str, Any]) -> dict[str, Any]:
            target = ensure_target(params)
            interactions = self._registry.owners_of(target)["interaction"].list()
            return {"items": [dict(i) for i in interactions]}

        methods = (
            ServerMethodDescriptor(method_id="agent.config.read", required_params=frozenset({"target"}),
                                   optional_params=frozenset(), handler=config_read, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.config.submitOperation",
                                   required_params=frozenset({"target"}),
                                   optional_params=frozenset({"patch", "unset", "sourceRef"}),
                                   handler=config_submit_operation, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.submitInput", required_params=frozenset({"target"}),
                                   optional_params=frozenset({"draftRevision", "capture"}),
                                   handler=submit_input, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.session.list", required_params=frozenset({"target"}),
                                   optional_params=frozenset(), handler=session_list, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.run.query", required_params=frozenset({"target"}),
                                   optional_params=frozenset({"runId"}), handler=run_query, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.interaction.record", required_params=frozenset({"target"}),
                                   optional_params=frozenset({"interactionId", "fields"}),
                                   handler=interaction_record, owner=PLUGIN_ID),
            ServerMethodDescriptor(method_id="agent.interaction.list", required_params=frozenset({"target"}),
                                   optional_params=frozenset(), handler=interaction_list, owner=PLUGIN_ID),
        )
        return ServerPluginRegistration(
            methods=methods,
            provided_ports={"agent.owners@1": self._registry},
        )
