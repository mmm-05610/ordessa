# T10-Pi：真 Pi CLI 受控探针（Q4 managed lane 升格尝试）

日期：2026-09-29。执行面：本 worktree `011-q4-mcp`；Pi = PATH 安装
（`/home/maoqh/.local/bin/pi` → `~/.pi/agent/install/releases/0.86.1/node_modules/@earendil-works/pi-coding-agent`，
`pi --version` = **0.86.1**；R-Q4-4 双 pin 歧义未裁：生产闭包 pin 0.84.2，PATH 实装只有 0.86.1）。
所有 pi 子进程均在 `HOME=$(mktemp -d)` 隔离环境 + `PI_OFFLINE=1 PI_SKIP_VERSION_CHECK=1` +
`timeout 60/240` 下运行；**未读未写用户 `~/.pi`**（勘察仅只读 dist 文件）；无任何外网、无真实模型调用、
无真实 MCP server（门后是 `InMemoryManagedClient` echo 假后端）。

## 1. 一手勘察：官方文档说法 vs dist 一手代码

| 事实 | docs（0.86.1 包内 `docs/extensions.md` 等） | dist 一手代码/先例 | 差异/裁定 |
| --- | --- | --- | --- |
| 扩展入口 | `export default function (pi: ExtensionAPI)`，工厂返回 Promise 时 pi 在 `session_start` 前 await | Go 桥 gate 扩展（`plugins/harness/adapters/acp-adapter/internal/pi/gate_extension.go`）实证同形 | 一致；本桥用 async 工厂做握手（阻塞到 ready，超时 fail closed） |
| 加载路径 | `~/.pi/agent/extensions/`、`.pi/extensions/`、settings.json `extensions[]`、`pi -e/--extension <path>`（"only for quick tests"） | `pi --help`：`--extension, -e <path>  (can be used multiple times)`；`--no-extensions` 下 `-e` 仍生效 | 生产装载面 = CLI 注入（Go 桥先例同路线），正式入口归 C0（G9） |
| registerTool | `pi.registerTool(ToolDefinition)`，`execute(toolCallId, params, signal, onUpdate, ctx)`；`parameters` 为 TypeBox TSchema | `dist/core/extensions/types.d.ts:344-383`（ToolDefinition 逐字段）+ `:950` 签名；示例 `examples/extensions/hello.ts` 用 `defineTool` + `Type` 来自 `@earendil-works/pi-ai` | 文档"Available Imports"写 `typebox` 包，示例实际从 `@earendil-works/pi-ai` 导入 `Type`（dist 里 `typebox` 目录确实存在）→ 记录为文档/示例不一致；本桥直接透传 Server 侧 JSON Schema 对象（TypeBox 运行时形状即 JSON Schema，但 **未经真机 LLM 调用验证**，见 §4-C） |
| session 生命周期 | `session_start`/`session_shutdown`（含退出 Ctrl-C/SIGTERM）/`session_before_switch` 等 | types.d.ts `SessionStartEvent.reason` 枚举与 lifecycle 图一致 | 一致 |
| RPC 面 | `pi --mode rpc`：stdin/stdout 换行分隔 JSON；`prompt` 命中扩展命令**直接执行不经 LLM**；`notify` 以 `extension_ui_request` 帧流出（fire-and-forget）；Node readline 不合规（U+2028/9） | 探针驱动逐字实现（select+readline on \n），§3 实测 | 一致；探针的 B/D1 格靠这两条 |
| 离线开关 | `PI_OFFLINE`、`PI_SKIP_VERSION_CHECK`、`PI_CODING_AGENT_DIR`、`PI_PACKAGE_DIR` | 探针使用 PI_OFFLINE/PI_SKIP_VERSION_CHECK + 隔离 HOME 成功（无网络请求迹象） | 一致 |
| 包名 scope | `@earendil-works/pi-coding-agent` | Go 桥 gate 扩展仍 `import type` 旧 scope `@mariozechner/pi-coding-agent`（类型期擦除，运行不报错） | 0.86.1 闭包内只有 `@earendil-works/*`；本桥用新 scope（type-only，同样不产生运行时依赖） |

## 2. 桥组件符号

**扩展（Pi 侧，受管可执行件）** `plugins/assets/mcp/adapters/pi/ordessa-mcp-bridge.ts`
（sha256 `17d4f00e…820589b`，见 `scripts/pack.mjs` 产 `dist/manifest.json`；版本/许可证/信任登记在
`package.json` + manifest，`trustApproval: "pending"` ——打包不等于信任批准）。
符号：`LOOPBACK_HOST`（唯一可拨地址字面量）、`BridgeChannel.connect/call/close`、
`requiredEnv(ORDESSA_PI_BRIDGE_PORT|TOKEN)`（**不读 HOST**，扫描钉死）、每目录工具一
`pi.registerTool`、`/ordessa_mcp_status` 观测命令、`session_shutdown → close`。

**Python 对端** `plugins/assets/mcp/backend/managed/pi_bridge.py`：
`BRIDGE_PROTOCOL=1`、`bind_bridge()`（登记时按活观察逐项核 `tool_schema_digest`，
不匹配 `MCP_VERIFICATION_MISMATCH`；越出批准子集 `MCP_TOOL_NOT_APPROVED`；无观察
`MCP_CATALOG_MISSING`/`MCP_NOT_CONNECTED`）、`PiToolBridge.handle_call`（先核登记子集+
digest 漂移，**再**入 `ManagedSessionManager.call_tool` = D5 统一双门，不建第二权限模型）、
`PiBridgeServer`（127.0.0.1:0、`secrets.token_hex` 一次性绑定 + `hmac.compare_digest`、
`token_consumed` 粘性/`bound` 活通道二分、帧大小上限、malformed→断道、`close()` 幂等释港）。
错误码全部取自 `backend/errors.py` 封闭词表（通道门=PERMISSION_REFUSED；非 loopback
listen=MCP_TRANSPORT_UNSUPPORTED）。env 契约对齐 server-compat bridge token 先例
（composition.py order-65 `AGENTBOX_BRIDGE_URL/TOKEN`）独立实现。

## 3. 真 CLI 探针逐格（命令 + 输出摘录 + 退出码）

命令（复现）：
```
HOME=$(mktemp -d) PI_OFFLINE=1 PI_SKIP_VERSION_CHECK=1 timeout 60 pi --version   # → 0.86.1, rc=0
HOME=$(mktemp -d) PI_OFFLINE=1 timeout 60 pi --help                              # rc=0（-e/--mode rpc/--no-session 在案）
timeout 240 .venv/bin/python plugins/assets/mcp/tests/pi_bridge/real_pi_probe.py # rc=0
```
探针逐格输出（pi 0.86.1 实进程，隔离 HOME `/tmp/ordessa-pi-probe-98xu799k`）：

| 格 | 判定 | 证据 |
| --- | --- | --- |
| D0 错 token 装载 | **observed** | `wrong-token pi: hellosRefused=1 bound=False reasons=['hello token does not match the bound registration'] client_executed=0`；pi 进程未能登记任何通道 |
| A 扩展加载/握手 | **observed** | `pi(pid=1306562) hello_accepted=1 bound=True`（`pi --mode rpc --no-session -e ordessa-mcp-bridge.ts`；async 工厂在 session 前完成通道绑定） |
| B 目录在 Pi 内可见 | **observed** | RPC prompt `/ordessa_mcp_status` 不经 LLM 直接执行，回 `extension_ui_request/notify`：`bound=true readyTools=[echo] allTools=[read,bash,powershell,edit,write,grep,find,ls,echo]` ——`echo` 经 `registerTool` 出现在 Pi 自身注册表，未批准的 `list` 不在 |
| C 真机 tools/call | **unknown（需凭据）** | LLM 分派腿必须有 provider；本轮不造凭据、不真调用（AGENTS 规则 9）。门侧行为已由 L2 全证（§4）；升格需 loopback fake-provider（G9 列项）或真模型授权 |
| D1 活通道重绑定 | **observed** | 第二个真 pi 携已消耗 token 起程 → `reasons=[…, 'another live channel already holds this bridge'] firstChannelStillBound=True client_executed=0` |
| E 关闭/清理 | **observed** | `pi exited 0; bridge.bound=False`（stdin 关闭→pi 正常退出→通道 EOF→活通道位落 0，token 保持已耗），`server.close()` 快照 `closed=True hellosAccepted=1 callsRefused=0 client_executed=0`；测试并证端口释放可重 bind |

首轮探针曾暴露真缺陷：pi 退出后 `bound` 仍为 True（EOF 只退循环不清活通道位）——修复为
`bound`（活通道）与 `token_consumed`（粘性一次性）二分，`_connection_loop` EOF 时清位并记
`pi-bridge-channel-closed`；修后 D1/A/E 全 observed（`grep` 记录于 commits 前工作树）。

## 4. L2 反例/门测试（`tests/pi_bridge/`，29 例）与变异证据

- roundtrip（`test_pi_roundtrip.py`）：hello→ready 仅含批准子集；call 经双门入受管 client
  （`executed_calls` 为证）；authority 决策 kwargs 逐项核对；ready 帧无凭据（含 token 不回显）。
- token 绑定（`test_token_binding.py`）：缺 token/错 token/活通道二 hello/断开后重放（=消耗后
  永不再绑）/错 proto/非 hello 首帧/malformed 断道/超 1MiB 帧不解析/env 面必 loopback。
- 门拒零转发（`test_gate_zero_forward.py`）：未登记工具在**进入 manager 前**拒（monkeypatch 哨兵
  证 manager 未入）；DENYING authority 下 client `executed_calls==[]`；绑定后目录漂移→
  `CATALOG_CHANGED` 且 client 零执行；bind 期描述符与观察 digest 不符→`MCP_VERIFICATION_MISMATCH`；
  越批准子集 bind 拒；未连接定义 bind 拒（`MCP_NOT_CONNECTED`）。
- close 清理（`test_pi_close_cleanup.py`）：close 幂等（replayed）、端口释放可重 bind、在途 peer
  见 EOF、close 后无 accept 无 result。
- 源码扫描（`test_source_scan.py`）：import 白名单（`node:net`/`node:process`/type-only pi）；
  无 `fetch`/http/https/dns/MCP client 形状；`net.connect` 的 host 只能是 `LOOPBACK_HOST`
  字面量、源内地址字面量集合 ⊆ {127.0.0.1}、扩展不读 HOST env；env 读取面 = PORT+TOKEN；
  无 secretRef/apiKey/credential 形状标识；Python 对端 bind 点唯一且非 loopback listen 为类型化拒绝。
- 变异（旁路→红→恢复）：①`handle_call` 子集检 `if False` →
  `test_unregistered_tool_refused_zero_forwarded` 红（1 failed/28 passed），恢复绿；
  ②`_check_hello` token compare 旁路 → `test_wrong_token_is_refused` 红，恢复绿。
  两处均为受控反证（带对照：修复后 pi_bridge+codes 44 passed；全 `plugins/assets/mcp/tests` **490 passed**，
  codes 封闭词表守卫生效——`ENV_*` 常量曾误撞「模块自注册码」形状，已改表驱动定义）。

## 5. L 级裁定（本域）

- 加载/登记（Pi 实进程装载扩展、通道绑定、Server 校验目录进入 Pi 注册表、观测命令）：**L3**
  （真 CLI 0.86.1 PATH 实装 observed；≠ 生产闭包 0.84.2，R-Q4-4 未裁前不得写「生产可用」）。
- 拒绝（错绑/重放/越集/门拒/漂移/超限帧）：通道与门侧 **L2**（Python peer）+ 真 CLI **L3**（D0/D1）；
  其中「未登记工具在真机 call 帧上被拒」仍随 C 格挂 unknown。
- 调用（execute→通道→双门→受管 client→结果回注）：**L2**；真 Pi LLM 分派腿 **unknown-需凭据**。
- 清理：**L2**（测试）+ **L3**（E 格实进程 EOF 链）。
- 全链 L3（Pi 标 "ready"）所缺：C 格真机分派 + 生产闭包 0.84.2 复测 + 装载面正式入口 + 信任批准
  （manifest `trustApproval` 仍 pending）——前三项已列 G9；第四项是流程门不是代码门。

## 6. 红账 / 未证范围（如实）

1. 未做真 MCP server 端到端（门后是 in-memory echo 假 client）；未做真模型调用（规则 9）。
2. `registerTool` 的 `parameters` 直传 Server 观察 JSON Schema 的**运行时校验兼容**未实证（需 C 格）。
3. 探针跑在 0.86.1 PATH 实装；0.84.2 生产闭包内同名面未验证。
4. `session_shutdown` 显式帧（SIGINT/SIGTERM 路径）未单独验证——E 格走的是 stdin 关闭 + EOF 兜底。
5. 动态目录变更后的**扩展侧撤权**（Pi 内工具移除/禁用）未实现：漂移时门拒调用（L2 已证），
   但 Pi 注册表里的旧工具名要到重绑定才消失——设计允许（拒执行），体验面记后续项。
6. `pi-acp 0.5.0` 每会话 `mcpServers→InlineExtension` 静态链仍未运行实证（不属本探针面）。
