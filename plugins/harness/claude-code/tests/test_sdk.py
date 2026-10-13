"""C only: explicit injected public SDK shape, no actual SDK/CLI/model."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json

import pytest

from ordessa_harness_claude_code.sdk import (
    ClaudeSdkSession, FencedSdkTransport, SdkRuntimeUnavailable, SdkOutcomeUnknown,
    installed_sdk_factory,
)


class Gate:
    def __init__(self):
        self.allowed = True
        self.payloads = []

    @asynccontextmanager
    async def dispatch_guard(self, payload):
        if not self.allowed:
            raise SdkRuntimeUnavailable("lease revoked")
        self.payloads.append(payload)
        yield


class Native:
    def __init__(self):
        self.writes = []
        self.messages = []
        self.fail = False
        self.closed = False

    async def connect(self):
        pass

    async def write(self, data):
        self.writes.append(data)
        if self.fail:
            raise OSError("controlled partial write")

    async def read_messages(self):
        for message in self.messages:
            yield message

    async def close(self):
        self.closed = True

    def is_ready(self):
        return not self.closed

    async def end_input(self):
        pass


@dataclass
class ResultMessage:
    session_id: str
    origin: dict | None = None


@dataclass
class SystemMessage:
    subtype: str
    data: dict


class Client:
    def __init__(self, *, options, transport):
        self.options, self.transport = options, transport

    async def connect(self):
        await self.transport.connect()
        await self.transport.write(json.dumps({"type": "control_request", "request": {"subtype": "initialize"}}) + "\n")

    async def query(self, prompt, session_id):
        await self.transport.write(json.dumps({"type": "user", "session_id": session_id, "content": prompt}) + "\n")

    async def interrupt(self):
        await self.transport.write(json.dumps({"type": "control_request", "request": {"subtype": "interrupt"}}) + "\n")

    async def set_model(self, model):
        await self.transport.write(json.dumps({"type": "control_request", "request": {"subtype": "set_model", "model": model}}) + "\n")

    def receive_messages(self):
        return self.transport.read_messages()

    async def disconnect(self):
        await self.transport.close()


async def decision(*args):
    raise SdkRuntimeUnavailable("explicit decision absent")


def setup():
    native, gate = Native(), Gate()
    transport = FencedSdkTransport(native, gate)
    session = ClaudeSdkSession(transport=transport, options={"can_use_tool": decision},
        sdk_factory=lambda: (Client, lambda **kw: kw), native_session_id="session-1")
    return session, native, gate


def test_sdk_adapter_no_fallback_and_callback_required():
    native, gate = Native(), Gate()
    with pytest.raises(SdkRuntimeUnavailable):
        ClaudeSdkSession(transport=FencedSdkTransport(native, gate))
    with pytest.raises(SdkRuntimeUnavailable):
        ClaudeSdkSession(transport=native, options={"can_use_tool": decision})


@pytest.mark.parametrize("options", [
    {"permission_mode": "bypassPermissions", "can_use_tool": decision},
    {"allowed_tools": ["Bash"], "can_use_tool": decision},
    {"env": {"TOKEN": "forbidden"}, "can_use_tool": decision},
    {"continue_conversation": True, "can_use_tool": decision},
])
def test_unadmitted_sdk_options_refuse_before_factory(options):
    native, gate = Native(), Gate()
    with pytest.raises(SdkRuntimeUnavailable):
        ClaudeSdkSession(transport=FencedSdkTransport(native, gate), options=options,
                         sdk_factory=lambda: pytest.fail("must not load SDK"))


def test_missing_or_different_sdk_never_imports_or_installs(monkeypatch):
    from importlib import metadata
    def missing(name):
        raise metadata.PackageNotFoundError(name)
    monkeypatch.setattr(metadata, "version", missing)
    with pytest.raises(SdkRuntimeUnavailable, match="not installed"):
        installed_sdk_factory()
    monkeypatch.setattr(metadata, "version", lambda name: "99")
    with pytest.raises(SdkRuntimeUnavailable, match="outside"):
        installed_sdk_factory()


def test_native_model_ack_is_unknown_no_config_truth():
    async def scenario():
        session, native, gate = setup()
        await session.open()
        result = await session.mutate_configuration("claude.model", "value", {"model": "test-model"})
        assert result == {"outcome": "unknown", "confirmation": "ackOnly"}
        assert gate.payloads[-1]["request"]["subtype"] == "set_model"
        assert len(native.writes) == 2
        await session.disconnect()
    asyncio.run(scenario())


def test_partial_write_keeps_unknown_no_new_prompt_or_connect():
    async def scenario():
        session, native, gate = setup()
        await session.open()
        native.fail = True
        with pytest.raises(SdkOutcomeUnknown):
            await session.submit({"content": "first", "session_id": "session-1"})
        with pytest.raises(SdkOutcomeUnknown):
            await session.submit({"content": "changed", "session_id": "session-1"})
        with pytest.raises(SdkOutcomeUnknown):
            await session.open()
        assert len(native.writes) == 2
        await session.disconnect()
    asyncio.run(scenario())


def test_background_result_interrupt_not_turn_completion():
    async def scenario():
        session, native, gate = setup()
        await session.open()
        await session.submit({"content": "first", "session_id": "session-1"})
        assert (await session.interrupt())["outcome"] == "unknown"
        native.messages = [ResultMessage("session-1", {"kind": "task-notification"})]
        assert len([msg async for msg in session.receive_native()]) == 1
        with pytest.raises(SdkOutcomeUnknown):
            await session.submit({"content": "changed", "session_id": "session-1"})
        native.messages = [ResultMessage("session-1")]
        assert len([msg async for msg in session.receive_native()]) == 1
        await session.submit({"content": "next", "session_id": "session-1"})
        assert (await session.disconnect())["unitStopped"] == "unknown"
    asyncio.run(scenario())


def test_revocation_covers_sdk_control_input_and_end_input():
    async def scenario():
        session, native, gate = setup()
        await session.open()
        gate.allowed = False
        with pytest.raises(SdkRuntimeUnavailable):
            await session.interrupt()
        with pytest.raises(SdkRuntimeUnavailable):
            await session.mutate_configuration("claude.model", "reset", None)
        assert len(native.writes) == 1
        await session.disconnect()
    asyncio.run(scenario())


def test_sdk_same_async_context_enforced():
    async def scenario():
        session, native, gate = setup()
        await session.open()
        with pytest.raises(SdkRuntimeUnavailable, match="original async"):
            await asyncio.create_task(session.interrupt())
        await session.disconnect()
    asyncio.run(scenario())


def test_session_mismatch_refuses_without_write():
    async def scenario():
        session, native, gate = setup()
        await session.open()
        with pytest.raises(SdkRuntimeUnavailable):
            await session.submit({"content": "hello", "session_id": "another"})
        assert len(native.writes) == 1
        await session.disconnect()
    asyncio.run(scenario())


def test_explicit_session_is_bound_before_dispatch_and_receive():
    async def scenario():
        native, gate = Native(), Gate()
        session = ClaudeSdkSession(transport=FencedSdkTransport(native, gate), options={"can_use_tool": decision},
                                  sdk_factory=lambda: (Client, lambda **kw: kw))
        await session.open()
        await session.submit({"content": "hello", "session_id": "explicit-session"})
        native.messages = [ResultMessage("different-session")]
        with pytest.raises(SdkOutcomeUnknown):
            [msg async for msg in session.receive_native()]
        with pytest.raises(SdkOutcomeUnknown):
            await session.submit({"content": "resend", "session_id": "explicit-session"})
        assert len(native.writes) == 2
        await session.disconnect()
    asyncio.run(scenario())


def unbound_setup():
    native, gate = Native(), Gate()
    session = ClaudeSdkSession(transport=FencedSdkTransport(native, gate), options={"can_use_tool": decision},
                              sdk_factory=lambda: (Client, lambda **kw: kw))
    return session, native, gate


def test_sdk_init_data_binds_actual_session_and_preserves_message():
    async def scenario():
        session, native, gate = unbound_setup()
        await session.open()
        assert session.native_session_id is None  # control connect does not fabricate session.
        raw = {"type": "system", "subtype": "init", "session_id": "actual-session",
               "future_field": {"keep": [1, 2]}}
        message = SystemMessage("init", raw)
        native.messages = [message]
        observed = [item async for item in session.receive_native()]
        assert observed == [message] and observed[0] is message
        assert message.data is raw and raw["future_field"] == {"keep": [1, 2]}
        assert session.native_session_id == "actual-session"
        await session.submit({"content": "once", "session_id": "actual-session"})
        assert len(native.writes) == 2
        await session.disconnect()
    asyncio.run(scenario())


@pytest.mark.parametrize("raw", [
    {"type": "system", "subtype": "init"},
    {"type": "system", "subtype": "init", "session_id": None},
    {"type": "system", "subtype": "init", "session_id": ""},
    {"type": "system", "subtype": "init", "session_id": "default"},
    {"type": "system", "subtype": "init", "session_id": " whitespace "},
    {"type": "system", "subtype": "init", "session_id": "\ud800"},
    {"type": "other", "subtype": "init", "session_id": "invented"},
])
def test_sdk_init_invalid_native_identity_does_not_license_new_input(raw):
    async def scenario():
        session, native, gate = unbound_setup()
        await session.open()
        native.messages = [SystemMessage("init", raw)]
        with pytest.raises(SdkOutcomeUnknown, match="initialization"):
            [item async for item in session.receive_native()]
        assert session.native_session_id is None
        with pytest.raises(SdkOutcomeUnknown):
            await session.submit({"content": "replacement", "session_id": "default"})
        with pytest.raises(SdkOutcomeUnknown):
            await session.mutate_configuration("claude.model", "reset", None)
        assert len(native.writes) == 1  # no query, prompt, second initialize or resend.
        await session.disconnect()
    asyncio.run(scenario())


def test_sdk_init_cannot_replace_original_session_or_settle_pending_input():
    async def scenario():
        session, native, gate = setup()
        await session.open()
        await session.submit({"content": "original", "session_id": "session-1"})
        native.messages = [SystemMessage("init", {"type": "system", "subtype": "init", "session_id": "replacement"})]
        with pytest.raises(SdkOutcomeUnknown):
            [item async for item in session.receive_native()]
        assert session.native_session_id == "session-1"
        with pytest.raises(SdkOutcomeUnknown):
            await session.submit({"content": "new", "session_id": "session-1"})
        assert len(native.writes) == 2
        await session.disconnect()
    asyncio.run(scenario())


def test_consistent_repeated_init_does_not_complete_turn():
    async def scenario():
        session, native, gate = setup()
        await session.open()
        await session.submit({"content": "original", "session_id": "session-1"})
        raw = {"type": "system", "subtype": "init", "session_id": "session-1"}
        native.messages = [SystemMessage("init", raw), SystemMessage("init", raw)]
        assert len([item async for item in session.receive_native()]) == 2
        with pytest.raises(SdkOutcomeUnknown):
            await session.submit({"content": "new", "session_id": "session-1"})
        assert len(native.writes) == 2
        await session.disconnect()
    asyncio.run(scenario())


def test_unknown_system_data_preserved_not_reinterpreted_as_init():
    async def scenario():
        session, native, gate = unbound_setup()
        await session.open()
        raw = {"type": "system", "subtype": "future", "session_id": "future-unverified", "unknown": ["verbatim"]}
        message = SystemMessage("future", raw)
        native.messages = [message]
        observed = [item async for item in session.receive_native()]
        assert observed[0] is message and observed[0].data is raw
        assert session.native_session_id is None and len(native.writes) == 1
        await session.disconnect()
    asyncio.run(scenario())


@pytest.mark.parametrize("frame", ["{}", "[]\n", "{}\n{}\n", '{"x": NaN}\n',
    '{"x": Infinity}\n', '{"x": 1e400}\n', '{"x": "\ud800"}\n'])
def test_transport_requires_one_object_frame(frame):
    async def scenario():
        native, gate = Native(), Gate()
        with pytest.raises(ValueError):
            await FencedSdkTransport(native, gate).write(frame)
        assert native.writes == []
    asyncio.run(scenario())


@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_unicode_line_separator_is_not_native_frame_separator(separator):
    async def scenario():
        native, gate = Native(), Gate()
        frame = json.dumps({"content": "before" + separator + "after"}, ensure_ascii=False) + "\n"
        await FencedSdkTransport(native, gate).write(frame)
        assert native.writes == [frame]
        assert gate.payloads == [{"content": "before" + separator + "after"}]
    asyncio.run(scenario())
