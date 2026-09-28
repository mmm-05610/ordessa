"""Ordessa Prompts domain plugin — Server methods and the public service.

Owns the `prompts.*` wire family and provides the `prompts.service` port,
registered through the public `server_plugin_api` vocabulary only: this
module imports no host internals, no Profile implementation and no
Harness implementation (G01/G08 boundary tests enforce that). When this
plugin is not composed, the family is honestly absent.

Ports:

* consumes (optional, by documented name):
  - `profile.prompts_authorization` — the public Profile authorisation
    port for profile-scoped content; absence refuses only that scope;
  - `server.id` — this Server's stable identity string used as the
    snapshot's serverScope; absence falls back to the private data path
    (never to a client-supplied value);
  - `prompts.subject_provider` — a zero-arg callable naming the current
    service-context caller; identity is taken from the context, never
    self-declared in a request. Absence means the loopback single-operator
    subject of this Server.
* provides: `prompts.service` — the PromptsService instance.

The plugin's SQLite lives in its own directory under the product data
root (`<data_root>/prompts/`); the Server core DB and its markers are not
touched (plan.md "数据与升级").
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Callable, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from ordessa_prompts.api import InvalidRequestError
from ordessa_prompts.backend.records import PromptRecords
from ordessa_prompts.backend.service import PromptsService
from ordessa_prompts.backend.storage import PromptsStore

PLUGIN_ID = "ordessa.assets.prompts"
PLUGIN_DISPLAY_NAME = "Prompts: instructions & personas"
PLUGIN_VERSION = "1"

#: the one directory name this plugin owns under the product data root
DATA_DIR_NAME = "prompts"

_DEFAULT_SUBJECT = "server-loopback-operator"


def _require(params: Mapping[str, Any], *names: str) -> None:
    missing = [name for name in names if name not in params]
    if missing:
        raise InvalidRequestError(f"request is missing {', '.join(missing)}")


def _bounded_str(value: Any, name: str, *, max_len: int = 512) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= max_len:
        raise InvalidRequestError(f"{name} must be a bounded string")
    return value


def _body_bytes(value: Any, name: str = "body") -> bytes:
    """Bodies cross the wire base64-encoded; decoding is strict."""
    if not isinstance(value, str) or len(value) > 200_000:
        raise InvalidRequestError(f"{name} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001 - the refusal never echoes input
        raise InvalidRequestError(f"{name} is not valid base64") from exc


def _version(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return int(value)


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidRequestError(f"{name} must be a boolean")
    return value


def _int_or_none(value: Any, name: str) -> "int | None":
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidRequestError(f"{name} must be a positive integer or null")
    return int(value)


def _offset_or_none(value: Any, name: str) -> int:
    """A page offset: zero and upward are both legal (page one is 0)."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return int(value)


class PromptsServerPlugin:
    """Prompts domain: content library + service, Profile/Harness optional."""

    def __init__(self, *, store_path: "Path | str | None" = None) -> None:
        #: tests and isolated deployments may pass an explicit private
        #: database path; production leaves it None and the data-root
        #: service provides the directory.
        self._forced_store_path = store_path
        self._store: "PromptsStore | None" = None
        self._service: "PromptsService | None" = None

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name=PLUGIN_DISPLAY_NAME, version=PLUGIN_VERSION)

    # -- build ------------------------------------------------------------------

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        ports = context.ports
        path = self._forced_store_path
        if path is None:
            data_root = context.data_root
            if data_root is None:
                raise InvalidRequestError(
                    "no data root is available for the Prompts private store")
            path = Path(str(data_root)) / DATA_DIR_NAME / "prompts.db"
        store = PromptsStore(path)
        server_scope = self._server_scope(ports, path)
        subject_provider = self._subject_provider(ports)
        records = PromptRecords(store)
        service = PromptsService(
            records,
            server_scope=server_scope,
            subject_provider=subject_provider,
            profile_authorization=ports.get("profile.prompts_authorization"))
        self._store = store
        self._service = service
        return ServerPluginRegistration(
            methods=self._methods(service),
            provided_ports={"prompts.service": service},
            disposal=self._dispose)

    @staticmethod
    def _server_scope(ports: Mapping[str, Any], store_path: "Path | str") -> str:
        provided = ports.get("server.id")
        if isinstance(provided, str) and provided:
            return provided
        # Absent the (not yet published) server identity port, the
        # physical per-Server binding of this private store is the scope:
        # two data domains cannot share it. (api-requests.md: server.id)
        return "dataroot:" + str(Path(str(store_path)).parent)

    @staticmethod
    def _subject_provider(ports: Mapping[str, Any]) -> "Callable[[], str]":
        provider = ports.get("prompts.subject_provider")
        if callable(provider):
            return provider  # identity comes from the service context
        return lambda: _DEFAULT_SUBJECT

    # -- the wire family -----------------------------------------------------------

    def _methods(self, service: PromptsService) -> "tuple[ServerMethodDescriptor, ...]":
        def prompts_list(params: Mapping[str, Any]) -> dict[str, Any]:
            return service.list(
                scope=params.get("scope"), kind=params.get("kind"),
                query=params.get("query"),
                include_archived=_bool(params.get("includeArchived", False),
                                       "includeArchived"),
                limit=_int_or_none(params.get("limit"), "limit"),
                offset=_offset_or_none(params.get("offset"), "offset"))

        def prompts_get(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "id")
            return service.get(_bounded_str(params["id"], "id"))

        def prompts_get_revision(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "id")
            return service.get_revision(_bounded_str(params["id"], "id"),
                                        _int_or_none(params.get("revision"), "revision"))

        def prompts_create(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "kind", "scope", "title", "body", "operationKey")
            return service.create(
                kind=_bounded_str(params["kind"], "kind", max_len=32),
                scope=params["scope"],
                title=params["title"],
                description=params.get("description"),
                body=_body_bytes(params["body"]),
                operation_key=_bounded_str(params["operationKey"], "operationKey",
                                           max_len=128))

        def prompts_update(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "id", "expectedVersion", "expectedRevision",
                     "patch", "operationKey")
            patch = dict(params["patch"])
            if "bodyBase64" in patch:
                patch["body"] = _body_bytes(patch.pop("bodyBase64"))
            return service.update(
                _bounded_str(params["id"], "id"),
                expected_metadata_version=_version(params["expectedVersion"],
                                                   "expectedVersion"),
                expected_latest_revision=_version(params["expectedRevision"],
                                                  "expectedRevision"),
                patch=patch,
                operation_key=_bounded_str(params["operationKey"], "operationKey",
                                           max_len=128))

        def prompts_clone(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "sourceId", "targetScope", "title", "operationKey")
            return service.clone(
                _bounded_str(params["sourceId"], "sourceId"),
                target_scope=params["targetScope"], title=params["title"],
                source_revision=_int_or_none(params.get("sourceRevision"),
                                             "sourceRevision"),
                operation_key=_bounded_str(params["operationKey"], "operationKey",
                                           max_len=128))

        def prompts_archive(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "id", "expectedVersion", "operationKey")
            return service.archive(
                _bounded_str(params["id"], "id"),
                expected_metadata_version=_version(params["expectedVersion"],
                                                   "expectedVersion"),
                operation_key=_bounded_str(params["operationKey"], "operationKey",
                                           max_len=128))

        def prompts_restore(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "id", "expectedVersion", "operationKey")
            return service.restore(
                _bounded_str(params["id"], "id"),
                expected_metadata_version=_version(params["expectedVersion"],
                                                   "expectedVersion"),
                operation_key=_bounded_str(params["operationKey"], "operationKey",
                                           max_len=128))

        def prompts_import_text(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "contentBase64")
            content = _body_bytes(params["contentBase64"], "contentBase64")
            return service.import_text(
                content,
                filename_hint=(None if "filenameHint" not in params else
                               _bounded_str(params["filenameHint"], "filenameHint",
                                            max_len=255)),
                kind=params.get("kind", "instruction"),
                scope=params.get("scope", {"kind": "library"}),
                title=params.get("title"),
                operation_key=(None if "operationKey" not in params else
                               _bounded_str(params["operationKey"], "operationKey",
                                            max_len=128)))

        def prompts_export_text(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "id")
            return service.export_text(
                _bounded_str(params["id"], "id"),
                _int_or_none(params.get("revision"), "revision"))

        def prompts_resolve_snapshot(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "selection")
            snapshot = service.resolve_snapshot(
                params["selection"],
                profile_revision=_int_or_none(params.get("profileRevision"),
                                              "profileRevision"),
                overlay_revision=_int_or_none(params.get("overlayRevision"),
                                              "overlayRevision"))
            return snapshot.as_wire()

        def prompts_preview(params: Mapping[str, Any]) -> dict[str, Any]:
            _require(params, "selection")
            return service.preview(params["selection"])

        S = frozenset
        return (
            ServerMethodDescriptor(
                method_id="prompts.list",
                required_params=S({"requestId"}),
                optional_params=S({"scope", "kind", "query", "includeArchived",
                                   "limit", "offset"}),
                handler=prompts_list, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.get",
                required_params=S({"requestId", "id"}), optional_params=S(),
                handler=prompts_get, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.getRevision",
                required_params=S({"requestId", "id"}),
                optional_params=S({"revision"}),
                handler=prompts_get_revision, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.create",
                required_params=S({"requestId", "kind", "scope", "title", "body",
                                   "operationKey"}),
                optional_params=S({"description"}),
                handler=prompts_create, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.update",
                required_params=S({"requestId", "id", "expectedVersion",
                                   "expectedRevision", "patch", "operationKey"}),
                optional_params=S(),
                handler=prompts_update, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.clone",
                required_params=S({"requestId", "sourceId", "targetScope", "title",
                                   "operationKey"}),
                optional_params=S({"sourceRevision"}),
                handler=prompts_clone, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.archive",
                required_params=S({"requestId", "id", "expectedVersion",
                                   "operationKey"}),
                optional_params=S(),
                handler=prompts_archive, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.restore",
                required_params=S({"requestId", "id", "expectedVersion",
                                   "operationKey"}),
                optional_params=S(),
                handler=prompts_restore, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.importText",
                required_params=S({"requestId", "contentBase64"}),
                optional_params=S({"filenameHint", "kind", "scope", "title",
                                   "operationKey"}),
                handler=prompts_import_text, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.exportText",
                required_params=S({"requestId", "id"}),
                optional_params=S({"revision"}),
                handler=prompts_export_text, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.resolveSnapshot",
                required_params=S({"requestId", "selection"}),
                optional_params=S({"profileRevision", "overlayRevision"}),
                handler=prompts_resolve_snapshot, owner=PLUGIN_ID),
            ServerMethodDescriptor(
                method_id="prompts.preview",
                required_params=S({"requestId", "selection"}), optional_params=S(),
                handler=prompts_preview, owner=PLUGIN_ID),
        )

    def _dispose(self) -> None:
        if self._store is not None:
            self._store.close()
        self._store = None
        self._service = None
