"""Explicit adapter of the pinned public Claude Agent SDK.

No import, subprocess, credential lookup, or event-loop thread at module import.
The SDK must remain in one async context (upstream client.py contract).  Its
default subprocess transport merges the parent environment, so it is never used
here. Deployment supplies isolated transport and a gate covering EVERY native
write, including SDK control/callback traffic. No fallback to stream_json.
"""
from __future__ import annotations

import asyncio
from importlib import metadata
import json
from typing import Mapping
from .native_identity import _native_identity

SDK_VERSION = "0.2.163"
SDK_SOURCE_COMMIT = "9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b"




class SdkRuntimeUnavailable(RuntimeError):
    code = "CLAUDE_SDK_UNAVAILABLE"


class SdkOutcomeUnknown(RuntimeError):
    code = "CLAUDE_OUTCOME_UNKNOWN"


class FencedSdkTransport:
    """SDK's publicly exposed custom Transport, with async dispatch fencing.

    ``native`` implements connect/write/read_messages/close/is_ready/end_input.
    ``authority.dispatch_guard(raw_frame)`` is an async context manager which
    rechecks lease, epoch, activation and full native effects and holds the
    write fence through the actual write. A boolean or caller token is no port.
    Native close must close this connection's owned transport only; completion
    of close is never a stop/release result.
    """
    def __init__(self, native, authority):
        if (native is None or authority is None or not callable(getattr(authority, "dispatch_guard", None))
                or any(not callable(getattr(native, name, None)) for name in
                       ("connect", "write", "read_messages", "close", "is_ready", "end_input"))):
            raise SdkRuntimeUnavailable("explicit isolated native transport and dispatch authority required")
        self.__native, self.__authority = native, authority

    async def connect(self):
        # Creation is separately admitted by the durable prepare/start claim.
        # This method only opens a transport already owned by that operation.
        async with self.__authority.dispatch_guard({"type": "ordessa_transport_connect"}):
            await self.__native.connect()

    async def write(self, data):
        if not isinstance(data, str) or not data.endswith("\n"):
            raise ValueError("native SDK write requires complete JSONL frames")
        # Native framing is LF, not Unicode line breaking. U+2028/U+2029
        # inside JSON strings must remain untouched.
        frame = data[:-1]
        if not frame or "\n" in frame:
            raise ValueError("one native frame per fenced dispatch required")
        try:
            data.encode("utf-8", errors="strict")
            payload = json.loads(frame)
            # json.loads accepts NaN/Infinity and overflowing numeric literals;
            # reject them before authority or native dispatch.
            json.dumps(payload, allow_nan=False, ensure_ascii=False).encode("utf-8", errors="strict")
        except (UnicodeError, ValueError):
            raise ValueError("native frame requires valid UTF-8 and finite JSON") from None
        if not isinstance(payload, dict):
            raise ValueError("native SDK frame must be an object")
        async with self.__authority.dispatch_guard(payload):
            await self.__native.write(data)

    def read_messages(self):
        return self.__native.read_messages()

    async def close(self):
        await self.__native.close()

    def is_ready(self):
        return self.__native.is_ready()

    async def end_input(self):
        # Ending input may terminate a run; it is an effect, not a read.
        async with self.__authority.dispatch_guard({"type": "ordessa_transport_end_input"}):
            await self.__native.end_input()


def installed_sdk_factory():
    """Load a specifically admitted existing SDK; never install/update it."""
    try:
        version = metadata.version("claude-agent-sdk")
    except metadata.PackageNotFoundError:
        raise SdkRuntimeUnavailable("pinned Claude Agent SDK is not installed") from None
    if version != SDK_VERSION:
        raise SdkRuntimeUnavailable("installed Claude Agent SDK version is outside the verified source pin")
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
    return ClaudeSDKClient, ClaudeAgentOptions


class ClaudeSdkSession:
    """One real SDK client's native unit channel; core remains the operation owner.

    SDK acknowledgment of a set_model/set_permission_mode is not readback.
    ``mutate_configuration`` therefore reports unknown. Durable reconciliation
    and actual snapshots belong to the existing injected Unit owner, which must
    preserve original operation/request/scope identities.
    """
    def __init__(self, *, transport: FencedSdkTransport, options: Mapping | None = None,
                 sdk_factory=None, native_session_id=None):
        if not isinstance(transport, FencedSdkTransport):
            raise SdkRuntimeUnavailable("a fenced isolated SDK transport is required")
        if native_session_id is not None and not _native_identity(native_session_id):
            raise ValueError("native session identity must be explicit")
        options = dict(options or {})
        allowed = {"model", "system_prompt", "permission_mode", "can_use_tool"}
        if set(options) - allowed or options.get("permission_mode", "default") != "default":
            raise SdkRuntimeUnavailable("only explicit supported SDK options and default permission mode are admitted")
        # A callback is mandatory: absence must not silently approve prompts.
        if not callable(options.get("can_use_tool")):
            raise SdkRuntimeUnavailable("explicit native permission decision callback required")
        self.__transport, self.__options = transport, options
        self.__factory = sdk_factory or installed_sdk_factory
        self.__client = None
        self.__task = None
        self.__connect_attempted = False
        self.__session_id = native_session_id
        self.__turn_pending = False
        self.__identity_unknown = False
        self.__closed = False
        self.__lock = asyncio.Lock()

    def _context(self):
        if self.__task is not asyncio.current_task():
            raise SdkRuntimeUnavailable("SDK unit must remain in its original async task context")
        if self.__closed or self.__client is None:
            raise SdkRuntimeUnavailable("SDK unit is not connected")

    async def open(self):
        if self.__connect_attempted:
            raise SdkOutcomeUnknown("original SDK connect attempt cannot be repeated")
        factory, options_type = self.__factory()
        options = options_type(**self.__options)
        self.__client = factory(options=options, transport=self.__transport)
        self.__task = asyncio.current_task()
        self.__connect_attempted = True
        try:
            # No prompt: connection creation is not a model task.
            await self.__client.connect()
        except BaseException:
            # Upstream may have spawned/opened before failing; never retry.
            raise SdkOutcomeUnknown("SDK connection outcome is unknown; reconcile original owner binding") from None

    async def submit(self, native_payload):
        self._context()
        if self.__identity_unknown:
            raise SdkOutcomeUnknown("native session evidence is unresolved; no new input permitted")
        if not isinstance(native_payload, Mapping) or set(native_payload) != {"content", "session_id"}:
            raise ValueError("explicit native content/session payload required")
        session = native_payload["session_id"]
        if not isinstance(session, str) or not session or not isinstance(native_payload["content"], str) or not native_payload["content"]:
            raise ValueError("nonempty native content/session required")
        if self.__session_id is not None and session != self.__session_id:
            raise SdkRuntimeUnavailable("native session differs from unit binding")
        async with self.__lock:
            if self.__turn_pending:
                raise SdkOutcomeUnknown("previous native turn unresolved; do not resend")
            if self.__session_id is None and session != "default":
                self.__session_id = session
            self.__turn_pending = True  # before write, including cancellation.
            try:
                await self.__client.query(native_payload["content"], session_id=session)
            except BaseException:
                raise SdkOutcomeUnknown("native input outcome is unknown; no resend permitted") from None

    async def receive_native(self):
        self._context()
        async for message in self.__client.receive_messages():
            # Preserve typed native messages. Result ends a human turn only,
            # not process/background lifecycle. Never infer readiness here.
            identity = getattr(message, "session_id", None)
            if getattr(message, "subtype", None) == "init":
                # The pinned SDK's SystemMessage has no session_id member:
                # message_parser.py retains the original native init in data.
                # Do not substitute the requested session or 'default'.
                raw = getattr(message, "data", None)
                if (not isinstance(raw, Mapping) or raw.get("type") != "system"
                        or raw.get("subtype") != "init" or not _native_identity(raw.get("session_id"))
                        or (identity is not None and identity != raw["session_id"])):
                    self.__identity_unknown = True
                    raise SdkOutcomeUnknown("native initialization lacks consistent session identity")
                identity = raw["session_id"]
            if identity is not None:
                if not _native_identity(identity) or (self.__session_id is not None and identity != self.__session_id):
                    self.__identity_unknown = True
                    raise SdkOutcomeUnknown("native session evidence does not match unit")
                self.__session_id = identity
            origin = getattr(message, "origin", None)
            if (type(message).__name__ == "ResultMessage"
                    and (origin is None or (isinstance(origin, Mapping) and origin.get("kind") == "human"))):
                # SDK ResultMessage has no durable operation receipt. Its own
                # turn identity is sufficient only for this local pending guard.
                if not isinstance(identity, str) or not identity:
                    self.__identity_unknown = True
                    raise SdkOutcomeUnknown("terminal turn lacks native session evidence")
                self.__turn_pending = False
            yield message

    @property
    def native_session_id(self):
        """Read-only binding observation, not Unit/process readiness evidence."""
        return self.__session_id

    async def interrupt(self):
        self._context()
        await self.__client.interrupt()
        # ACK does not clear pending or prove the unit stopped.
        return {"outcome": "unknown", "scope": "turn"}

    async def mutate_configuration(self, kind, action, payload):
        self._context()
        if self.__identity_unknown:
            raise SdkOutcomeUnknown("native session evidence is unresolved; configuration write refused")
        async with self.__lock:
            if kind == "claude.model" and action in {"value", "reset"}:
                if action == "value" and (not isinstance(payload, Mapping) or set(payload) != {"model"}
                                          or not isinstance(payload["model"], str) or not payload["model"]):
                    raise ValueError("model value requires an explicit nonempty model")
                await self.__client.set_model(None if action == "reset" else payload["model"])
            else:
                raise SdkRuntimeUnavailable("native configuration action is not implemented")
            return {"outcome": "unknown", "confirmation": "ackOnly"}

    async def disconnect(self):
        self._context()
        self.__closed = True
        await self.__client.disconnect()
        return {"outcome": "disconnected", "unitStopped": "unknown"}
