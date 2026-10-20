"""External sample #2 — a static resource package.

A minimal third-party Server plugin composed only through the public
`server_plugin_api` contract. It owns two read-only wire methods,
`sample.resources.list` and `sample.resources.get`, and serves one frozen
JSON document shipped inside its own distribution. It installs without
Server, Harness or Profile: its only dependency is
`ordessa-server-plugin-api`, it imports no product module, and it is
enabled only by an explicit composition selection — installing the
distribution never enables it.

Public access (lifecycle-evidence §SDK真实穿透与样例, external sample #2):

    from ordessa_server.bootstrap import build_runtime
    from ordessa_sample_static_resource import SampleStaticResourcePlugin

    runtime = build_runtime(data_root, server_plugins=(SampleStaticResourcePlugin(),))
    runtime.start()
    runtime.wire.dispatch("sample.resources.list", {})

Exit: `runtime.stop()` retires both methods with the round; nothing is
written under the data root and nothing outlives the composition.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    WireError,
)

PLUGIN_ID = "ordessa.sample-static-resource"
PLUGIN_DISPLAY_NAME = "Static resource sample"
PLUGIN_VERSION = "1"

METHOD_LIST = "sample.resources.list"
METHOD_GET = "sample.resources.get"

#: The frozen content document, packaged with this distribution.
PACKAGE_ROOT = Path(__file__).resolve().parent
RESOURCES_PATH = PACKAGE_ROOT / "data" / "resources.json"

#: The sha256 of the frozen bytes above, pinned here so the package can
#: verify its own content at build time: an edited or corrupted document is
#: a typed startup failure, never silently served bytes.
FROZEN_RESOURCES_SHA256 = "6083dafe7d08e5970e091f5ad41c368db7d2eab92429e1cfe6dddad7231b66fd"


class SampleStaticResourcePlugin:
    """Static resource sample: one frozen document, two read-only methods."""

    def __init__(self) -> None:
        self._resources: tuple[dict[str, Any], ...] = ()
        self._content_sha256: str = ""

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name=PLUGIN_DISPLAY_NAME, version=PLUGIN_VERSION,
            requires=(),
        )

    # -- build ----------------------------------------------------------------

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        # The host hands its scoped facades in `context.ports`; this plugin
        # needs none of them — the content travels with the package.
        document = self._load_frozen_document()
        self._resources = tuple(document["resources"])
        self._content_sha256 = FROZEN_RESOURCES_SHA256

        def sample_resources_list(params: Mapping[str, Any]) -> dict[str, Any]:
            # Read-only: the frozen document, byte-digest pinned, in file order.
            return {
                "schema": document["schema"],
                "items": [dict(entry) for entry in self._resources],
                "contentSha256": self._content_sha256,
            }

        def sample_resources_get(params: Mapping[str, Any]) -> dict[str, Any]:
            resource_id = params["id"]
            if (not isinstance(resource_id, str) or not resource_id
                    or len(resource_id) > 128):
                raise WireError(
                    "INVALID_REQUEST", "id must be a bounded string")
            for entry in self._resources:
                if entry["id"] == resource_id:
                    return {
                        "resource": dict(entry),
                        "contentSha256": self._content_sha256,
                    }
            raise WireError(
                "NOT_FOUND",
                f"sample resource {resource_id!r} does not exist")

        methods = (
            ServerMethodDescriptor(
                method_id=METHOD_LIST,
                required_params=frozenset(),
                optional_params=frozenset(),
                handler=sample_resources_list, owner=PLUGIN_ID,
            ),
            ServerMethodDescriptor(
                method_id=METHOD_GET,
                required_params=frozenset({"id"}),
                optional_params=frozenset(),
                handler=sample_resources_get, owner=PLUGIN_ID,
            ),
        )
        return ServerPluginRegistration(
            methods=methods,
            # Deliberately empty: the sample exposes nothing for other plugins
            # to consume, and consumes nothing in return.
            provided_ports={},
        )

    # -- frozen content -------------------------------------------------------

    def _load_frozen_document(self) -> dict[str, Any]:
        raw = RESOURCES_PATH.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != FROZEN_RESOURCES_SHA256:
            raise RuntimeError(
                "SAMPLE_STATIC_RESOURCE_CONTENT_MISMATCH: the packaged frozen "
                f"content digest {digest!r} does not match the pinned digest "
                f"{FROZEN_RESOURCES_SHA256!r}; refusing to serve unverified bytes")
        document = json.loads(raw.decode("utf-8"))
        if (not isinstance(document, dict)
                or not isinstance(document.get("schema"), str)
                or not isinstance(document.get("resources"), list)):
            raise RuntimeError(
                "SAMPLE_STATIC_RESOURCE_CONTENT_INVALID: frozen document is not "
                "the expected {schema, resources} shape")
        return document
