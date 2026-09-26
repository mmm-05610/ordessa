"""目标验收主线：客户端经过 Server 的受管理通道，与受控 ACP 对端双向通信。

按主会话定稿的接缝契约逐条立测：

1. 发现与项目列表属编排控制面，不依赖 ACP 通道（现状即应通过）。
2. 建立/取得通道必须显式提供 harnessId、projectId；Server 校验授权与项目、
   解析权威 cwd，再让 Harness 插件按该 cwd 启动或连接；返回绑定信息和双向
   ACP 通道。
3. 建立通道不代替客户端 initialize、不创建原生会话、不发送 prompt；这些
   ACP 操作由前端发起、Server 透传。
4. 客户端 ACP 帧双向原样透传——断言为**完整 JSON 帧相等**（收到的帧必须逐字节
   等于对端发出的帧），不做类型换算、不做子串检查。
5. 通道的 Harness/项目绑定不可悄悄更换；其他项目取得其他绑定通道。
6. 连接 ID 与原生 session ID 分开。
7. 前端切换展示不构成释放指令（不自动取消/重启/重发）；显式 release 才按
   所有权释放。
8. 补测：项目绑定、未授权零启动、双通道隔离（含两通道同用相同 JSON-RPC 请求
   id）、显式释放。
9. Workcore 边界：一次通道运行对应一次 execution。建立后**立即锁定**该通道
   的 execution 身份（ledger 差集中的唯一 id）与进程身份（pid 集合）；多轮
   prompt/审批前后两个集合均不变——"每个进程都有一条启动记录"不算数。
   显式 release 须有确认，释放后 A 不得再有任何往返、B 须仍可实际往返、
   其他 execution 不受影响；被杀进程同样只结束运行记录，在飞请求不得被代答
   成成功。运行记录的结束是**正向断言**：进入合法终态词表（正常关闭 /
   异常结束）并写明 endReason——"通道运行正常结束"不等于"内部任务全部成
   功"，正常结束用例故意留下未完成的在飞任务来证明这一区分。
10. 新 ACP WebSocket 自身有授权正反例：缺 token / 非 loopback Origin 在
    accept 前被拒，未授权客户端不能接入既有连接、不能释放；持牌客户端可
    完整往返。不复用旧 event-stream 的认证结论。

接缝现状：定稿契约要求的生产接缝**尚不存在**（wire/1 没有通道方法，
event-stream 只送投影事件而非原样 ACP 帧）。除控制面与测试客户端自检外，
本节测试以"TARGET MISSING"清晰失败，不 skip、不 xfail、不冒充通过。所有
对签名敏感的代码集中在 `open_managed_channel`/`ManagedChannel` 一处；最小
签名与前端对齐后只改这一处，全部验收即变为可执行。

`test_channel_client_selftest.py`（同目录）先自证本文件的测试客户端本身
（WS 上下文生命周期、收帧不丢、真实超时、清理），避免 TARGET MISSING 掩盖
夹具自身错误。
"""
from __future__ import annotations

import glob as _glob
import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tests.acp_orchestration.conftest import (
    HELLO, ServerHandle, peer_events, session_new_events, pid_alive, wait_until,
)

HARNESS_ID = "pi"

# -- 待定稿接缝的最小签名（与前端对齐后仅此一处变化） ------------------------

CHANNEL_OPEN_METHOD = "acp.channel.open"        # {harnessId, projectId} -> 绑定+通道
CHANNEL_RELEASE_METHOD = "acp.channel.release"  # {connectionId} -> 按所有权释放并确认
CHANNEL_WS_PATH = "/wire/v1/acp-channel/{connectionId}"  # 双向原样 ACP 帧；
# 该 WS 复用 bearer 认证边界（缺 token 4401 / 非 loopback Origin 4403，accept 前
# 拒绝；既有 connectionId 不可被未授权客户端接入）——由 admission 测试钉住。


class _RelayClosed:
    """Sentinel: the inbound reader ended (no relay, or the relay closed)."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc


_NONE = object()


@dataclass
class ManagedChannel:
    """One Server-managed bidirectional ACP channel, as the contract defines it.

    Client mechanics (pinned by test_channel_client_selftest.py):
    - the websocket is entered as a context manager (Starlette initialises the
      transport in ``__enter__``; sending without entering is not a channel).
    - a daemon reader thread pumps every inbound frame into ``_seen`` plus a
      queue, so collection never consumes/loses a frame.
    - every wait is a real timeout (``queue.get(timeout=…)``); no assertion
      depends on a blocking ``receive_text`` returning.
    - ``close()`` exits the context manager; test teardown closes every
      channel this fixture created.
    """

    server: Any
    binding: dict[str, Any]
    connection_id: str
    _ws_cm: Any = None
    _ws: Any = None
    _reader: Any = None
    _inbox: queue.Queue = field(default_factory=queue.Queue)
    _seen: list[dict] = field(default_factory=list)

    # -- transport ---------------------------------------------------------

    def _ensure_open(self) -> None:
        if self._ws is not None:
            return
        url = CHANNEL_WS_PATH.format(connectionId=self.connection_id)
        # 正例自己必须携带授权凭据：TestClient 没有默认认证头，relay 的
        # accept 前鉴权会（正确地）拒绝匿名连接。未授权反例由
        # test_channel_ws_admission_requires_authorization 独立覆盖。
        headers = {}
        token = getattr(self.server, "token", None)
        if token:
            headers["authorization"] = "Bearer " + token
        try:
            self._ws_cm = self.server.client.websocket_connect(url, headers=headers)
            self._ws = self._ws_cm.__enter__()
        except BaseException as exc:  # noqa: BLE001 - a missing relay is a missing seam
            self._ws_cm = None
            self._ws = None
            raise AssertionError(
                f"TARGET MISSING: no bidirectional ACP relay at {url!r} "
                f"({type(exc).__name__}: {exc})") from exc
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        try:
            while True:
                self._inbox.put(json.loads(self._ws.receive_text()))
        except BaseException as exc:  # noqa: BLE001 - surfaced on the next wait
            self._inbox.put(_RelayClosed(exc))

    def send_frame(self, frame: dict) -> None:
        """The client's own ACP frame enters the channel verbatim."""
        self._ensure_open()
        self._ws.send_text(json.dumps(frame, ensure_ascii=False))

    def _next(self, timeout: float):
        try:
            item = self._inbox.get(timeout=max(timeout, 0.001))
        except queue.Empty:
            return _NONE
        if isinstance(item, _RelayClosed):
            raise AssertionError(
                f"TARGET MISSING: channel {self.connection_id!r} relay ended "
                f"({type(item.exc).__name__}: {item.exc})")
        return item

    # -- collection (never loses a frame) ------------------------------------

    def collect(self, *, until: Any = None, timeout: float = 30.0,
                settle: float = 0.5) -> list[dict]:
        """Wait until ``until(frame)`` matches a seen frame or the deadline.

        Every frame is retained in ``_seen`` before being visible to any
        caller, so repeated collection is non-destructive.  With no predicate,
        returns after one quiet ``settle`` interval (or ``timeout``).
        """
        deadline = time.monotonic() + timeout
        while True:
            if until is not None and any(until(f) for f in self._seen):
                return list(self._seen)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return list(self._seen)
            item = self._next(remaining)
            if item is _NONE:
                return list(self._seen)
            self._seen.append(item)

    def drained(self, *, settle: float = 0.5) -> list[dict]:
        """All frames received so far, including any still in the inbox."""
        while True:
            item = self._next(settle)
            if item is _NONE:
                return list(self._seen)
            self._seen.append(item)

    def answer(self, frame_id: int, *, timeout: float = 30.0) -> dict:
        seen = self.collect(
            until=lambda f: f.get("id") == frame_id and "method" not in f,
            timeout=timeout)
        return answer_for(seen, frame_id)

    # -- lifecycle -----------------------------------------------------------

    def release(self) -> dict:
        """Explicit, ownership-scoped release; the seam must acknowledge."""
        answer = self.server.wire("acp.channel.release",
                                  {"connectionId": self.connection_id})
        assert "result" in answer, f"release must be acknowledged, got {answer}"
        return answer["result"]

    def close(self) -> None:
        """Local cleanup of the test's own connection (not a Server release)."""
        cm, self._ws_cm, self._ws = self._ws_cm, None, None
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except BaseException:  # noqa: BLE001 - cleanup must not mask results
                pass


def open_managed_channel(server: ServerHandle, *, harness_id: str,
                         project_id: str) -> ManagedChannel:
    """Acquire the contract's channel: explicit harnessId + projectId in,
    binding + bidirectional ACP channel out."""
    answer = server.wire("acp.channel.open", {
        "harnessId": harness_id, "projectId": project_id,
    })
    if "error" in answer:
        detail = answer["error"]
        if "is not a wire/1 method" in str(detail.get("message", "")):
            raise AssertionError(
                f"TARGET MISSING: the finalized seam has no channel method yet "
                f"({CHANNEL_OPEN_METHOD!r} refused: {detail})")
        raise AssertionError(f"channel open failed: {answer}")
    result = answer["result"]
    connection_id = result.get("connectionId") or result.get("connection", {}).get("id")
    binding = result.get("binding") or result
    assert connection_id, f"channel open must return a connection id: {result}"
    return ManagedChannel(server=server, binding=binding,
                          connection_id=str(connection_id))


@pytest.fixture
def channels():
    """Tracks every channel a test opens and closes its local websocket."""
    created: list[ManagedChannel] = []

    def make(server: ServerHandle, *, harness_id: str = HARNESS_ID,
             project_id: str) -> ManagedChannel:
        channel = open_managed_channel(server, harness_id=harness_id,
                                       project_id=project_id)
        created.append(channel)
        return channel

    yield make
    for channel in created:
        channel.close()


# -- shared frame/evidence helpers --------------------------------------------


def acp_frame(frame_id: int, method: str, params: dict) -> dict:
    return {"jsonrpc": "2.0", "id": frame_id, "method": method, "params": params}


def initialize_frame(frame_id: int) -> dict:
    return acp_frame(frame_id, "initialize",
                     {"protocolVersion": 1, "clientCapabilities": {}})


def session_new_frame(frame_id: int, project: Path) -> dict:
    return acp_frame(frame_id, "session/new",
                     {"cwd": str(project.resolve()), "mcpServers": []})


def prompt_frame(frame_id: int, session_id: str, text: str) -> dict:
    return acp_frame(frame_id, "session/prompt",
                     {"sessionId": session_id,
                      "prompt": [{"type": "text", "text": text}]})


def answer_for(frames: list[dict], frame_id: int) -> dict:
    matches = [f for f in frames if f.get("id") == frame_id and "method" not in f]
    assert matches, f"no answer to request id {frame_id} in {[f.get('id') for f in frames]}"
    return matches[0]


#: The `agentInfo` the controlled peer fixture actually emits
#: (`fixtures/bidirectional_acp_peer.mjs`, the `initialize` handler).
#: Comparing the WHOLE object pins "arrive unchanged" strictly: any added,
#: dropped or rewritten member fails, which a single-field probe would miss.
PEER_AGENT_INFO = {
    "name": "hd003-peer", "version": "test",
    "vendorExtensions": {"hd003": True},
}


def open_session(channel: ManagedChannel, project: Path, *, frame_id: int = 1):
    """Client-driven setup over the channel: initialize then session/new, with
    the given (client-chosen) JSON-RPC ids."""
    channel.send_frame(initialize_frame(frame_id))
    initialized = channel.answer(frame_id)
    assert initialized["result"].get("agentInfo") == PEER_AGENT_INFO, \
        "the peer's own initialize result must arrive unchanged"
    channel.send_frame(session_new_frame(frame_id + 1, project))
    session_id = channel.answer(frame_id + 1)["result"]["sessionId"]
    assert session_id, "the peer must hand back its native session id"
    return session_id


def peer_rows_by_pid(log_base: str) -> dict[int, list[dict[str, Any]]]:
    """Peer evidence grouped by the peer process that wrote it.

    Ownership is read from the evidence files themselves (name
    `<base>.<pid>.<peerId>`), never guessed from start order.
    """
    base_dir, stem = os.path.split(log_base)
    rows: dict[int, list[dict[str, Any]]] = {}
    for path in sorted(Path(base_dir).glob(_glob.escape(stem) + ".*")):
        parts = path.name.split(".")
        pid = int(parts[len(stem.split("."))])
        rows[pid] = [json.loads(line) for line in path.read_text().splitlines()
                     if line.strip()]
    return rows


def peer_pids_for(log_base: str, directory: Path) -> set[int]:
    wanted = str(directory.resolve())
    return {pid for pid, rows in peer_rows_by_pid(log_base).items()
            if any(row.get("cwd") == wanted for row in rows)}


def peer_sent_frames(rows: list[dict], match) -> list[dict]:
    return [row["frame"] for row in rows
            if row.get("dir") == "send" and match(row.get("frame", {}))]


def peer_recv_frames(rows: list[dict], method: str) -> list[dict]:
    return [row["frame"] for row in rows
            if row.get("dir") == "recv" and row.get("frame", {}).get("method") == method]


def in_flight_execution_ids(server: ServerHandle) -> set[str]:
    """The real Workcore execution ledger, read at its production seam.

    `executions.list` (wire) over the order-64 inventory is the product's own
    in-flight execution entry — this test does NOT force channel runs into a
    directly-SQL'd `server_turns` table.  The terminal state of an ended run
    record is read through `channel_run_record`/`assert_run_record_ended`
    below, the single place to adapt once the run-record seam is aligned.
    """
    rows = server.result("executions.list",
                         {"requestId": server.request_id("exec")})["executions"]
    return {row["executionId"] for row in rows}


#: proposal (pending alignment): one method that reads ONE execution's run record
CHANNEL_RUN_GET_METHOD = "executions.get"

# 运行记录终态词表（提案，唯一适配点）：
#   "closed"      —— 通道运行正常结束（显式 release/关闭；结束本身合法）
#   "interrupted" —— 通道运行因 Agent 崩溃/断连异常结束
# 两者都必须携 endReason。"运行结束"与"内部任务全部成功"是两回事：
# 成功声称词（completed/succeeded/...）不属于通道运行台账，出现即违规；
# 且正常结束用例里会留一个**未完成的在飞任务**来证明结束不被换算成成功。
RUN_END_NORMAL = {"closed"}
RUN_END_ABNORMAL = {"interrupted"}
RUN_SUCCESS_CLAIM_STATES = {"completed", "succeeded", "success", "ok", "done"}


def channel_run_record(server: ServerHandle, execution_id: str) -> dict:
    answer = server.wire("executions.get", {
        "requestId": server.request_id("run"), "executionId": execution_id,
    })
    if "error" in answer:
        if "is not a wire/1 method" in str(answer["error"].get("message", "")):
            raise AssertionError(
                f"TARGET MISSING: no seam reads the channel run record "
                f"{execution_id!r} yet ({CHANNEL_RUN_GET_METHOD!r} refused: "
                f"{answer['error']})")
        raise AssertionError(f"run record read failed: {answer}")
    return answer["result"]


def assert_run_record_ended(server: ServerHandle, execution_id: str, *,
                            normal: bool) -> dict:
    """正向断言：该运行记录进入了合法终态并写明结束原因。

    不是排除几个成功字符串——终态必须 ∈ 正常/异常结束词表（按场景精确一侧），
    endReason 必须存在；任何成功声称词都被终态词表的正向枚举天然排除。
    """
    record = channel_run_record(server, execution_id)
    state = record.get("state")
    legal = RUN_END_NORMAL if normal else RUN_END_ABNORMAL
    assert state not in RUN_SUCCESS_CLAIM_STATES, (
        f"run {execution_id!r} ended as {state!r}: ending a channel run must "
        "never be recorded as every internal task having succeeded")
    assert state in legal, (
        f"run {execution_id!r} must be POSITIVELY recorded in a legal end "
        f"state {sorted(legal)} for a {'normal' if normal else 'abnormal'} "
        f"termination, got {state!r} (record: {record})")
    assert record.get("endReason"), (
        f"the end must name its reason, got {record}")
    return record


# -- 1. 控制面：发现与项目列表不依赖 ACP 通道（现状应通过） --------------------


def test_discovery_and_project_list_work_without_any_acp_channel(server, project):
    identity = server.result("server.hello", HELLO)
    assert identity["nativeExecution"]["mode"] == "native"
    workspace_id = server.open_workspace(project)
    listed = server.result("workspaces.list", {"includeArchived": False})
    assert any(item["id"] == workspace_id for item in listed["items"]), listed
    # Discovery alone must not touch an Agent: the peer never started.
    assert peer_events(server.log_base) == [], \
        "控制面发现不得依赖或启动 ACP 通道"


def test_unauthenticated_channel_request_is_refused_and_starts_nothing(server):
    """未授权零启动的可测部分：认证在一切之前，请求不触及任何 Agent。"""
    answer = server.wire(CHANNEL_OPEN_METHOD, {
        "harnessId": HARNESS_ID, "projectId": "anything",
    }, token="wrong-token", status=401)
    assert answer["error"]["code"] == "UNAUTHENTICATED", answer
    assert answer["error"]["details"]["internalCode"] == "AUTHENTICATION_REQUIRED", answer
    time.sleep(0.5)
    assert peer_events(server.log_base) == [], \
        "an unauthenticated channel request must not start anything"


def test_unbound_project_gets_no_channel_and_starts_nothing(server, tmp_path):
    """契约：Server 先校验授权与项目。未打开/未授权的项目必须被拒且零启动
    （与错误的 token 的拒绝是两条独立路径）。"""
    stranger = tmp_path / "never-opened"
    stranger.mkdir()
    before = peer_events(server.log_base)
    answer = server.wire(CHANNEL_OPEN_METHOD, {
        "harnessId": HARNESS_ID, "projectId": str(stranger),
    })
    assert "error" in answer, (
        f"an unbound project must never obtain a channel, got {answer}")
    if "is not a wire/1 method" in str(answer["error"].get("message", "")):
        raise AssertionError(
            f"TARGET MISSING: {CHANNEL_OPEN_METHOD} does not exist yet, so the "
            "project-authorization refusal path cannot be measured")
    assert peer_events(server.log_base) == before, \
        "a refused channel open must not start anything"


# -- 2/3. 建立通道：显式绑定、不代做 ACP 操作 ---------------------------------


def test_channel_open_returns_binding_with_the_authoritative_cwd(server, project, channels):
    """契约：Server 校验项目、解析权威 cwd，返回绑定信息。"""
    workspace_id = server.open_workspace(project)
    channel = channels(server, project_id=workspace_id)
    assert channel.binding.get("harnessId") == HARNESS_ID, channel.binding
    got_cwd = channel.binding.get("cwd") or channel.binding.get("directory")
    assert got_cwd == str(Path(project).resolve()), (
        f"the binding must carry the Server-resolved authoritative cwd "
        f"{str(Path(project).resolve())!r}, got {got_cwd!r}")


def test_establishing_a_channel_performs_no_initialize_no_session_no_prompt(server, project, channels):
    """契约：建立通道后对端只可能被启动，绝不收到 Server 代做的 ACP 操作帧。"""
    workspace_id = server.open_workspace(project)
    channels(server, project_id=workspace_id)
    time.sleep(1.0)
    forbidden = {"initialize", "session/new", "session/load", "session/prompt"}
    observed = {row["frame"]["method"] for pid_rows in peer_rows_by_pid(server.log_base).values()
                for row in pid_rows if row.get("dir") == "recv"
                and isinstance(row.get("frame"), dict) and "method" in row["frame"]}
    assert not forbidden.intersection(observed), (
        f"the Server answered ACP on the client's behalf during setup: {observed}")


# -- 4. 客户端 ACP 帧双向原样透传（完整帧相等） --------------------------------


def test_client_frames_relay_verbatim_both_directions(server, project, channels):
    """每个客户端请求的应答、每个对端发出的通知帧，都必须与对端日志里
    `dir=send` 的原始帧**完整相等**（不换算类型、不查子串）。"""
    workspace_id = server.open_workspace(project)
    channel = channels(server, project_id=workspace_id)
    session_id = open_session(channel, project)
    channel.send_frame(prompt_frame(3, session_id, "scenario:meta"))
    channel.answer(3)
    channel.send_frame(prompt_frame(4, session_id, "scenario:custom-update"))
    channel.answer(4)
    seen = channel.drained()

    sent = [f for rows in peer_rows_by_pid(server.log_base).values()
            for f in peer_sent_frames(rows, lambda fr: "method" in fr)]
    assert sent, "the peer must have sent notification frames"
    missing = [f for f in sent if f not in seen]
    assert not missing, (
        f"inbound frames must arrive exactly as sent, missing verbatim: {missing}")
    # update-level _meta and the unknown sessionUpdate kind are covered by the
    # exact whole-frame comparison above; name them so a failure says which:
    assert any(f.get("params", {}).get("update", {}).get("sessionUpdate")
               == "hd003_extension" for f in sent), "fixture must emit the extension update"
    assert any("_meta" in json.dumps(f) for f in sent), "fixture must emit _meta"
    # the peer's own session/new answer reached the client byte-identical too
    new_answer = answer_for(seen, 2)
    sent_answers = [f for rows in peer_rows_by_pid(server.log_base).values()
                    for f in peer_sent_frames(rows, lambda fr: fr.get("id") == 2)]
    assert new_answer in sent_answers, \
        "outbound answers must arrive exactly as the peer sent them"


def test_native_error_identity_survives_the_relay_exact(server, project, channels):
    workspace_id = server.open_workspace(project)
    channel = channels(server, project_id=workspace_id)
    session_id = open_session(channel, project)
    channel.send_frame(prompt_frame(3, session_id, "scenario:rpc-error"))
    received = channel.answer(3)
    sent = [f for rows in peer_rows_by_pid(server.log_base).values()
            for f in peer_sent_frames(rows, lambda fr: fr.get("id") == 3 and "error" in fr)]
    assert sent, "the peer must have answered the prompt with a JSON-RPC error"
    assert received == sent[0], (
        f"the complete error frame must relay unchanged: got {received!r}, "
        f"peer sent {sent[0]!r}")
    # restated field-by-field (still exact, no coercion):
    error = received["error"]
    assert type(error["code"]) is int and error["code"] == -32603, error
    assert error["message"] == "hd003 peer internal failure", error
    assert error["data"] == {"vendorDetail": "keep-me"}, error


def test_client_answered_permission_carries_the_chosen_option_id(server, project, channels):
    """反向请求原样到达客户端；客户端自己回选的 optionId（同 kind 双选项中的
    精确一个）原样到达对端——收到的应答帧与客户端发出的应答帧完整相等。"""
    workspace_id = server.open_workspace(project)
    channel = channels(server, project_id=workspace_id)
    session_id = open_session(channel, project)
    channel.send_frame(prompt_frame(3, session_id, "scenario:permission twin-options"))
    seen = channel.collect(
        until=lambda f: f.get("method") == "session/request_permission", timeout=30)
    reverse = [f for f in seen if f.get("method") == "session/request_permission"][0]
    request = reverse["params"]
    allow_options = [o for o in request["options"] if o["kind"] == "allow_once"]
    assert len(allow_options) == 2, request["options"]
    chosen = next(o["optionId"] for o in allow_options
                  if o["optionId"].startswith("pick-2-"))
    client_answer = {"jsonrpc": "2.0", "id": reverse["id"], "result": {
        "outcome": {"outcome": "selected", "optionId": chosen}}}
    channel.send_frame(client_answer)
    wait_until(lambda: any(
        row.get("event") == "permission-answer"
        for rows in peer_rows_by_pid(server.log_base).values() for row in rows),
        timeout=30, message="the client's decision to reach the peer")
    received_by_peer = [row for rows in peer_rows_by_pid(server.log_base).values()
                        for row in rows if row.get("event") == "permission-answer"]
    assert len(received_by_peer) == 1, received_by_peer
    assert received_by_peer[0]["frame"] == client_answer, (
        f"the peer must receive the client's own answer verbatim; "
        f"got {received_by_peer[0]['frame']!r}, client sent {client_answer!r}")


# -- 5/6. 绑定不可换、双通道隔离（相同请求 id）、连接 ID 独立 -------------------


def test_a_channel_binding_never_moves_and_each_project_gets_its_own(server, tmp_path, channels):
    project_a = tmp_path / "alpha"
    project_b = tmp_path / "beta"
    for path in (project_a, project_b):
        path.mkdir()
    ws_a = server.open_workspace(project_a)
    ws_b = server.open_workspace(project_b)
    channel_a = channels(server, project_id=ws_a)
    channel_b = channels(server, project_id=ws_b)
    assert channel_a.connection_id != channel_b.connection_id
    assert channel_b.binding.get("cwd") == str(project_b.resolve())
    # Re-acquiring the same pair yields the same binding, never a silently
    # different harness or project.
    again = channels(server, project_id=ws_a)
    assert again.binding.get("cwd") == channel_a.binding.get("cwd"), \
        "the same (harnessId, projectId) must not be re-bound elsewhere"


def test_two_channels_relay_identical_request_ids_without_crossing(server, tmp_path, channels):
    """③在通道层的钉法：两条通道使用**同一批 JSON-RPC 请求 id**，应答必须各回
    各家；prompt 流量按对端进程日志归属判定，不按消息里的字段猜。"""
    project_a = tmp_path / "alpha"
    project_b = tmp_path / "beta"
    for path in (project_a, project_b):
        path.mkdir()
    ws_a = server.open_workspace(project_a)
    ws_b = server.open_workspace(project_b)
    channel_a = channels(server, project_id=ws_a)
    channel_b = channels(server, project_id=ws_b)
    # Same ids 1/2 on both channels; each answer must carry its own peer's cwd.
    session_a = open_session(channel_a, project_a, frame_id=1)
    session_b = open_session(channel_b, project_b, frame_id=1)
    assert session_a != session_b, "the two peers own distinct native session ids"

    channel_a.send_frame(prompt_frame(3, session_a, "only-for-alpha"))
    channel_a.answer(3, timeout=30)
    got = channel_b.drained(settle=1.0)
    assert not [f for f in got if f.get("id") == 3 and "method" not in f], \
        "channel B answered a request id that was only ever sent on channel A"
    by_pid = peer_rows_by_pid(server.log_base)
    a_pids = peer_pids_for(server.log_base, project_a)
    b_pids = peer_pids_for(server.log_base, project_b)
    assert a_pids and b_pids, "both peers must have per-pid evidence"
    alpha_seen = any("only-for-alpha" in json.dumps(frame_recv)
                     for pid in a_pids for frame_recv in peer_recv_frames(by_pid[pid], "session/prompt"))
    assert alpha_seen, "the prompt must reach the peer owned by A"
    leaked = [row for pid in b_pids for row in by_pid[pid] if row.get("dir") == "recv"]
    assert not any("only-for-alpha" in json.dumps(row) for row in leaked), \
        "channel A's traffic must never reach the peer owned by B"


def test_connection_id_is_separate_from_the_native_session_id(server, project, channels):
    workspace_id = server.open_workspace(project)
    channel = channels(server, project_id=workspace_id)
    native_id = open_session(channel, project)
    assert str(channel.connection_id) != str(native_id), (
        "the channel's connection id and the peer's native session id are "
        "different identities and must never collide")


# -- 7/8/9. 生命周期：切换≠释放；显式 release；一次通道运行=一次 execution ------


def test_stopping_to_view_is_not_a_release(server, project, channels):
    """The client may go quiet (view switch); nothing may be cancelled,
    restarted or resent on its behalf."""
    workspace_id = server.open_workspace(project)
    channel = channels(server, project_id=workspace_id)
    open_session(channel, project)
    pids_before = set(peer_rows_by_pid(server.log_base))
    time.sleep(2.0)  # the client "switches away": no reads, no frames
    assert set(peer_rows_by_pid(server.log_base)) == pids_before, \
        "quiet viewing must not restart the owned Agent"
    by_pid = peer_rows_by_pid(server.log_base)
    assert not any(peer_recv_frames(rows, "session/cancel") for rows in by_pid.values()), \
        "quiet viewing must not cancel a turn"
    assert len(session_new_events(server.log_base)) == 1, \
        "quiet viewing must not re-create or re-send anything"
    # The channel is still live afterwards.
    channel.send_frame(prompt_frame(9, "any", "still-alive"))
    assert channel.answer(9, timeout=30)["result"]["stopReason"] == "end_turn", \
        "the channel must still relay after the client stopped viewing"


def test_channel_ws_admission_requires_authorization(server, project, channels):
    """新 ACP WebSocket 的授权正反例（不复用旧 event-stream 的结论）：
    已存在的连接不能被未授权客户端接入，只有持牌客户端能继续往返。"""
    from tests.acp_orchestration.test_access_authorization import ws_close_code
    workspace_id = server.open_workspace(project)
    channel = channels(server, project_id=workspace_id)
    url = "ws://127.0.0.1" + CHANNEL_WS_PATH.format(
        connectionId=channel.connection_id)
    good = {"authorization": "Bearer " + server.token}
    assert ws_close_code(server, url, {"authorization": "Bearer wrong"}) == 4401, \
        "an unauthorized client must not attach to an existing connectionId"
    assert ws_close_code(server, url, {}) == 4401, \
        "a missing bearer token must be refused before accept"
    assert ws_close_code(server, url, {"origin": "http://evil.example", **good}) == 4403, \
        "a non-loopback Origin must be refused on the ACP relay too"
    # 正例：授权的持牌客户端仍然可以完整往返。
    open_session(channel, project)


def test_explicit_release_acks_and_only_the_owned_channel_stops(server, tmp_path, channels):
    """release 必须被确认；释放后 A 不再可用、B 仍可实际往返；
    未授权客户端既不能接入也不能释放。"""
    project_a = tmp_path / "alpha"
    project_b = tmp_path / "beta"
    for path in (project_a, project_b):
        path.mkdir()
    ws_a = server.open_workspace(project_a)
    ws_b = server.open_workspace(project_b)
    baseline = in_flight_execution_ids(server)
    channel_a = channels(server, project_id=ws_a)
    exec_a = in_flight_execution_ids(server) - baseline
    assert len(exec_a) == 1, (
        f"channel A's run must be exactly one execution, got {sorted(exec_a)}")
    (run_a_id,) = sorted(exec_a)
    channel_b = channels(server, project_id=ws_b)
    exec_b = in_flight_execution_ids(server) - baseline - exec_a
    session_a = open_session(channel_a, project_a)
    session_b = open_session(channel_b, project_b)
    owned_by_a = peer_pids_for(server.log_base, project_a)
    owned_by_b = peer_pids_for(server.log_base, project_b)
    assert owned_by_a and owned_by_b, "both Agents must be up before releasing"

    # 未授权 release：401，且 A 完全不受影响（真实往返，不是仅 PID 存活）。
    refusal = server.wire(CHANNEL_RELEASE_METHOD,
                          {"connectionId": channel_a.connection_id},
                          token="wrong-token", status=401)
    assert refusal["error"]["code"] == "UNAUTHENTICATED", refusal
    channel_a.send_frame(prompt_frame(20, session_a, "still-ours"))
    assert channel_a.answer(20)["result"]["stopReason"] == "end_turn", \
        "a refused release attempt must leave A fully usable"

    # 显式 release：必须收到确认。
    ack = channel_a.release()
    assert isinstance(ack, dict), f"release must answer with a result: {ack!r}"

    # A 不再可用：不得再有任何完整 ACP 往返（成功应答即违规）。
    round_trip = None
    try:
        channel_a.send_frame(prompt_frame(21, session_a, "must-not-work"))
        round_trip = channel_a.answer(21, timeout=8)
    except Exception:  # noqa: BLE001 - any channel-level failure is a failed round trip
        round_trip = None
    assert round_trip is None, \
        f"released channel A still completed an ACP round trip: {round_trip}"
    wait_until(lambda: not any(pid_alive(pid) for pid in owned_by_a),
               timeout=15, message="A's owned Agent to stop")
    assert exec_a and exec_a.isdisjoint(in_flight_execution_ids(server)), \
        "A's channel run must have ended in the ledger"
    # 正向断言：A 的运行记录进入合法终态并写明结束原因（不是仅"从在飞
    # 列表消失"，也不是排除几个成功字符串）。
    assert_run_record_ended(server, run_a_id, normal=True)

    # B 仍可实际往返，且 B 的 execution 不受影响。
    channel_b.send_frame(prompt_frame(22, session_b, "alive-after-A-release"))
    assert channel_b.answer(22)["result"]["stopReason"] == "end_turn", \
        "releasing A must not disturb B's real traffic"
    assert all(pid_alive(pid) for pid in owned_by_b)
    assert in_flight_execution_ids(server) - baseline == exec_b, \
        "release must end exactly A's run, leaving B's execution in flight"


def test_one_channel_run_is_one_workcore_execution(server, project, channels):
    """Workcore 边界：一次通道运行=一次 execution。建立后立即锁定该通道的
    execution 身份与进程身份；多轮 prompt/审批前后，两个身份集合均不变；
    release 精确结束该 execution，不波及其他。"""
    workspace_id = server.open_workspace(project)
    baseline = in_flight_execution_ids(server)
    channel = channels(server, project_id=workspace_id)

    # —— 建立后立刻锁定身份 ——
    run_ids = in_flight_execution_ids(server) - baseline
    assert len(run_ids) == 1, (
        f"opening a channel run must correspond to exactly one execution, "
        f"the ledger gained {sorted(run_ids)}")
    (run_id,) = sorted(run_ids)
    # `connect` answers once the Agent process is spawned; the controlled
    # peer's first log line becomes visible a moment after node boots.  Wait
    # for that evidence, then lock the identities — every behavioural
    # assertion below is unchanged, and a late or absent start still fails.
    wait_until(lambda: peer_rows_by_pid(server.log_base),
               timeout=15, message="the Agent started at open time to be logged")
    pids_after_open = set(peer_rows_by_pid(server.log_base))
    assert pids_after_open == peer_pids_for(server.log_base, project), \
        "the run's Agent processes must all be started for the bound project"
    assert pids_after_open, "the plugin must have started the Agent at open time"

    # —— 多轮：3 prompt + 1 权限往返，全部落在同一运行内 ——
    session_id = open_session(channel, project)
    channel.send_frame(prompt_frame(3, session_id, "round-one"))
    channel.answer(3)
    channel.send_frame(prompt_frame(4, session_id, "scenario:permission twin-options"))
    seen = channel.collect(
        until=lambda f: f.get("method") == "session/request_permission", timeout=30)
    reverse = [f for f in seen if f.get("method") == "session/request_permission"][0]
    chosen = next(o["optionId"] for o in reverse["params"]["options"]
                  if str(o["optionId"]).startswith("pick-1-"))
    channel.send_frame({"jsonrpc": "2.0", "id": reverse["id"], "result": {
        "outcome": {"outcome": "selected", "optionId": chosen}}})
    channel.answer(4)
    channel.send_frame(prompt_frame(5, session_id, "round-three"))
    channel.answer(5)

    # —— execution 身份不变（不是"数量没炸"，而是同一个 run_id）——
    now = in_flight_execution_ids(server)
    assert now - baseline == {run_id}, (
        f"multi-round use must not create or replace executions: "
        f"locked {run_id!r}, now {sorted(now - baseline)}")
    # —— 进程身份不变：同一批 pid、每个 pid 只有一条启动记录 ——
    by_pid = peer_rows_by_pid(server.log_base)
    assert set(by_pid) == pids_after_open, \
        "no restart: the run's process set must be identical before and after"
    for pid in pids_after_open:
        starts = [row for row in by_pid[pid] if row.get("event") == "peer-start"]
        assert len(starts) == 1, f"pid {pid} restarted inside one channel run"
        assert len(peer_recv_frames(by_pid[pid], "session/prompt")) >= 1
    prompts = sum(len(peer_recv_frames(by_pid[pid], "session/prompt"))
                  for pid in pids_after_open)
    assert prompts == 3, f"3 prompts must reach the same long-lived peers, got {prompts}"
    assert len(session_new_events(server.log_base)) == 1, \
        "multi-round use must not re-create the native session"

    # —— 故意留下一个**永不完成**的在飞任务，再显式 release：
    #    通道运行可以正常结束，但该任务没有被换算成任何成功。
    channel.send_frame(prompt_frame(6, session_id, "scenario:hang"))
    channel.release()
    after = in_flight_execution_ids(server)
    assert run_id not in after, "release must end the channel's own execution"
    assert after == baseline, \
        f"release must not disturb any other execution: {sorted(after ^ baseline)}"
    record = assert_run_record_ended(server, run_id, normal=True)
    assert record["endReason"] == "released", \
        f"a client-initiated close must name its own reason, got {record}"
    try:
        frames = channel.collect(timeout=5)
    except AssertionError:  # relay ended — the honest outcome
        frames = list(channel._seen)
    fabricated = [f for f in frames if f.get("id") == 6 and "method" not in f
                  and "result" in f]
    assert not fabricated, (
        f"the unfinished in-flight prompt was answered as success when the "
        f"channel run closed normally: {fabricated}")


def test_unexpected_agent_exit_ends_the_run_record_not_as_success(server, project, channels):
    """进程意外退出同样只结束通道运行记录，且不得被记为内部任务全部成功；
    在飞 prompt 不能收到伪造的成功应答。"""
    import signal
    workspace_id = server.open_workspace(project)
    baseline = in_flight_execution_ids(server)
    channel = channels(server, project_id=workspace_id)
    run_ids = in_flight_execution_ids(server) - baseline
    assert len(run_ids) == 1, run_ids
    (run_id,) = sorted(run_ids)
    # `connect` answers once the Agent process is spawned; the controlled
    # peer's first log line becomes visible a moment after node boots.  Wait
    # for that evidence, then lock the identity — every behavioural assertion
    # below is unchanged, and a late or absent start still fails.
    wait_until(lambda: len(peer_rows_by_pid(server.log_base)) == 1,
               timeout=15,
               message="the channel run's single Agent process to log its start")
    pids = set(peer_rows_by_pid(server.log_base))
    assert len(pids) == 1, f"one channel run owns exactly one Agent process, got {pids}"
    (pid,) = sorted(pids)
    session_id = open_session(channel, project)
    channel.send_frame(prompt_frame(7, session_id, "scenario:hang"))  # 在飞、永无应答

    os.kill(pid, signal.SIGKILL)
    wait_until(lambda: run_id not in in_flight_execution_ids(server),
               timeout=30, message="the crashed channel run to leave the in-flight ledger")

    # 在飞请求绝不允许被 Server 代答成成功。
    try:
        frames = channel.collect(timeout=5)
    except AssertionError:  # relay ended — the honest outcome
        frames = list(channel._seen)
    fabricated = [f for f in frames if f.get("id") == 7 and "method" not in f
                  and "result" in f]
    assert not fabricated, \
        f"the Server answered the in-flight prompt as success after the Agent died: {fabricated}"
    # 正向断言：崩溃的运行记录进入**异常结束**的合法终态并写明原因——
    # 既不是几个成功字符串的排除，也不是把断连粉饰成正常关闭。
    assert_run_record_ended(server, run_id, normal=False)


# -- 11. 释放结果诚实性：插件的真实释放结论必须一路传到 wire 与账本 ----------
#
# 主会话整改令（审核轮）：`released:false`、close 超时、无回执都不得被后端
# 换算成释放成功；未确认时保留资源身份与可重试能力，不销毁唯一管理入口；
# Registry 只在确认后才结账；并发 release 不得重复结账。
# 注入方式与主会话自己的复现一致：用桩包裹活的 transport，仅脚本化
# request_release 的答复，其余属性全部委托真实入口链路。


#: What the entry honestly says when its OS-confirmed reclaim admitted a
#: survivor (`ok:true` but `released:false`) - the plugin's real strict
#: guarantee that the backend must not drop.
_FALSE_RECEIPT = {"confirmed": False, "reason": "release-unconfirmed",
                  "report": {"released": False}}

#: What the transport reports when the entry never answered `close` in time.
_CLOSE_TIMEOUT = {"confirmed": False, "reason": "close-timeout", "report": None}


class _ReleaseStub:
    """Wraps the live transport; scripts only `request_release`, delegates
    everything else - including the real `close` once the script runs out."""

    def __init__(self, real, outcomes: list) -> None:
        self._real = real
        self._outcomes = list(outcomes)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def request_release(self):
        if self._outcomes:
            return dict(self._outcomes.pop(0))
        return self._real.request_release()


def _install_release_stub(server: ServerHandle, connection_id: str,
                          outcomes: list) -> _ReleaseStub:
    connection = server.runtime.acp_channels.get(connection_id)
    assert connection is not None and connection.transport is not None, (
        "the live channel's transport must be in place before scripting its answer")
    stub = _ReleaseStub(connection.transport, outcomes)
    connection.transport = stub
    return stub


def test_a_refused_release_never_becomes_a_success_answer(server, project, channels):
    """反例一（插件明确 false）：wire 返回 released:false，账本一分不动；
    身份保留、可重试，最终真实确认后才结束并只结束一次。"""
    workspace_id = server.open_workspace(project)
    baseline = in_flight_execution_ids(server)
    channel = channels(server, project_id=workspace_id)
    run_ids = in_flight_execution_ids(server) - baseline
    assert len(run_ids) == 1, run_ids
    (run_id,) = sorted(run_ids)
    session_id = open_session(channel, project)

    stub = _install_release_stub(server, channel.connection_id,
                                 [_FALSE_RECEIPT, _FALSE_RECEIPT])

    ack = channel.release()
    assert ack["released"] is False, \
        f"an entry that could not confirm the reclaim must never be answered as released: {ack}"
    assert ack["connectionId"] == channel.connection_id
    assert ack["executionId"] == run_id
    assert ack["reason"] == "release-unconfirmed", ack

    # 账本原样：运行仍在飞，没有终态、没有结束原因。
    assert run_id in in_flight_execution_ids(server), \
        "an unconfirmed release must not end the run record"
    record = channel_run_record(server, run_id)
    assert record["state"] not in (RUN_END_NORMAL | RUN_END_ABNORMAL
                                   | RUN_SUCCESS_CLAIM_STATES), record
    assert not record.get("endReason"), record

    # 唯一管理入口没有被销毁：通道仍然能真实往返。
    channel.send_frame(prompt_frame(30, session_id, "still-usable-after-refused-release"))
    assert channel.answer(30)["result"]["stopReason"] == "end_turn", \
        "a refused release must not tear down the entry or its Agent"

    # 身份保留：同 (harness, project) 再次取得仍是同一连接，而非第二条运行。
    again = channels(server, project_id=workspace_id)
    assert again.connection_id == channel.connection_id, \
        "an unconfirmed release must not move or replace the channel's identity"
    assert in_flight_execution_ids(server) - baseline == {run_id}

    # 重试仍可诚实成功：入口真正回执 OS 级回收后，才结账并返回成功。
    connection = server.runtime.acp_channels.get(channel.connection_id)
    connection.transport = stub._real
    ack = channel.release()
    assert ack["released"] is True, ack
    assert ack["executionId"] == run_id
    record = assert_run_record_ended(server, run_id, normal=True)
    assert record["endReason"] == "released", record
    assert run_id not in in_flight_execution_ids(server)

    # 第三次释放：通道已不存在，wire 给出 NOT_FOUND，而不是另一个成功。
    final = server.wire(CHANNEL_RELEASE_METHOD,
                        {"connectionId": channel.connection_id})
    assert final["error"]["code"] == "NOT_FOUND", final


def test_an_unanswered_close_is_not_release_success_and_retry_confirms(server, project, channels):
    """反例二+三（close 超时 → 重试成功）：超时按失败返回且账本不动；
    入口未被脚本伤害，真实 close 的重试得到确认后才结束。"""
    workspace_id = server.open_workspace(project)
    baseline = in_flight_execution_ids(server)
    channel = channels(server, project_id=workspace_id)
    run_ids = in_flight_execution_ids(server) - baseline
    assert len(run_ids) == 1, run_ids
    (run_id,) = sorted(run_ids)
    open_session(channel, project)
    owned = peer_pids_for(server.log_base, project)
    assert owned, "the run's Agent must be up before releasing"

    _install_release_stub(server, channel.connection_id, [_CLOSE_TIMEOUT])

    ack = channel.release()
    assert ack["released"] is False, \
        f"a close that was never answered cannot be claimed as a release: {ack}"
    assert ack["reason"] == "close-timeout", ack
    assert ack["executionId"] == run_id
    assert run_id in in_flight_execution_ids(server)
    record = channel_run_record(server, run_id)
    assert not record.get("endReason"), record

    # 重试：脚本已尽，桩把 request_release 交给真实入口链路 - close 第一次
    # 被真正问出口，得到 OS 确认回执后诚实成功。
    ack = channel.release()
    assert ack["released"] is True, ack
    assert ack["executionId"] == run_id
    record = assert_run_record_ended(server, run_id, normal=True)
    assert record["endReason"] == "released", record
    assert run_id not in in_flight_execution_ids(server)
    wait_until(lambda: not any(pid_alive(pid) for pid in owned), timeout=15,
               message="the confirmed release to actually reclaim the Agent")


def test_concurrent_releases_settle_the_run_record_exactly_once(server, project, channels,
                                                                monkeypatch):
    """并发 release 不得重复结账：两个线程同时释放同一连接，账本终态
    转换恰好发生一次，且没有任何一次返回被换算成假的失败或假的重复。"""
    import ordessa_harness.server_acp.registry as registry_module

    settlements: list[tuple[str, str]] = []
    real_end = registry_module.end_run_released

    def counting_end(session_records, execution_id, *, reason):
        settlements.append((execution_id, reason))
        return real_end(session_records, execution_id, reason=reason)

    monkeypatch.setattr(registry_module, "end_run_released", counting_end)

    workspace_id = server.open_workspace(project)
    baseline = in_flight_execution_ids(server)
    channel = channels(server, project_id=workspace_id)
    run_ids = in_flight_execution_ids(server) - baseline
    assert len(run_ids) == 1, run_ids
    (run_id,) = sorted(run_ids)
    open_session(channel, project)

    registry = server.runtime.acp_channels
    barrier = threading.Barrier(2)
    results: list[Any] = []
    failures: list[BaseException] = []

    def racer() -> None:
        try:
            barrier.wait(timeout=30)
            results.append(registry.release(channel.connection_id))
        except BaseException as exc:  # noqa: BLE001 - surface it on the main thread
            failures.append(exc)

    threads = [threading.Thread(target=racer) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=90)
    assert not failures, failures
    assert not any(thread.is_alive() for thread in threads), "a release raced hung"
    assert len(results) == 2, results
    # 每个赢到连接的调用都拿到真实确认；晚到者至多 NOT_FOUND(None)，
    # 绝不重复结账，也绝不返回 released:false 冒充。
    for outcome in results:
        assert outcome is None or outcome["released"] is True, results
    assert any(outcome is not None for outcome in results), results
    assert len(settlements) == 1, (
        f"the run record must be settled exactly once, got {settlements}")
    assert settlements[0] == (run_id, "released"), settlements
    record = assert_run_record_ended(server, run_id, normal=True)
    assert record["endReason"] == "released", record
    assert run_id not in in_flight_execution_ids(server)
