"""测试客户端自检：ManagedChannel 自身的连接/收帧/超时/清理必须先行成立。

这些测试**不依赖产品接缝**（它们自带一个回声 WebSocket 应用），证明
`test_managed_acp_channel.py` 的通道客户端在机械上是正确的：WebSocket 经
context manager 进入、正例连接显式携带测试 bearer（回声应用 accept 前强制
校验凭据，缺/错即 4401 拒绝）、reader 线程不丢帧且保留全部已收帧、等待是真
实超时（不会因阻塞读而卡死）、relay 断开的呈现是清晰断言失败、close 退出上
下文。这样当主线测试报 TARGET MISSING 时，可以确定那是接缝缺失，而不是夹具
错误（包括不是"客户端自己没带凭据被拒"）。
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from tests.acp_orchestration.test_managed_acp_channel import (
    CHANNEL_WS_PATH, ManagedChannel, answer_for,
)

SELFTEST_TOKEN = "selftest-token"


def _echo_app() -> FastAPI:
    """A scripted relay: each request frame answers with one answer, unless
    the method says otherwise; `note:<n>` requests also pre-send n
    notification frames; `silent` never answers; `closing` drops the relay;
    `whoami` echoes back the received authorization header.  The relay
    enforces the bearer **before accept** (4401) exactly like the contract's
    production admission rule, so a client that forgot its credential can
    never pass these self-tests."""
    app = FastAPI()
    path = CHANNEL_WS_PATH.format(connectionId="{connection_id}")

    @app.websocket(path)
    async def channel(websocket: WebSocket, connection_id: str):
        if websocket.headers.get("authorization") != f"Bearer {SELFTEST_TOKEN}":
            await websocket.close(code=4401)  # before accept
            return
        await websocket.accept()
        while True:
            frame = json.loads(await websocket.receive_text())
            method = frame.get("method", "")
            if method == "closing":
                await websocket.close(code=1000)
                return
            if method.startswith("note:"):
                for k in range(int(method.split(":")[1])):
                    await websocket.send_text(json.dumps(
                        {"jsonrpc": "2.0", "method": "session/update",
                         "params": {"seq": k}}))
            if method == "silent":
                continue
            if method == "whoami":
                await websocket.send_text(json.dumps(
                    {"jsonrpc": "2.0", "id": frame["id"], "result": {
                        "auth": websocket.headers.get("authorization", "")}}))
                continue
            await websocket.send_text(json.dumps(
                {"jsonrpc": "2.0", "id": frame["id"],
                 "result": {"echo": True, "connection": connection_id}}))

    return app


def _channel(token: str | None = SELFTEST_TOKEN) -> ManagedChannel:
    client = TestClient(_echo_app())
    return ManagedChannel(server=SimpleNamespace(client=client, token=token),
                          binding={}, connection_id="selftest")


def test_websocket_enters_the_connection_context_and_relays_frames():
    channel = _channel()
    try:
        channel.send_frame({"jsonrpc": "2.0", "id": 1, "method": "x", "params": {}})
        answered = channel.answer(1, timeout=15)
        assert answered["result"] == {"echo": True, "connection": "selftest"}, answered
        # A second request proves the connection stays usable (not re-entered).
        channel.send_frame({"jsonrpc": "2.0", "id": 2, "method": "y", "params": {}})
        assert channel.answer(2, timeout=15)["result"]["echo"] is True
    finally:
        channel.close()


def test_collection_retains_every_frame_and_is_non_destructive():
    channel = _channel()
    try:
        channel.send_frame({"jsonrpc": "2.0", "id": 7, "method": "note:3", "params": {}})
        answered = channel.answer(7, timeout=15)
        assert answer_for(channel._seen, 7) is answered
        seen_once = channel.drained(settle=0.5)
        seen_twice = channel.drained(settle=0.5)
        assert seen_once == seen_twice, "drained() must never consume or lose frames"
        updates = [f for f in seen_once if f.get("method") == "session/update"]
        assert [u["params"]["seq"] for u in updates] == [0, 1, 2], \
            f"all three notifications must be retained, got {seen_once}"
    finally:
        channel.close()


def test_waits_are_real_timeouts_and_never_hang():
    channel = _channel()
    started = time.monotonic()
    try:
        channel.send_frame({"jsonrpc": "2.0", "id": 9, "method": "silent", "params": {}})
        try:
            channel.answer(9, timeout=2.0)
        except AssertionError as exc:
            assert "no answer to request id 9" in str(exc), exc
        else:
            raise AssertionError("answer() must fail when no frame arrives")
        elapsed = time.monotonic() - started
        assert elapsed < 8.0, f"the timeout must bound the wait, took {elapsed:.1f}s"
    finally:
        channel.close()


def test_a_dropped_relay_surfaces_as_a_clean_assertion_on_the_next_wait():
    channel = _channel()
    try:
        channel.send_frame({"jsonrpc": "2.0", "id": 1, "method": "closing", "params": {}})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                channel.collect(timeout=1.0)
            except AssertionError as exc:
                assert "relay ended" in str(exc), exc
                break
            time.sleep(0.1)
        else:
            raise AssertionError("the closed relay must surface on the next wait")
    finally:
        channel.close()


def test_close_exits_the_connection_context_and_is_idempotent():
    channel = _channel()
    channel.send_frame({"jsonrpc": "2.0", "id": 1, "method": "x", "params": {}})
    channel.answer(1, timeout=15)
    assert channel._ws is not None and channel._ws_cm is not None
    channel.close()
    assert channel._ws is None and channel._ws_cm is None
    channel.close()  # teardown-safe: closing twice must not raise


def test_connecting_to_an_absent_relay_reports_target_missing_without_hanging():
    client = TestClient(FastAPI())  # no channel route at all
    channel = ManagedChannel(server=SimpleNamespace(client=client),
                             binding={}, connection_id="missing")
    started = time.monotonic()
    try:
        channel.send_frame({"jsonrpc": "2.0", "id": 1, "method": "x", "params": {}})
    except AssertionError as exc:
        assert "TARGET MISSING" in str(exc), exc
    else:
        raise AssertionError("send over an absent relay must fail cleanly")
    finally:
        channel.close()
    assert time.monotonic() - started < 8.0, "a missing relay must not hang the client"


def test_channel_client_carries_the_bearer_and_unsigned_attach_is_refused():
    """授权正例的自证：客户端连接**确实携带** bearer（回声应用 accept 前强制
    校验并把收到的请求头原样回显）；缺凭据/错凭据的连接在 accept 前被 4401
    拒绝，客户端清晰失败且不挂起。主线未授权反例由
    test_channel_ws_admission_requires_authorization 独立覆盖。"""
    from tests.acp_orchestration.test_access_authorization import ws_close_code
    # 正例：whoami 回显证明连接头随 websocket 一并送达。
    channel = _channel()
    try:
        channel.send_frame({"jsonrpc": "2.0", "id": 1, "method": "whoami", "params": {}})
        answered = channel.answer(1, timeout=15)
        assert answered["result"]["auth"] == f"Bearer {SELFTEST_TOKEN}", (
            f"the test client must attach its bearer credential, the relay saw "
            f"{answered['result']['auth']!r}")
    finally:
        channel.close()
    # 反例：同一条 relay，缺/错凭据在 accept 前被拒（4401）。
    url = "ws://127.0.0.1" + CHANNEL_WS_PATH.format(connectionId="selftest")
    relay_only = SimpleNamespace(client=TestClient(_echo_app()))
    assert ws_close_code(relay_only, url, {}) == 4401, \
        "the relay must refuse an unsigned attach before accept"
    assert ws_close_code(relay_only, url, {"authorization": "Bearer wrong"}) == 4401, \
        "the relay must refuse a wrong bearer before accept"
    # 客户端视角：被拒的连接清晰失败、不挂起（与缺 relay 同类呈现）。
    unsigned = _channel(token=None)
    started = time.monotonic()
    try:
        unsigned.send_frame({"jsonrpc": "2.0", "id": 1, "method": "x", "params": {}})
    except AssertionError as exc:
        assert "TARGET MISSING" in str(exc), exc
    else:
        raise AssertionError("an unsigned attach must fail cleanly")
    finally:
        unsigned.close()
    assert time.monotonic() - started < 8.0, "a refused attach must not hang the client"
