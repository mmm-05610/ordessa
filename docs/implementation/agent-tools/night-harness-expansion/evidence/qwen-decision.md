# N007 Qwen Code 原生通道决策与实现证据

执行：家族单元切片（harness 驱动 + products 消费者客户端），2026-10-04。真实模型调用 0、安装 0、git 操作 0、共享文件改动 0。协议事实为 L0（官方文档/官方源码逐条钉定，来源 URL 见下；全部查阅日期 2026-10-04）；全部测试为 **L1 fake upstream**（本地 `http.server`，标注在测试名，**不冒真实进程**）；本机无 qwen CLI（`command -v qwen` = absent，不安装），**L2 未测**。不发布 runtimeReady。

方法备注：`qwen-serve-protocol.md` 约 398 KB（4288 行），WebFetch 提取两次均返回空文本，改用 `raw.githubusercontent.com` 原文分段核读（同一官方来源）；`architecture.md` 等小文档 WebFetch/原文均核对通过。钉版 revision 为核读时的 main HEAD。

## L0 钉版表（来源 URL + 查阅日期 2026-10-04）

| # | 项目 | 钉定值 | 来源 URL |
| --- | --- | --- | --- |
| 1 | 上游仓库 / 包 | `github.com/QwenLM/qwen-code`；npm `@qwen-code/qwen-code` | https://github.com/QwenLM/qwen-code |
| 2 | 许可 | **Apache-2.0**（LICENSE 原文头部确认；npm packument 的 license 字段为空，以仓库 LICENSE 为准） | https://raw.githubusercontent.com/QwenLM/qwen-code/main/LICENSE ; https://registry.npmjs.org/@qwen-code/qwen-code/latest |
| 3 | release 钉版 | **0.24.7**（`packages/cli/package.json` 与 npm `latest` 一致） | https://raw.githubusercontent.com/QwenLM/qwen-code/main/packages/cli/package.json ; https://registry.npmjs.org/@qwen-code/qwen-code/latest |
| 4 | 源码 revision | main **9915c7ff8ff17a6c5e0840053a0c05bb72eec510**（2026-10-04T17:54:09Z） | https://api.github.com/repos/QwenLM/qwen-code/commits/main |
| 5 | 通道形态 | `qwen serve` = 包在 ACP 执行外的 **HTTP + SSE 控制面**；`qwen --acp` 为 ACP 宿主，可被 ACP 客户端直接驱动，也可被 serve 经共享 ACP bridge 驱动 | https://github.com/QwenLM/qwen-code/blob/main/docs/developers/architecture.md |
| 6 | serve 默认监听 | `--hostname` 默认 **127.0.0.1**、`--port` 默认 **4170**；`--port 0` = OS 分配临时端口；`--workspace` 可重复（首个 primary，须绝对路径，缺省 process.cwd()） | https://github.com/QwenLM/qwen-code/blob/main/packages/cli/src/commands/serve.ts（`DEFAULT_SERVE_HOSTNAME='127.0.0.1'`、port default 4170）; https://github.com/QwenLM/qwen-code/blob/main/docs/developers/qwen-serve-protocol.md |
| 7 | serve 阶段 | Stage 1 **experimental**（`--http-bridge` 默认 true，Stage 2 in-process 未实现）；用户文档仍标 "v0.16-alpha" 而包已是 0.24.7 → **文档/版本漂移登记**，不擅自调和 | serve.ts `describe`/`--http-bridge` 选项 ; https://github.com/QwenLM/qwen-code/blob/main/docs/users/qwen-serve.md |
| 8 | 认证（传输层） | 环回默认 **无 token 可信模式**（本地调用者拥有完整 operator API 权限，含代码执行）；`--token`/`QWEN_SERVER_TOKEN` 可选 bearer；`--require-auth` 硬化环回；非环回绑定必须 token（缺省生成临时 bearer 启动时打印一次）；`/health` 在普通环回注册于 bearer 中间件之前 | qwen-serve-protocol.md §Authentication ; serve.ts |
| 9 | 认证（provider） | 环境变量：`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL`（别名 `QWEN_MODEL`）、`DASHSCOPE_API_KEY`、`ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL`/`ANTHROPIC_MODEL`、`GEMINI_API_KEY`/`GEMINI_MODEL`；或 `~/.qwen/settings.json` 的 `env` 引用、`.qwen/.env` | https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/auth.md |
| 10 | 会话创建 | `POST /session`（200）→ `{sessionId, workspaceCwd, attached?}`；`sessionScope` 缺省 `single`（同 workspace 二次 create 可 `attached:true` 共享会话），`thread` 每次强制新会话；caller 可带 `sessionId`（`session_id_override`）；cwd 不匹配注册 workspace → 400 `workspace_mismatch` | qwen-serve-protocol.md §POST /session ; 源码 `packages/cli/src/serve/routes/session.ts`（AK ce route 200） |
| 11 | 会话恢复 | `POST /session/:id/load`、`POST /session/:id/resume`（daemon 持有的持久会话；未观测） | qwen-serve-protocol.md |
| 12 | 发送 | `POST /session/:id/prompt` → **202 `{promptId, lastEventId}`**（源码实测还含 `eventEpoch`）＝**受理回执，非完成**；完成是 SSE 上 `turn_complete`/`turn_error` 按 `promptId` 关联，`stopReason` 为开放字符串 | qwen-serve-protocol.md §POST /session/:id/prompt ; session.ts（`res.status(202).json({ promptId, lastEventId, eventEpoch })`） |
| 13 | 事件流 | `GET /session/:id/events`（SSE）：`data:` 一行一个完整 JSON envelope `{id?, v, type, data}`；`event:` 行与 `envelope.type` 相同；合成帧（`client_evicted`/`slow_client_warning`/`stream_error`/`state_resync_required`/`replay_complete`）无 id；`Last-Event-ID` 重放（ring 默认 8000） | qwen-serve-protocol.md §GET /session/:id/events |
| 14 | 取消 | `POST /session/:id/cancel` → **204**，只取消**当前活跃** prompt；已排队 prompt 继续执行（文档化多 prompt 契约） | qwen-serve-protocol.md §cancel ; session.ts（`res.status(204).end()`） |
| 15 | 关闭会话 | `DELETE /session/:id` → 204：取消活跃 prompt、pending permission 置 cancelled、发 `session_closed`、移除 live 会话；**磁盘会话不删**，可 load | qwen-serve-protocol.md §DELETE /session/:id |
| 16 | 中断语义 | prompt HTTP 连接中途断开 → daemon 向 agent 发 ACP cancel；SSE 断流可用 `Last-Event-ID` 续传；**断流/断开都不是完成** | qwen-serve-protocol.md §prompt（"If the HTTP client disconnects mid-prompt…"）; §events |
| 17 | 权限回调 | agent 发 `permission_request`（SSE）→ 客户端显式投票 `POST /session/:id/permission/:requestId`（`{outcome:{outcome:'selected',optionId}}` 或 cancelled）；默认策略 first-responder，**响应超时默认 0 = 无限等待**；绝不自动批 | qwen-serve-protocol.md §permission ; §GET /session/:id/events 事件表 |
| 18 | 协议版本协商 | `GET /capabilities` → `{v:1, protocolVersions:{current:'v1',supported:['v1']}, features:[...], workspaceCwd, workspaces[]}`；v 递增才代表不兼容帧变更；能力用 feature tags | qwen-serve-protocol.md §GET /capabilities |
| 19 | workspace/runtime 归属 | daemon "authenticates the request and resolves the workspace"；"each live workspace runtime owns its own bridge and ACP child"；每个 workspace runtime 生成/预热 `qwen --acp` 子进程（primary 1 个预热 + trusted secondary 按需） | architecture.md ; https://github.com/QwenLM/qwen-code/blob/main/docs/users/qwen-serve.md（"Up to one primary ACP child plus one on-demand child per trusted secondary"） |
| 20 | 权限归属 | agent core 应用 permission policy；acp-bridge **mediating permission requests**；daemon 扇出 SSE、收 HTTP 投票 | architecture.md（packages/core / packages/acp-bridge 职责） |
| 21 | SDK 候选 | TS `@qwen-code/sdk`：`query()` 进程客户端 **＋ `DaemonClient` 消费 serve HTTP/SSE**；Python `qwen-code-sdk`（experimental）v1 只做 `stream-json` CLI 进程传输，明示 **不含 ACP**；Java SDK 独立文档 | https://github.com/QwenLM/qwen-code/blob/main/docs/developers/sdk-typescript.md ; https://github.com/QwenLM/qwen-code/blob/main/docs/developers/sdk-python.md（"v1 targets the existing stream-json CLI protocol"） |
| 22 | ACP 候选 | `qwen --acp` 把 agent 暴露为 ACP transport；`packages/acp-bridge` 负责 channel 生命周期/多路复用/权限中介/进程生成；直接 ACP 客户端自行承担 spawn 与权限应答 | architecture.md §ACP bridge ; https://github.com/QwenLM/qwen-code/blob/main/docs/users/ide-integration/ide-integration.md（IDE 经 ACP） |
| 23 | 设计文档 | serve 协议锁定于 issue #3803 的 §04 routes table；Stage 1 定位"开发者在协议面上做原型/本地单用户" | qwen-serve-protocol.md 首段 ; qwen-serve-user.md §Scope honesty（同上 URL） |
| 24 | 本机安装 | **未安装**（无 `qwen` 可执行文件）；artifact sha256 = unknown（无可摘要物；安装未授权） | 本机检查（L2 未测） |
| 25 | 仓内既有事实 | 管理产物模板引用 `@qwen-code/qwen-code` **0.23.4**、凭证环境引用 `OPENAI_API_KEY`、`QWEN_HOME`、会话状态 `projects/`（与上游 0.24.7 存在版本漂移，登记不调和） | 仓内 `plugins/harness/src/ordessa_harness/qwen/production.py`（ADAPTER_VERSION/QWEN_HOME/STATE_TARGET） |

钉版含义：以上是 2026-10-04 的官方正文/源码状态；升级或换机使 release/revision/协议失效，必须重钉重验（G1）。serve 明确标注 Stage 1 experimental，本单不把其能力升级为稳定承诺。

## 通道决策（serve HTTP/SSE vs SDK vs 原生 ACP）

- **选定：`qwen serve` 环回 HTTP + SSE**（客户端经已冻结 `_http.LoopbackHttpChannel` 消费）。理由：
  1. 与 N001 冻结接缝直接匹配（loopback HTTP + SSE 事件流），不需要新传输；
  2. 有一等公民消费面佐证协议被真实使用：TS SDK `DaemonClient` 与内置 Web Shell 都走同一 HTTP/SSE 协议；
  3. 管理点齐全且显式：`/capabilities` 版本/能力协商、prompt 202 受理回执、按 `promptId` 关联的 SSE 完成帧、cancel 204、权限投票路由、`Last-Event-ID` 重放；
  4. daemon 承担 workspace/runtime/子进程/权限中介，符合"唯一核心、不造第二会话账"。
- **未选：SDK 作为通道**。`@qwen-code/sdk` 不是独立运行时通道：其 `DaemonClient` 只是 serve HTTP/SSE 的库封装（再包一层会与冻结接缝重复），其 `query()` 是 CLI 进程封装；Python SDK v1 明示只做 `stream-json` CLI 进程传输、不含 ACP/daemon，能力面更小。SDK 作为消费者库记录，不作为本家族主通道。
- **未选：原生 ACP（`qwen --acp`）**。ACP 是 serve 的内层执行传输；直接采用意味着由嵌入方自行 spawn、`session/new` 绑 cwd、应答 `session/request_permission`，把 workspace/runtime/权限归属搬进桥（更大的管理面，且是标准上层协议而非 qwen 原生控制面）。登记为候选与后续 L3 备选，不在本单实现/运行。

## 假设攻击结论（serve 源码 vs 文档）

1. **归属问题（serve vs ACP 谁持有 workspace/runtime/权限）**：
   - workspace：**serve daemon** 持有——`--workspace`/process.cwd 注册并 canonicalize，cwd 不匹配 400 `workspace_mismatch`；`/capabilities.workspaceCwd` 是预检源。
   - runtime：**serve daemon** 持有——每个 workspace runtime 拥有自己的 bridge 与 `qwen --acp` 子进程；CLI stdout 只是启动日志（非环回启动路径还会打印 token/QR 秘密），**绝不解析为协议或管理面**。
   - 权限：agent core 应用策略、acp-bridge 中介、**客户端显式 HTTP 投票**；默认 first-responder 且超时默认无限等待。桥/客户端不代替用户投票。
   - 对照：若选 `qwen --acp`，以上三项归嵌入客户端（spawn/`session/new` cwd/`request_permission` 应答），故不选。
2. **会话账**：`POST /session` 缺省 `sessionScope:'single'` 会在同 workspace 二次 create 时 `attached:true` 共享既有会话；桥若默认 single 会与用户会话串账。客户端**默认 `thread`**（独立会话），`attached:true` 原样上抛、绝不改写成"新会话"；sessionId 只来自 daemon，不伪造（G6）。
3. **回执≠完成**：文档与源码一致——prompt 路由返回 202 受理（源码多一个 `eventEpoch` 附加字段，见下），完成帧 `turn_complete`/`turn_error` 由 SSE 按 `promptId` 关联；prompt HTTP 中途断开触发 daemon 侧 ACP cancel。客户端不把 202、断流或 close 当完成。
4. **源码与文档差异（核实后登记）**：
   - `session.ts` 的 202 响应体为 `{ promptId, lastEventId, eventEpoch }`，文档只写 `{promptId,lastEventId}` —— **验证到的附加字段差异**，登记于驱动 `unknown_boundary.source_check`，不据此扩展断言。
   - 文档阶段标签漂移：用户文档仍写 "v0.16-alpha"，而 `packages/cli/package.json`/npm latest 已是 **0.24.7**，serve.ts 自述 "Stage 1 experimental: --http-bridge" —— 登记为漂移，release 仍钉 0.24.7 + main SHA。
   - 取消/建会话源码状态码与文档一致（cancel 204、POST /session 200）；`--port 0` OS 分配为源码 help 原文。
5. **CLI 输出不当完整管理面**：驱动计划不解析 stdout；管理事实只来自协议路由（G5 类比）。非环回启动的 token/QR 属秘密面，计划永不走非环回。
6. **环回特权面**：环回默认无 token 即可执行代码（本地任意进程可驱动 daemon）。计划只允许环回（`--hostname` 不可覆盖）、默认 `--no-web` 关闭预认证静态 Web Shell 面；不注入/不继承任何 token（G9/G12）。

## 实现（CODE_READY + L1；L2 未测）

| 交付 | 位置 | 测试 |
| --- | --- | --- |
| Harness 驱动 | `plugins/harness/src/ordessa_harness/qwen/native_channel.py`（FAMILY_ID="qwen"；channel_report 含上游/许可/0.24.7+revision/Stage 漂移/协议 schema/启动/隔离 QWEN_HOME/网络/认证/session/回调/cancel/ownership/source_check；plan_launch 环回纯计划（禁止相对 workspace、默认 --no-web、port 可选 0）；compile_config 支持键映射+3 拒绝键+未知键发前拒+session_scope 值校验；capability_matrix 三态 observed 全 no） | `plugins/harness/tests/qwen/test_qwen_native_channel.py` **18P/0F** |
| 消费者客户端 | `products/agent-tools/src/ordessa_agent_tools/native_clients/qwen.py`（QwenClient：GET /capabilities 握手、POST /session 默认 thread 且 attached 原样、prompt 202 回执≠完成、SSE 未知原样保留+Last-Event-ID、cancel/close_session 204、respond_permission 显式投票无默认、close 只释放自身；describe 无 runtimeReady） | `products/agent-tools/tests/native_clients/test_qwen_client.py` **14P/0F** |

命令与退出码（家族单元执行；主执行者需复跑）：

```
.venv-ordessa-py312/bin/python -m pytest plugins/harness/tests/qwen -q -p no:cacheprovider                                      # 18 passed, exit 0
.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/native_clients/test_qwen_client.py -q   # 14 passed, exit 0
```

反例 → 门映射：

| 反例 | 测试 | 门 |
| --- | --- | --- |
| 非环回目的地拒绝（example.com） | 客户端 `test_l1_non_loopback_refused`；驱动环回计划不可配 `--hostname` | G9 |
| 缺必需配置/未知键发前拒 | 驱动 4 键参数化拒绝（mcpServers/sandbox/hotModelSwitch/unknownThing）+ invalid session_scope | G3 |
| 相对 workspace 发前拒（daemon 要求绝对路径） | 驱动 `test_plan_launch_rejects_relative_workspace` | G3/QWEN-DOC |
| 未知 SSE 事件原样保留 | 客户端 `test_l1_sse_unknown_preserved_...`（future.unknownType 逐字节 data） | G4 |
| 失回执/服务端错误不重发 | 客户端 `test_l1_api_error_is_typed_and_never_retried`（500 typed，服务端计数==1） | G11 |
| close 后 ChannelClosed | 客户端 `test_l1_close_then_use_is_channel_closed` | G8 |
| 回执≠完成、断流≠完成 | 客户端 `test_l1_send_is_receipt_not_completion`、`test_l1_sse_unknown_preserved_and_stream_end_not_completion` | G6 |
| 无显式选择不发权限票（无默认、无 auto-approve） | 客户端 `test_l1_permission_vote_is_explicit_and_never_automatic`（投票前服务端计数==0） | G4/SAFETY |
| attached 会话不伪造第二会话账 | 客户端 `test_l1_attached_session_is_surfaced_not_rewritten` | G6 |
| 计划纯度（不 spawn、argv 无 token） | 驱动 `test_plan_launch_is_pure` | G8/G12 |
| 无凭据继承（隔离 env 无 KEY/TOKEN/SECRET） | 驱动 `test_plan_launch_env_pins_qwen_home_without_credentials` | G12 |

## 每家矩阵初稿（列取自 specs/030-native-harness-expansion/acceptance.md）

| 列 | 值（2026-10-04，L2 未测） |
| --- | --- |
| familyId | qwen |
| chosenChannel | `qwen serve` 环回 HTTP+SSE（over ACP）；ACP 直连与 SDK 均比较后未选 |
| upstreamRelease/SHA | release **0.24.7**（cli package.json/npm latest）；源码 revision **9915c7ff8ff17a6c5e0840053a0c05bb72eec510**（main，2026-10-04） |
| artifactDigest | unknown（本机未安装；仓内管理产物引用 0.23.4，版本漂移登记） |
| protocolVersion | serve v1（`/capabilities.protocolVersions`）；Stage 1 experimental |
| driverPath | `plugins/harness/src/ordessa_harness/qwen/native_channel.py` |
| clientPath | `products/agent-tools/src/ordessa_agent_tools/native_clients/qwen.py` |
| nativeSessionBinding | 未绑定（029 native session reservation 未交付）；sessionId 仅来自 daemon（`POST /session`），客户端默认 thread、attached 原样 |
| configOwner | qwen 家族 compile_config（G3 发前拒）；serve 启动参数归 plan_launch；MCP/模型热切换归 daemon 运行路由（拒绝键登记） |
| profileKinds | unknown（未测） |
| skill 适用性 | daemon 有 workspace skills 路由/设置面（文档），本切片不接线；unknown（未测） |
| prompt 适用性 | declared yes（POST /session/:id/prompt 202 回执→SSE 完成帧）；implemented yes(client)；observed no |
| model 适用性 | declared yes（session/startup config 与 POST /session/:id/model 路由）；implemented session-field/route-known；hotModelSwitch 配置键发前拒；observed no |
| MCP 适用性 | daemon 运行路由（POST /workspace/mcp/servers 等）为唯一 owner；compile 拒绝 `mcpServers` 键（不吞）；observed no |
| internalSandbox 适用性 | unsupported（compile 拒绝 `sandbox` 键；qwen sandbox 属其 settings/feature 面，不由本家族编译）；observed no |
| approvalCallback | declared yes（permission_request + 投票路由）；implemented vote-route(no-auto)；observed no |
| resume | declared yes（/session/:id/load、/session/:id/resume）；implemented route-known；observed no |
| cancel | declared yes（/cancel 204，仅活跃 prompt）；implemented yes(client)；observed no |
| extensions | unknown 类型/字段原样保留（implemented yes）；observed no |
| transportFence | no（未交付，登记） |
| requestReconciliation | declared yes（promptId + Last-Event-ID）；implemented yes(client)；observed no |
| installScope | 未安装、未分发；安装/更新 = 待授权 |
| L0–L4 证据 | L0✓（本表 25 行逐条 URL）；L1✓（32 用例：驱动 18 + 客户端 14，全 L1 fake 标注）；L2 **未测**（无 CLI）；L3/L4 未测（模型预算 0） |
| 限制 | serve Stage 1 experimental；Stage 1.5/2 未交付；文档版本漂移（v0.16-alpha 标签 vs 0.24.7）；`eventEpoch` 源码附加字段；环回默认 tokenless 特权面；permission 超时默认无限等待；轮询/遥测/自动更新未见文档钉定 |
| 下一步 | 授权后安装 0.24.7 → 隔离 QWEN_HOME 下做 L2（启动/serve 端口发现/capabilities/create(thread)/prompt 202+SSE 完成/cancel/权限投票/退出清理）；重钉 artifact digest；再评估 ACP 直连与 Stage 1.5 变化 |

## 未测清单（一律 unknown，不得当通过）

- **L2 全部未测**：真实 `qwen serve` 启动、端口发现、`/capabilities` 回报、session 创建/附加、prompt→SSE 完成链路、cancel/close、权限投票真机行为、退出码与信号清理（本机无 CLI；安装未授权）。
- 真实 daemon 的 `eventEpoch` 值/epoch 复位行为、replay ring 与 `state_resync_required` 真机路径。
- 非环回/带 token/`--require-auth` 部署形态（本计划只做环回无 token 面，未实测）。
- 权限多客户端策略（designated/consensus/local-only）与超时配置真机行为。
- 会话 load/resume、worktree/branch 隔离、channels、managed runtime 等 serve 扩展面。
- 分离管理绑定（029 AT-009/010/011）依赖阻塞；不发布 runtimeReady；本单终态 **CODE_READY + L1（L2 未测）**。

## 诚实登记

- serve 的 202/SSE 语义按官方正文 + 源码双核："回执≠完成"、"prompt 连接断开触发 cancel"、"SSE 断开可用 Last-Event-ID 续传"；测试不把 fixture 当上游兼容证据，也不把 202 简写成完成。
- 源码核读发现的文档差异（eventEpoch 附加字段、阶段标签 vs 版本号）已逐条记录；未核实项一律 unknown。
- 本证据不含 runtimeReady；capability_matrix 的 observed 全为 no；矩阵中的 unsupported/unknown 均有来源或明确未测标注。
