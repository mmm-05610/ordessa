"""External sample #3 — a non-Chat terminal/document extension.

Independent distribution (deps only the public plugin API). Proves the
public contracts admit a terminal/document view WITHOUT Agent/Chat/Profile:
it registers read-only document-surface wire methods and declares its
interaction surface through the F1 SurfaceAPI contract (sample-terminal/1
schema). A document surface is read-only: control requests are refused and
reliable submission is typed unsupported.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
    WireError,
)

PLUGIN_ID = "ordessa.sample-terminal"
PLUGIN_DISPLAY_NAME = "Terminal/document sample (non-Chat)"
PLUGIN_VERSION = "1"

METHOD_OPEN = "sample.terminal.open"
METHOD_READ = "sample.terminal.read"
METHOD_CAPABILITIES = "sample.terminal.capabilities"

FROZEN_DOCUMENT = b"line 1: a frozen document body\nline 2: read-only surface\n"
FROZEN_DIGEST = hashlib.sha256(FROZEN_DOCUMENT).hexdigest()

CAPABILITIES = {
    "viewKind": "terminal-document",
    "interactionSchema": "sample-terminal/1",
    "requires": {"agent": False, "chat": False, "profile": False},
    "writable": False,
    "reliableSubmission": "unsupported",
    "reliableSubmissionReason": (
        "the document surface is read-only: control requests are refused and "
        "reliable submission is typed-unsupported, never silently downgraded"),
}


class SampleTerminalPlugin:
    """Non-Chat terminal/document sample: one frozen read-only document."""

    def __init__(self) -> None:
        self._open_count = 0

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name=PLUGIN_DISPLAY_NAME, version=PLUGIN_VERSION,
            requires=(),
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        def open_document(params: Mapping[str, Any]) -> dict[str, Any]:
            request_id = params.get("requestId", "")
            if not isinstance(request_id, str) or not (8 <= len(request_id) <= 128):
                raise WireError("INVALID_REQUEST", "requestId must be 8..128 characters")
            self._open_count += 1
            return {
                "documentId": "doc-1",
                "contentSha256": FROZEN_DIGEST,
                "readOnly": True,
                "viewKind": "terminal-document",
            }

        def read_document(params: Mapping[str, Any]) -> dict[str, Any]:
            document_id = params.get("id")
            if document_id != "doc-1":
                raise WireError("NOT_FOUND", "unknown document")
            return {
                "document": FROZEN_DOCUMENT.decode("utf-8"),
                "contentSha256": FROZEN_DIGEST,
                "readOnly": True,
            }

        def capabilities(params: Mapping[str, Any]) -> dict[str, Any]:
            return dict(CAPABILITIES)

        methods = (
            ServerMethodDescriptor(
                method_id=METHOD_OPEN,
                required_params=frozenset({"requestId"}),
                optional_params=frozenset(),
                handler=open_document, owner=PLUGIN_ID,
            ),
            ServerMethodDescriptor(
                method_id=METHOD_READ,
                required_params=frozenset({"id"}),
                optional_params=frozenset(),
                handler=read_document, owner=PLUGIN_ID,
            ),
            ServerMethodDescriptor(
                method_id=METHOD_CAPABILITIES,
                required_params=frozenset(),
                optional_params=frozenset(),
                handler=capabilities, owner=PLUGIN_ID,
            ),
        )
        return ServerPluginRegistration(methods=methods, provided_ports={})
