"""Thin Claude Code stream-json consumer; no Agent SDK engine or retry loop.

Wire reference: anthropics/claude-agent-sdk-python at
9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b, _internal/query.py, client.py,
types.py and _internal/transport/subprocess_cli.py (read 2026-10-05).
This source pin is not an installed SDK/CLI version. Production should prefer
that upstream SDK. This synchronous consumer implements only user/control
initialize/interrupt and explicit can_use_tool responses; hooks/SDK MCP and
background-run completion are not implemented. A result ends a turn, never
proves the process or background tasks ended. No prompt is automatically resent.
Bidirectional mode requires the Harness owner to launch --input-format
stream-json --output-format stream-json --permission-prompt-tool stdio --verbose.
"""
from __future__ import annotations

import copy
import math
import time
import uuid
from typing import Any, Mapping

from ._transport import ChannelClosed, ChannelFailure, FramingError, LostReceipt, ProcessChannel, RequestTimeout

FAMILY_ID = "claude"
COMMAND_CATALOG_ID = "claude-code"
PROTOCOL = "claude-stream-json/1"
SOURCE_COMMIT = "9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b"


class ClaudeStreamFailure(ChannelFailure):
    def __init__(self, detail: str, raw: Mapping[str, Any]):
        super().__init__("CLAUDE_RUN_FAILED", detail)
        self.raw = copy.deepcopy(dict(raw))


class ClaudePermissionPending(ChannelFailure):
    """Native approval is waiting for an explicit caller decision."""
    def __init__(self, raw):
        super().__init__("CLAUDE_PERMISSION_PENDING", "Native tool permission awaits an explicit decision")
        self.raw = copy.deepcopy(raw)


def describe() -> dict[str, Any]:
    return {"familyId": FAMILY_ID, "commandCatalogId": COMMAND_CATALOG_ID,
            "channel": "stdio-stream-json", "protocol": PROTOCOL,
            "schemaSourceCommit": SOURCE_COMMIT,
            "knownMessageTypes": ["system/init", "system/api_retry", "system/plugin_install",
                                  "assistant", "user", "stream_event", "permission_denied", "result",
                                  "control_request", "control_response", "control_cancel_request"],
            "completionScope": "turn", "sdkHooksImplemented": False, "sdkMcpImplemented": False}


def _text(value):
    return isinstance(value, str) and bool(value) and value.strip() == value


class ClaudeCodeClient:
    """Serialized consumer of one owned channel; no concurrent reader support.

    Output-only mode never writes stdin. Bidirectional mode must be explicitly
    selected and initialized. One outstanding prompt is allowed: unknown
    outcomes remain outstanding, even after an interrupt receipt.
    """
    def __init__(self, channel: ProcessChannel, *, name="claude-stream", bidirectional=False, session_id=None):
        if type(bidirectional) is not bool or (session_id is not None and not _text(session_id)):
            raise ValueError("invalid Claude channel mode or session identity")
        self._channel, self._name, self._bidirectional = channel, name, bidirectional
        self._session = session_id
        self._records = []
        self._init = None
        self._control_ready = False
        self._initialize_sent = False
        self._active_turn = False
        self._result = None
        self._permissions = {}
        self._permission_ids = set()
        self._closed = False

    @classmethod
    def launch(cls, spec: Any, *, name="claude-stream", bidirectional=False, session_id=None):
        return cls(ProcessChannel.launch(spec, name=name), name=name,
                   bidirectional=bidirectional, session_id=session_id)

    def initialize(self, *, timeout=30.0):
        """Observe system/init; this is not the SDK control initialize receipt."""
        if self._init is not None:
            self._open()
            return copy.deepcopy(self._init)
        return self._wait_for(lambda r: r.get("type") == "system" and r.get("subtype") == "init", timeout=timeout)

    def initialize_control(self, *, timeout=30.0):
        self._writable()
        if self._initialize_sent:
            raise ChannelFailure("CLAUDE_CONTROL_ALREADY_SENT", "Initialize was already sent; do not resend an unknown request")
        self._valid_timeout(timeout)
        self._initialize_sent = True
        result = self._control({"subtype": "initialize", "hooks": None}, timeout=timeout)
        self._control_ready = True
        return result

    @property
    def session_id(self):
        return self._session

    @property
    def capabilities(self):
        return tuple(self._init.get("capabilities") or ()) if self._init else ()

    def submit_user(self, content: str, *, session_id=None):
        self._writable()
        if not self._control_ready:
            raise ChannelFailure("CLAUDE_NOT_INITIALIZED", "Control initialization is required")
        if self._active_turn or self._permissions:
            raise ChannelFailure("CLAUDE_TURN_PENDING", "Previous turn or permission is unresolved; query its evidence instead of resending")
        if not isinstance(content, str) or not content:
            raise ValueError("user content must be a nonempty string")
        selected = session_id if session_id is not None else self._session or "default"
        if not _text(selected) or (self._session is not None and selected != self._session):
            raise ChannelFailure("CLAUDE_SESSION_MISMATCH", "User input does not match the bound native session")
        if selected != "default":
            self._session = selected
        self._active_turn = True  # Set before write; a partial write stays unknown.
        self._result = None
        self._send({"type": "user", "message": {"role": "user", "content": content},
                    "parent_tool_use_id": None, "session_id": selected}, "user", None)

    def interrupt(self, *, timeout=10.0):
        self._writable()
        if not self._control_ready:
            raise ChannelFailure("CLAUDE_NOT_INITIALIZED", "Control initialization is required")
        # A control receipt acknowledges interrupt only; it does not clear the turn.
        return self._control({"subtype": "interrupt"}, timeout=timeout)

    def pending_permissions(self):
        return tuple(copy.deepcopy(raw) for raw in self._permissions.values())

    def respond_permission(self, request_id, decision, *, session_id):
        self._writable()
        if not _text(session_id) or session_id != self._session:
            raise ChannelFailure("CLAUDE_SESSION_MISMATCH", "Permission response does not match the bound native session")
        if request_id not in self._permissions:
            raise ChannelFailure("CLAUDE_PERMISSION_UNKNOWN", "Permission is absent, cancelled or already answered")
        if not isinstance(decision, dict):
            raise ValueError("explicit native permission decision required")
        behavior = decision.get("behavior")
        if behavior == "allow":
            valid = set(decision) == {"behavior", "updatedInput"} and isinstance(decision.get("updatedInput"), dict)
        elif behavior == "deny":
            valid = (set(decision) <= {"behavior", "message", "interrupt"}
                     and isinstance(decision.get("message"), str)
                     and ("interrupt" not in decision or type(decision["interrupt"]) is bool))
        else:
            valid = False
        if not valid:
            raise ValueError("invalid native permission decision; permission-rule changes are unsupported")
        # Consume before write; response loss never licenses a second approval.
        del self._permissions[request_id]
        self._send({"type": "control_response", "response": {
            "subtype": "success", "request_id": request_id, "response": copy.deepcopy(decision)}},
            "permission", request_id)

    def wait_result(self, *, timeout=60.0):
        self._open()
        if self._result is not None:
            return self._checked_result(self._result)
        for pending in self._permissions.values():
            raise ClaudePermissionPending(pending)
        return self._checked_result(self._wait_for(self._is_turn_result, timeout=timeout, stop_on_permission=True))

    def next_record(self, *, timeout=10.0):
        self._open()
        raw = self._channel.next_message(timeout=timeout).raw
        self._observe(raw)
        return copy.deepcopy(raw)

    def records(self):
        return tuple(copy.deepcopy(self._records))

    def cancel(self):
        """Legacy owned-process signal only; bidirectional callers use interrupt."""
        self._open()
        if self._bidirectional:
            raise ChannelFailure("CLAUDE_USE_INTERRUPT", "Bidirectional cancellation requires the native interrupt control request")
        self._channel.sigint()

    def close(self):
        self._closed = True
        return self._channel.close()

    def _open(self):
        if self._closed:
            raise ChannelClosed()

    def _writable(self):
        self._open()
        if not self._bidirectional:
            raise ChannelFailure("CLAUDE_OUTPUT_ONLY", "Bidirectional mode was not explicitly selected")

    def _send(self, payload, method, request_id):
        try:
            self._channel.send_raw(payload)
        except (ChannelClosed, FramingError, OSError) as exc:
            raise LostReceipt(method, request_id, "Native write failed; partial delivery is possible") from exc

    def _bind_session(self, raw):
        value = raw.get("session_id")
        if value is None:
            return
        if not _text(value) or (self._session is not None and value != self._session):
            raise LostReceipt(self._name, None, "Native record session does not match this channel")
        self._session = value

    @staticmethod
    def _is_turn_result(raw):
        origin = raw.get("origin")
        return (raw.get("type") == "result" and raw.get("parent_tool_use_id") is None
                and (origin is None or (isinstance(origin, dict) and origin.get("kind") == "human")))

    def _checked_result(self, raw):
        if not _text(raw.get("session_id")) or type(raw.get("is_error")) is not bool or not _text(raw.get("subtype")):
            raise LostReceipt(self._name, None, "Terminal result lacks required native identity or error facts")
        if raw["is_error"] or raw["subtype"] != "success":
            raise ClaudeStreamFailure("Claude returned a native error result", raw)
        return copy.deepcopy(raw)

    def _observe(self, raw):
        self._records.append(copy.deepcopy(raw))
        self._bind_session(raw)
        if raw.get("type") == "system" and raw.get("subtype") == "init":
            capabilities = raw.get("capabilities", [])
            if not isinstance(capabilities, list) or any(not _text(x) for x in capabilities):
                raise FramingError("Native init capabilities must be a string array")
            self._init = copy.deepcopy(raw)
        if raw.get("type") == "control_request":
            request, identity = raw.get("request"), raw.get("request_id")
            if not isinstance(request, dict) or not _text(identity):
                raise FramingError("Malformed native control request")
            if request.get("subtype") == "can_use_tool":
                if not _text(request.get("tool_name")) or not _text(request.get("tool_use_id")) or not isinstance(request.get("input"), dict):
                    raise FramingError("Malformed native permission request")
                if identity in self._permission_ids:
                    raise FramingError("Native permission request identity was replayed")
                self._permission_ids.add(identity)
                self._permissions[identity] = copy.deepcopy(raw)
        elif raw.get("type") == "control_cancel_request":
            self._permissions.pop(raw.get("request_id"), None)
        if self._is_turn_result(raw):
            if not _text(raw.get("session_id")) or type(raw.get("is_error")) is not bool or not _text(raw.get("subtype")):
                raise LostReceipt(self._name, None, "Terminal result lacks required native identity or error facts")
            self._result = copy.deepcopy(raw)
            self._active_turn = False

    def _control(self, request, *, timeout):
        self._valid_timeout(timeout)
        identity = "req_" + uuid.uuid4().hex
        self._send({"type": "control_request", "request_id": identity, "request": request}, request["subtype"], identity)
        raw = self._wait_for(lambda r: r.get("type") == "control_response"
                             and isinstance(r.get("response"), dict)
                             and r["response"].get("request_id") == identity,
                             timeout=timeout, request_id=identity)
        response = raw["response"]
        if response.get("subtype") == "error":
            raise ClaudeStreamFailure("Claude refused the native control request", raw)
        if response.get("subtype") != "success" or not isinstance(response.get("response"), (dict, type(None))):
            raise LostReceipt(request["subtype"], identity, "Malformed native control response")
        return copy.deepcopy(response.get("response") or {})

    @staticmethod
    def _valid_timeout(timeout):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")

    def _wait_for(self, predicate, *, timeout, request_id=None, stop_on_permission=False):
        self._valid_timeout(timeout)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout(self._name, request_id, timeout)
            try:
                raw = self.next_record(timeout=remaining)
            except RequestTimeout:
                continue
            except (ChannelClosed, FramingError, OSError) as exc:
                raise LostReceipt(self._name, request_id, "Native transport lost before a matching receipt") from exc
            if self._is_turn_result(raw) and raw.get("is_error") is True:
                self._checked_result(raw)
            if stop_on_permission and raw.get("request_id") in self._permissions:
                raise ClaudePermissionPending(raw)
            if predicate(raw):
                return raw
