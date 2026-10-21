# 旧运行链移除清单与恢复位置 (HD-002, transport-only 接入链)
> **Current owner and evidence note (2026-10-10).** This document contains earlier migration/review evidence. Its body is preserved; old paths and test outcomes below describe the recorded historical snapshot and are not current execution instructions or fresh validation. Current ownership and path mapping:
>
> - `runtime/access-entry.mjs` and the prior plugin-local access chain → `apps/server/src/ordessa_server/composition/native_channels/access_entry.mjs`; it selects brand declarations through `selected_launch_ports.mjs` and uses the Agent transport at `packages/execution/agents/src/ordessa_agents/harness/transport/acp.mjs`.
> - `plugins/harness/tests/access/*.test.mjs` → `tests/integration/harness/access/*.test.mjs`; controlled peer/marker fixtures → `tests/fixtures/harness/access/`; shared sidecar support → `tests/integration/harness/access/support/sidecar_harness.mjs`.
> - `plugins/harness/tests/access/test_acp_boundaries.py` → `tests/architecture/harness/test_acp_boundaries.py`; `plugins/harness/packaging/tests/test_acp_schema_drift_target.py` → `tests/integration/harness/packaging/test_acp_schema_drift_target.py`.
> - Historical shared `packaging/<brand>` npm roots → each leaf's `plugins/harness/<brand>/tooling/npm/`; actual launch declarations remain owned by their brand leaf and are selected by the Server port.
>
> The source-owner receipt `docs/verification/overnight-upper-structure-20261009/harness-access-test-owner-root-applied.json` records 14 source mappings applied. Four shared discovery/CI files were subsequently integrated in `docs/verification/overnight-upper-structure-20261009/current-test-discovery-root-applied.json`; unsafe `verify-clean.sh` remains held and unrun. It is a migration receipt, not a test result. No suite was run for this documentation candidate. Historical wire names, identifiers, and raw results below remain historical evidence.


裁定：不保留旧运行链，不做双轨兼容。本文件记录**被移除的具体文件**、移除依据、以及
**每一个文件的恢复位置**；同时记录**经核对后决定保留**的文件和保留原因 —— 移除是按
依赖闭包核对的结果，不是按文件名。

## 恢复位置（唯一权威）

17 个被删文件在 `HEAD (e996e9d2)` 中**全部不存在**（`git cat-file -e HEAD:…` 全部失败，
`git ls-files plugins/agent-box-harness` 只有 26 条），即它们都是**前任会话未提交的成果**，
Git 历史无法恢复它们。唯一恢复路径是本次删除前建立的插件外备份：

```
/home/maoqh/projects/ordessa/backups/hd002-transport-only-20260924/
├── README.md                 # 备份范围、方法与校验结论
├── git-status-before.txt     # 删除前的 git status 全文
├── tracked-modified.diff     # 删除前已跟踪文件的差异
├── tracked-modified-files/   # 这些文件的删除前副本
└── plugin-tree-before/       # 整个插件目录的 cp -a 快照（含下列 17 个文件）
```

删除前对**全部 17 个目标**逐一核对：备份内存在、插件内已不存在（实测
`present-in-backup=17 still-on-disk=0`）。恢复任一文件即
`cp plugin-tree-before/<相对路径> plugins/agent-box-harness/<相对路径>`。
已跟踪文件（`SOURCE.json`、`PATCHES.md`、`acp-client.js`、各测试）另有 `git diff` 可回溯。

## 一、移除的入口与信封分发（1 个）

| 文件 | 它原本做什么 | 为何被新链取代 |
| --- | --- | --- |
| `runtime/worker-entry.mjs` | 旧生产入口：`register`/`start`/`open`/`create`/`prompt`/`abort`/`status`/`close` 信封分发，代做 `initialize`+`authenticate`+`session/new`+`session/prompt`，持有会话/轮次/快照表，按品牌选 `permissionMode` 代答权限，把 resolver 超时写成 `cancelled` | `runtime/access-entry.mjs` 只做发现/连接/透明 transport/状态/关闭五件事；建立连接不发任何 ACP 帧，其余行原样转发。反向请求、未应答、超时一律不代答，退出如实上报 |

## 二、移除的桥快照文件（11 个，`third_party/harness_remote/bridge/src/`）

| 文件 | 归属职责 | 移除依据 |
| --- | --- | --- |
| `acp-registration.js` | 把已配置 Agent 注册成 profile 并驱动握手 | 注册式信封被 `op:"connect"` + 显式 launch 取代 |
| `acp-service.js` | 会话/轮次生命周期、prompt 编排 | 新链不管会话，ACP 帧由调用方自己写 |
| `acp-prompt-echo-filter.js` | 过滤 prompt 回显后再投影成业务事件 | 不再投影事件，帧原样双向保留 |
| `agent-model-catalog.js` | 模型目录捆绑与产品别名映射 | 改写 `model` 参数即破坏透明 transport |
| `agent-router.js` | 按品牌路由到不同处理分支 | 品牌差异收进 `harnesses/<品牌>/launch.mjs` |
| `bounded-lru.js` | 只为 transcript 缓存服务的容量原语 | 随缓存一并退役 |
| `harness-capability-contract.js` | 把能力声明投影成自定义契约面 | 能力字段原样透传（见 T 系列 `promptCapabilities`） |
| `http-policy.js` | 旧 HTTP/管理面出站策略 | 新链只有 stdio 一对管道 |
| `managed-event-fanout.js` | 事件多路分发（快照/订阅者） | 分发归 Workcore/Server，不在插件里 |
| `task-model.js` | 任务/轮次状态机 | 属 Server/Core 权威，插件不复制 |
| `transcript-cache.js` | 转录缓存（`DEFAULT_MAX_ENTRIES = 64`） | 无消费者；运行链内 `MAX_ENTRIES` 命中现为 0，由打包边界测试钉住 |

裁剪已同步：`SOURCE.json` 从 21 条收窄为 **10** 条，`PATCHES.md` §9 列出这 11 个文件与
许可证立场（Apache-2.0，上游 `giuliastro/harness-remote` v3.0.2 @ `21ce6db4`，快照式裁剪、
不浮动分支）。

## 三、移除的旧链专属测试（5 个文件，47 个 `test(` 声明）

用例数按 `grep -c '^test('` 统计备份内副本得到（合计 6+12+13+9+7 = 47）。

| 文件 | 用例 | 处置 |
| --- | --- | --- |
| `tests/harness_remote/sidecar_envelope.test.mjs` | 6 | 随信封退役；逐例替代覆盖见 `tests/RETIRED.md` |
| `tests/access/sidecar_boundary_behavior.test.mjs` | 12 | 同上，其中通用传输/进程清理/隔离事实已重定位到 `tests/access/access_entry_behavior.test.mjs` (E1–E8) |
| `tests/harness_remote/snapshot_seams.test.mjs` | 13 | 其中若干例为已删文件（如 `transcript-cache.js`、`acp-service.js`）的假接缝，无对应物；`PATCHES.md` §7 的覆盖损失单独记录 |
| `tests/harness_remote/four_harness_component.test.mjs` | 9 | 组件面测的是被删的注册/路由分支 |
| `tests/harness_remote/turn_completion_facts.test.mjs` | 7 | 轮次完成事实由 Agent 自己的 `stopReason` 帧表达，不再由插件合成 |

保留的同类测试：`tests/harness_remote/{fake_acp_peer.mjs,frame_buffer_lifecycle.test.mjs}`
（字节边界与行缓冲属通用传输）、`tests/access/{acp_channel_behavior,acp_passthrough_target,
controlled_harness_self_proof,real_adapter_protocol}.test.mjs`、`tests/capability_claims.test.mjs`、
`tests/opencode_*.test.mjs`。夹具自证：`controlled_harness_self_proof.test.mjs` 先证明受控
harness 自己会记录帧，之后缺席断言才算数。

## 四、核对后**保留**的文件（含看似旧链实为存活依赖）

| 文件 | 保留原因（核对证据） |
| --- | --- |
| `third_party/harness_remote/bridge/src/acp-client.js` | 新链的实际传输层。它经 `access-transport.mjs` 里**计算式动态 import** 到达，静态 import 闭包扫不到 —— 曾因此被误判为可删，手工核对后保留；`transportOnly` 补丁见 `PATCHES.md` §8 |
| 其余 9 个 `bridge/src/*.js` | `launcher.js`/`harness-profiles.js` 等仍在 `acp-client.js` 与 `harnesses/*/launch.mjs` 的静态闭包内 |
| `runtime/profile_extensions.mjs` | 仍是**发现层**的数据源：5 个 `harnesses/*/launch.mjs` 直接 import `AGENTBOX_HARNESS_PROFILES`。其 `resolveNativeModel` 不再有生产消费者，只作为品牌 production 模板的 parity 对照表保留（`tests/test_pi_production_template.py` 等） |
| `runtime/native-driver.mjs` | 插件内已无调用者（唯一调用者是 `worker-entry.mjs`），但包外 `src/agent_box/server/execution/sidecar.py:265` 仍逐字节投影它；跨包消费者不在本任务写范围，**保留并上报断点** |
| `runtime/subagent-bridge.mjs` | 同上：`sidecar.py:276-277` 与 `runtime.py:1160` 两个包外消费者存活，`PLAN-OPTIONAL-INSTALL.md §6-6` 已定其归属，本轮不动 |
| `runtime/drivers/opencode-native.mjs` + `tests/opencode_*.test.mjs` (32 例) | OpenCode 未登记在 `harnesses/`（本轮不扩品牌范围），其原生 driver 只被旧 driver 分支服务。删它等于**丢弃另一名 agent 未提交的原生能力**，属裁定中"可能丢失原生能力须上报、不自行决定"的一类，故保留并升级处理（见下）。**第 4 轮更正**：保留它的理由从来不是"OpenCode 不说 ACP" —— 官方提供 `opencode acp`，见下第 1 条 |
| `runtime/capability_declarations.json` | 能力声明投影，消费者在包外且与本链无关 |

### 需要裁定的两件事（只报证据，不越权）

1. **OpenCode 的接入归属（第 4 轮更正结论，不据此扩范围）。** 本条原先写的是"OpenCode 不说 ACP"，
   并据此建议 Server 为 non-ACP 品牌保留一条独立投影路径。**两点都撤回**：官方 OpenCode 提供
   `opencode acp`，在 stdio 上运行 ACP（官方文档《ACP Support》`https://opencode.ai/docs/acp/`，
   本轮仅查证该文档存在、未据以改动任何代码），所以它与本链的 transport-only 通道原则上同构，
   没有保留非 ACP 旁路的理由。本轮真正的事实只有这些：`harnesses/` 里没有 opencode 条目，所以 `op:"connect"`
   以 `HARNESS_UNDISCOVERED` 拒绝它 —— 本轮不扩品牌范围，这是范围决定，不是协议能力判断
   （E6 断言 `ids` 不含 `opencode`，断言的是登记范围）。它的原生 driver 与 32 例测试现在只由
   `native-driver.mjs` 这条旧接缝驱动。**最小建议**：由上层裁定是否登记 `harnesses/opencode/`
   的 ACP 条目。核实的依据边界要说清：本轮既未执行官方文档、也未在本机验证 ——
   `command -v opencode` 无结果、无 `packaging/opencode` 离线字节（`real_adapter_protocol.test.mjs`
   正是据此推出"离线无字节可读"），所以"本机版本是否提供 `acp`"留待下一轮带证据决定，不在本轮
   顺手开通道。
2. **包外信封消费者。** `src/agent_box/server/execution/sidecar.py` 仍按旧词汇发送
   `register/start/open/create/prompt/abort/status/close` 及 `permissionRoundTrip`、
   `permissionTimeoutMs`、`preferredAuthMethod`、`stateDirectory`，且 `bootstrap/runtime.py:531`
   与 `sandbox_port.py:129` 仍指向 `worker-entry.mjs`。**整条产品链目前不可用**，本插件不为它们
   保留兼容层。旧→新对照表见 `DELIVERY.md` §5。
