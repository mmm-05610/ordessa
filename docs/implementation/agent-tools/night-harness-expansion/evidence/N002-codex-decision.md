# N002 Codex 原生通道决策与实现证据

执行：主执行者（L0/L2调查+客户端）+切片子代理（驱动，主执行者复跑）。2026-10-04。真实模型调用0、安装0。

## 通道决策（L0）

- **选定通道**：`codex app-server` 本地原生 JSON-RPC（stdio默认）。不混淆 exec-server/模型API（doc三者分离已核实）；ws/unix 备选不选（ws文档自称experimental）。
- **钉版**：npm `@openai/codex` **0.157.1**（2026-09-27安装于~/.local/lib/node_modules）；**Apache-2.0**；平台二进制 `@openai/codex-linux-x64/.../bin/codex` sha256=`632b790674b5462899a61bd248c33a3fb4594d3388f33259b8ca00dce014c42d`（**该实物已损坏，见下**）。
- **协议来源**：官方 learn.chatgpt.com/docs/app-server（2026-10-04 WebFetch）。握手 initialize/initialized、**无版本协商**（仅capabilities门控 experimentalApi）、thread/turn身份、turn回执≠完成（turn/completed才终态）、反向审批item/permissions/requestApproval等按id关联、过载-32001不自动重试。
- **升级边界**：钉版本；无版本协商→升级须重钉重验（G1）。

## L2 实测 = BLOCKED（本机artifact损坏，如实登记）

| 证据 | 值 |
| --- | --- |
| 文件大小 | 125,251,498 字节 |
| ELF头声明段表偏移 | 285,338,280（文件截断于约44%） |
| 实测症状 | `execve` 返回 **EFAULT** → **SIGSEGV**（strace：`execve(...)=-1 EFAULT`、`--- SIGSEGV ---`）；plain/env隔离/unshare三种条件下均复现 |
| npm launcher | `node bin/codex.js --version` → `Error: Missing optional dependency @openai/codex-linux-x64`（launch解析第二故障，独立于截断） |
| 结论 | **本地安装损坏，L2真实进程验证不可得**。重装/更新第三方Harness不在本夜授权内→**登记待授权**；不擅自 `npm install` |

无模型握手/会话证据因此 **0项**（不冒充）；L2缺口精确到上述实证。

## 实现（CODE_READY＋L1）

| 交付 | 位置 | 测试 |
| --- | --- | --- |
| 消费者客户端 | `products/agent-tools/src/ordessa_agent_tools/native_clients/codex.py`（CodexAppServerClient：initialize/initialized、create_thread真实会话身份、start_turn回执≠完成、wait_turn_completed、cancel=turn/interrupt、reply_approval永不auto、-32001 typed不重试） | `tests/native_clients/test_codex_client.py` **11P/0F** |
| Harness驱动 | `plugins/harness/src/ordessa_harness/codex/native_channel.py`（BROKEN_LOCAL_ARTIFACT证据、plan_launch钉CODEX_HOME、compile_config发前拒、capability_matrix全no-observed） | `tests/codex/test_codex_native_channel.py` **17P/0F** |

命令/退出码（主执行者复跑）：
```
pytest tests/native_clients/test_codex_client.py -q          # 11 passed, exit 0
pytest plugins/harness/tests/pi plugins/harness/tests/codex  # 30 passed, exit 0
```
反例覆盖：-32001不自动重试、turn failed→TurnFailed带原文、wait超时→unknown不重发、非法审批决策本地拒、未知事件保留、关闭后typed失败。

## 分账与缺口

- L0✓；L1✓（28用例）；**L2=BLOCKED**（artifact损坏，非能力缺失——重装后可测initialize/thread/审批回调）；L3/L4未测。
- capability_matrix：observed 全部 no（诚实）；审批/取消/恢复=declared+plan-only。
- 管理绑定依赖阻塞同N001（029 AT-009/010/011）；不发布runtimeReady。
- **待授权清单**：重装或更新 @openai/codex（换新版本亦可）以恢复codex L2；重装后须重钉digest并重测。
