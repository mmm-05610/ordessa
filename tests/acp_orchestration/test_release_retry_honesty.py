"""真实 `request_release` 的重试诚实性（主会话第二整改令之落点 1）。

这些测试**不替换** `request_release` 方法本身：被测对象就是生产的
`AccessEntryTransport` 桥，只有它对端（入口进程）换成受控假入口
（`fixtures/fake_access_entry.mjs`，仅经本仓库 tests/ 资产实现，插件不动）。
上一轮的桩测钉的是注册表行为；本文件钉的正是曾被桩绕过的那段缓存逻辑：

* 明确 `released:false` 后，下一次显式重试必须**真正把新的 close 问出口**
  （假入口的计数证据作证），并允许诚实确认；
* close 超时则**不重复发 close**：重试继续等同一个 pending，迟到回执可确认。

真实对端（插件真入口 + 受控 peer）下的端到端 release 语义仍由
`test_managed_acp_channel.py` 钉住，本文件不替代它。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tests.acp_orchestration.conftest import NODE, PEER, wait_until, pid_alive
from ordessa_harness.server_acp.access_entry import AccessEntryTransport

FAKE_ENTRY = Path(__file__).with_name("fixtures") / "fake_access_entry.mjs"


def _start_fake(tmp_path: Path, *, script: str, close_timeout: float):
    """A real bridge over the controlled fake entry, connected and established."""
    evidence = tmp_path / "close-evidence.jsonl"
    transport = AccessEntryTransport(
        node=NODE, entry=str(FAKE_ENTRY), harness_id="pi",
        cwd=str(tmp_path), adapter={"command": NODE, "args": [str(PEER)]},
        on_line=lambda line: None, on_exit=lambda code: None,
        environment={**os.environ, "FAKE_CLOSE_SCRIPT": script,
                     "FAKE_EVIDENCE": str(evidence)},
        close_timeout=close_timeout,
    ).start()
    return transport, evidence


def _close_asks(evidence: Path) -> list[int]:
    if not evidence.exists():
        return []
    return [json.loads(line)["n"] for line in
            evidence.read_text().splitlines() if line.strip()]


def test_a_failed_receipt_is_asked_again_and_can_honestly_confirm(tmp_path):
    """插件明确 false → 第二次重试必须发出**新的** close 并得到确认。"""
    transport, evidence = _start_fake(tmp_path, script="false-then-true",
                                      close_timeout=8.0)
    entry_pid = transport.pid
    assert entry_pid and pid_alive(entry_pid)

    first = transport.request_release()
    assert first["confirmed"] is False, first
    assert first["reason"] == "release-unconfirmed", first
    assert (first["report"] or {}).get("released") is False, first
    assert _close_asks(evidence) == [1], \
        "the first attempt must have asked exactly one close"

    # 缺陷复现点：旧实现把失败缓存后永不再问。真实重试必须再问一次。
    second = transport.request_release()
    assert second["confirmed"] is True, \
        f"a retry after an explicit failure must re-ask the entry: {second}"
    assert second["reason"] == "released", second
    assert _close_asks(evidence) == [1, 2], \
        "the retry must have written a NEW close, not replayed a cached answer"

    # 确认之后：缓存只留给成功；入口进程被诚实收回。
    third = transport.request_release()
    assert third["confirmed"] is True and _close_asks(evidence) == [1, 2], \
        "a confirmed release is terminal and must not re-ask"
    wait_until(lambda: not pid_alive(entry_pid), timeout=15,
               message="the entry to be stopped after its confirmed release")


def test_a_timed_out_close_is_not_re_sent_and_the_late_receipt_confirms(tmp_path):
    """超时 → 重试**等待原 pending**，绝不重复发 close；迟到回执诚实确认。"""
    # 假入口 1.2s 后才答复唯一的 close；桥的超时取 0.4s，逼出真实超时重试。
    transport, evidence = _start_fake(tmp_path, script="delay:1200",
                                      close_timeout=0.4)
    first = transport.request_release()
    assert first["confirmed"] is False and first["reason"] == "close-timeout", first

    outcome = first
    for _ in range(6):  # 每次重试只是再等同一个 pending
        outcome = transport.request_release()
        if outcome["confirmed"]:
            break
        assert outcome["reason"] == "close-timeout", outcome

    assert outcome["confirmed"] is True, \
        f"the late receipt must confirm through the same pending: {outcome}"
    assert _close_asks(evidence) == [1], \
        "a timeout must never stack a second close behind the unanswered first"
