"""The Ordessa memory domain plugin: the mem0 self-hosted leaf (015 P-B).

Registration shape (server_plugin_api public vocabulary only — this module
imports no host internals, no Profile implementation, no Harness
implementation, and never ``ordessa_model_provider``):

* consumes (declared): ``ordessa.model-provider`` — the access grant for the
  ``model_provider.catalog`` provided port (AR-2 provider resolution). The
  port object is duck-typed; a composition edge without it degrades to the
  honest ``llmWiring: unsupported`` state, never a crash.
* consumes (optional, by documented name): ``server.id`` — the Server's
  stable identity scoping the profile namespaces (prompts-domain form).
* provides: ``assets.memory.service`` — the facade other domains consume.
* contributes: the eight brand ``assets.memory`` adapters into the real C2
  point ``harness.configuration-adapters`` (conformance-pinned overlap
  discipline; see ``bridge.py`` for the honest compile semantics), and the
  domain's own error-code → wire-family rows (model-provider form: the
  mapping lives with the plugin that raises the codes).
* wire family ``memory.*``: status / binding get+set / explicit extraction
  authorization / health / injection block / memory listing. Every surface
  carries the attribution line (spec red line 4).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from server_plugin_api import (
    WIRE_ERROR_FAMILIES_API_VERSION, WIRE_ERROR_FAMILIES_POINT_ID,
    Contribution, ContributionBatch, ServerMethodDescriptor, ServerPluginContext,
    ServerPluginDescriptor, ServerPluginRegistration,
)

from . import bridge, common, facet, llm_wiring, provisioning
from .capture import CapturePipeline
from .events import TurnSourceBinding, turn_event_from_mapping
from .injection import InjectionProducer, mount_note
from .mem0_client import Mem0Client, Mem0Unreachable
from .store import MemoryStore

PLUGIN_ID = "ordessa.assets.memory"
PLUGIN_DISPLAY_NAME = "Memory: mem0 self-hosted (Apache-2.0)"
PLUGIN_VERSION = "1"
#: The data-root directory name this plugin owns.
DATA_DIR_NAME = "memory"

#: The hard dependency: provider resolution comes from the model-provider
#: catalog port (requires = the access grant, server_plugin_api contract).
REQUIRES = ("ordessa.model-provider",)

CONFIGURATION_POINT = "harness.configuration-adapters"

#: The domain's own failure codes, self-published through
#: ``wire.error-families`` (model-provider form — the mapping lives with the
#: plugin that raises the codes; a contradicting row refuses at stage).
MEMORY_ERROR_CODES = {
    "MEMORY_INVALID_REQUEST": "INVALID_REQUEST",
    "MEMORY_INVALID_BINDING": "INVALID_REQUEST",
    "MEMORY_STORE_UNAVAILABLE": "UNAVAILABLE",
    "MEMORY_STACK_UNREACHABLE": "WORKER_UNREACHABLE",
    "MEMORY_WIRING_UNSUPPORTED": "CAPABILITY_UNSUPPORTED",
}


class MemoryError(Exception):
    """One of the domain's typed refusals; the message is body-free."""

    def __init__(self, code: str, message: str) -> None:
        if code not in MEMORY_ERROR_CODES:
            raise ValueError(f"unknown memory error code: {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _invalid_request(message: str) -> MemoryError:
    return MemoryError("MEMORY_INVALID_REQUEST", message)


def _bounded_str(value: Any, name: str, *, max_len: int = 256) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= max_len:
        raise _invalid_request(f"{name} must be a bounded string")
    return value


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_request(f"{name} must be a boolean")
    return value


class MemoryService:
    """The provided-port facade other domains consume (thin, read-mostly)."""

    def __init__(self, plugin: "MemoryPlugin") -> None:
        self._plugin = plugin

    def binding(self, profile_id: str) -> dict[str, Any]:
        return self._plugin.store.get_binding(profile_id)

    def injection_block(self, profile_id: str, query: str, *,
                        brand: str | None = None) -> dict[str, Any]:
        return self._plugin.injection_block_response(profile_id, query, brand)

    def status(self) -> dict[str, Any]:
        return self._plugin.status_snapshot()


class MemoryPlugin:
    """Server plugin: mem0 provisioning lifecycle + capture/injection pipelines."""

    def __init__(self, *, store_path: "Path | str | None" = None,
                 data_root: "Path | str | None" = None,
                 port_plan: "provisioning.PortPlan | None" = None,
                 runner: "provisioning.CommandRunner | None" = None) -> None:
        self._forced_store_path = store_path
        self._forced_data_root = data_root
        self._port_plan = port_plan
        self._runner = runner or provisioning.SystemRunner()
        self.store: MemoryStore | None = None
        self.stack: "provisioning.MemoryStack | None" = None
        self.pipeline: CapturePipeline | None = None
        self.producer: InjectionProducer | None = None
        self.turn_source = TurnSourceBinding()
        self._catalog: Any = None
        self._server_scope: str | None = None
        self._client: Mem0Client | None = None
        self._data_root_dir: Path | None = None

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name=PLUGIN_DISPLAY_NAME, version=PLUGIN_VERSION,
            requires=REQUIRES)

    # -- build ------------------------------------------------------------------

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        ports = context.ports
        root: Path
        if self._forced_data_root is not None:
            root = Path(str(self._forced_data_root)) / DATA_DIR_NAME
        elif context.data_root is not None:
            root = Path(str(context.data_root)) / DATA_DIR_NAME
        else:
            raise MemoryError(
                "MEMORY_STORE_UNAVAILABLE", "no data root is available for the memory domain")
        root.mkdir(parents=True, exist_ok=True)
        self._data_root_dir = root
        path = Path(str(self._forced_store_path)) if self._forced_store_path else root / "memory.db"
        self.store = MemoryStore(path)
        self._catalog = ports.get("model_provider.catalog")
        provided_scope = ports.get("server.id")
        self._server_scope = provided_scope if isinstance(provided_scope, str) else None
        if self._port_plan is not None:
            self.stack = provisioning.MemoryStack(self._runner, root, self._port_plan)
        self.pipeline = CapturePipeline(
            self.store, self._client_getter, lambda: self._server_scope)
        self.producer = InjectionProducer(self._client_getter, lambda: self._server_scope)
        self.turn_source.set_handler(self._on_turn)
        service = MemoryService(self)
        return ServerPluginRegistration(
            methods=self._methods(),
            provided_ports={"assets.memory.service": service},
            contributions=ContributionBatch((
                Contribution(WIRE_ERROR_FAMILIES_POINT_ID,
                             WIRE_ERROR_FAMILIES_API_VERSION, dict(MEMORY_ERROR_CODES)),
                *(Contribution(CONFIGURATION_POINT, "v1", bridge.BridgeMemoryAdapter(brand),
                               required=True)
                  for brand in common.BRANDS),
            ), open_points=frozenset({CONFIGURATION_POINT})),
            disposal=self._dispose,
        )

    # -- composition edges --------------------------------------------------------

    def bind_turn_source(self, source: Any) -> None:
        """Bind the (composition-supplied) turn-event source (AR-3 port).
        Absence of the port simply leaves the documented absent state."""
        self.pipeline.mark_source_bound(True)
        self.turn_source.bind(source)

    def _on_turn(self, event: Any) -> None:
        if isinstance(event, Mapping):
            event = turn_event_from_mapping(event)
        binding = self.store.get_binding(event.profile_id)
        self.pipeline.on_turn(event, binding=binding)

    def _client_getter(self) -> "Mem0Client | None":
        if self.stack is None:
            return None
        if self._client is None:
            env_file = self.stack.env_file
            if not env_file.exists():
                return None
            self._client = Mem0Client(
                self.stack.base_url,
                lambda: provisioning.read_admin_key(env_file))
        return self._client

    # -- status ---------------------------------------------------------------------

    def status_snapshot(self) -> dict[str, Any]:
        stack_state = "unprovisioned"
        docker_facts: "dict[str, str] | None" = None
        if self.stack is not None and self.stack.env_file.exists():
            stack_state = "provisioned"
            try:
                docker_facts = provisioning.detect_docker(self._runner)
            except provisioning.ProvisioningUnsupported:
                stack_state = "provisioned-host-lost-docker"
        try:
            plan = llm_wiring.resolve_wiring(self._catalog)
            wiring: dict[str, Any] = {
                "state": "supported",
                "llmProvider": plan.llm.provider, "llmModel": plan.llm_model,
                "embedderProvider": plan.embedder.provider,
                "embedderModel": plan.embedder_model,
                "note": "凭据以引用解析；内容只在写 data-root .env 时落地"}
        except llm_wiring.WiringUnsupported as exc:
            wiring = {"state": "unsupported", "reason": exc.reason}
        return {
            "attribution": common.ATTRIBUTION,
            "engine": "mem0",
            "license": "Apache-2.0",
            "deployment": "本地自托管（Docker）",
            "telemetry": "disabled",
            "mem0Pin": {"repo": common.MEM0_REPO_URL, "sha": common.MEM0_GIT_SHA},
            "docker": docker_facts,
            "stack": stack_state,
            "llmWiring": wiring,
            "extractionAuthorized": self.store.extraction_authorized(),
            "capture": {
                **(self.store.capture_stats()),
                "source": self.turn_source.source_status(),
            },
            "defaultBinding": common.default_binding(),
        }

    # -- the wire family --------------------------------------------------------------

    def _methods(self) -> "tuple[ServerMethodDescriptor, ...]":
        def memory_status(params: Mapping[str, Any]) -> dict[str, Any]:
            return self.status_snapshot()

        def memory_binding_get(params: Mapping[str, Any]) -> dict[str, Any]:
            profile_id = _bounded_str(params.get("profileId"), "profileId")
            return {"profileId": profile_id,
                    "value": self.store.get_binding(profile_id),
                    "isDefault": not self.store.has_binding_override(profile_id),
                    "attribution": common.ATTRIBUTION}

        def memory_binding_set(params: Mapping[str, Any]) -> dict[str, Any]:
            profile_id = _bounded_str(params.get("profileId"), "profileId")
            try:
                value = facet.validate_binding(params.get("value"))
            except facet.FacetValueError as exc:
                raise MemoryError("MEMORY_INVALID_BINDING", exc.message) from exc
            stored = self.store.set_binding(profile_id, value)
            return {"profileId": profile_id, "value": stored,
                    "attribution": common.ATTRIBUTION}

        def memory_extraction_authorize(params: Mapping[str, Any]) -> dict[str, Any]:
            authorized = _bool(params.get("authorized"), "authorized")
            self.store.set_extraction_authorized(authorized)
            return {"authorized": authorized,
                    "attribution": common.ATTRIBUTION,
                    "note": "显式授权后抽取仅走已解析的 bundled provider，且仍受 E3 真实模型授权约束"}

        def memory_health(params: Mapping[str, Any]) -> dict[str, Any]:
            client = self._client_getter()
            if client is None:
                return {"reachable": False, "reason": "stack not provisioned",
                        "attribution": common.ATTRIBUTION}
            try:
                client.docs_liveness()
            except Mem0Unreachable as exc:
                return {"reachable": False, "reason": str(exc),
                        "attribution": common.ATTRIBUTION}
            return {"reachable": True, "attribution": common.ATTRIBUTION}

        def memory_injection_block(params: Mapping[str, Any]) -> dict[str, Any]:
            profile_id = _bounded_str(params.get("profileId"), "profileId")
            query = _bounded_str(params.get("query"), "query", max_len=2048)
            brand = params.get("brand")
            if brand is not None:
                brand = _bounded_str(brand, "brand", max_len=64)
            return self.injection_block_response(profile_id, query, brand)

        def memory_memories_list(params: Mapping[str, Any]) -> dict[str, Any]:
            profile_id = _bounded_str(params.get("profileId"), "profileId")
            client = self._client_getter()
            if client is None:
                return {"items": [], "reason": "stack not provisioned",
                        "attribution": common.ATTRIBUTION}
            namespace = common.profile_namespace(self._server_scope, profile_id)
            try:
                answer = client.get_all(namespace)
            except Mem0Unreachable as exc:
                return {"items": [], "reason": str(exc),
                        "attribution": common.ATTRIBUTION}
            return {"items": answer.get("results") or [],
                    "attribution": common.ATTRIBUTION}

        S = frozenset
        return (
            ServerMethodDescriptor(
                method_id="memory.status", required_params=S({"requestId"}),
                optional_params=S(), handler=memory_status, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="memory.binding.get", required_params=S({"requestId", "profileId"}),
                optional_params=S(), handler=memory_binding_get, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="memory.binding.set",
                required_params=S({"requestId", "profileId", "value", "operationKey"}),
                optional_params=S(), handler=memory_binding_set, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="memory.extraction.authorize",
                required_params=S({"requestId", "authorized", "operationKey"}),
                optional_params=S(), handler=memory_extraction_authorize, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="memory.health", required_params=S({"requestId"}),
                optional_params=S(), handler=memory_health, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="memory.injectionBlock",
                required_params=S({"requestId", "profileId", "query"}),
                optional_params=S({"brand"}), handler=memory_injection_block, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="memory.memories.list", required_params=S({"requestId", "profileId"}),
                optional_params=S(), handler=memory_memories_list, owner=PLUGIN_ID),
        )

    def injection_block_response(self, profile_id: str, query: str,
                                 brand: "str | None") -> dict[str, Any]:
        block = self.producer.block(profile_id, query, self.store.get_binding(profile_id),
                                    brand=brand)
        return {"text": block.text, "count": block.count, "mounted": block.mounted,
                "reason": block.reason, "attribution": block.attribution,
                "facetName": common.INSTRUCTION_FACET_NAME,
                "coexistenceNote": mount_note(brand)}

    def _dispose(self) -> None:
        self.turn_source.unbind()
        if self.store is not None:
            self.store.close()
        self.store = None
        self.pipeline = None
        self.producer = None
        self._client = None
