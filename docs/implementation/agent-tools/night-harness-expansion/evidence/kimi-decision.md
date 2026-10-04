# N006 Kimi 原生通道决策与实现证据

执行：家族单元切片（harness 驱动 + products 消费者客户端），2026-10-04。真实模型调用 0、安装 0、第三方 Harness 更新 0。全部协议事实为 L0（官方文档正文逐条钉定，来源 URL 见下）；全部测试为 **L1 fake peer**（本地脚本模拟 JSON-RPC 2.0 帧，**不冒真实进程**）；本机无 kimi CLI，**L2 未测**。不发布 runtimeReady。

## L0 钉版表（来源 URL + 查阅日期 2026-10-04）

| # | 项目 | 钉定值 | 来源 URL |
| --- | --- | --- | --- |
| 1 | 上游仓库 / 包 | `github.com/MoonshotAI/kimi-cli`（PyPI `kimi-cli`，Python 实现） | https://github.com/MoonshotAI/kimi-cli |
| 2 | 许可 | **Apache-2.0**（LICENSE 原文头部确认） | https://raw.githubusercontent.com/MoonshotAI/kimi-cli/main/LICENSE |
| 3 | release 钉版 | **1.52.0**（`releases/latest` 重定向至 `tag/1.52.0`；changelog 记录 1.52.0 (2026-09-22) 为 final release） | https://github.com/MoonshotAI/kimi-cli/releases/latest ; https://moonshotai.github.io/kimi-cli/en/release-notes/changelog.html |
| 4 | 上游状态 | **已归档**（README CAUTION：read-only、不再发版/修复；迁移至 Kimi Code CLI） | https://github.com/MoonshotAI/kimi-cli （README） |
| 5 | 后继产品 | `MoonshotAI/kimi-code`（Kimi Code CLI）；其官方文档索引**无 Wire mode 页**（提供 Server API/ACP 等）；Wire 是否延续 = **unknown（迁移未验证）** | https://moonshotai.github.io/kimi-code/llms.txt |
| 6 | 通道入口 | `kimi --wire`（Wire server mode，experimental；与 shell/--print/--acp 互斥） | https://moonshotai.github.io/kimi-cli/en/customization/wire-mode.html ; https://moonshotai.github.io/kimi-cli/en/reference/kimi-command.html |
| 7 | 传输形态 | JSON-RPC 2.0 over stdin/stdout；每条消息一行 JSON（含 `jsonrpc`/`id`/`method`/`params`/`result`/`error` 全字段） | wire-mode.html |
| 8 | 协议版本 | **Wire 1.10**（正文："The current protocol version is 1.10"；1.10 增加 `StepRetry` 事件） | wire-mode.html ; changelog.html |
| 9 | 版本协商字段 | `initialize`（Wire 1.1+，可选）：请求 `params.protocol_version` + `client` + `capabilities`(supports_question, supports_plan_mode) + `external_tools` + `hooks`；响应 `protocol_version` + `server` + `slash_commands` + `capabilities` + `external_tools`。**mismatch 策略文档未写**；服务器不支持 `initialize` → `-32601` → 客户端按文档回退 no-handshake（legacy 客户端可直接发 `prompt`） | wire-mode.html |
| 10 | prompt | 请求 `params.user_input`；运行中发 `event`/`request`；**response 在 turn 完成后返回**，`result.status ∈ finished｜cancelled｜max_steps_reached`；错误码 -32000 turn 进行中 / -32001 LLM 未配置 / -32002 不支持的 LLM / -32003 LLM 服务错误 | wire-mode.html |
| 11 | replay | Wire 1.3+；读取 session 目录 `wire.jsonl`，按序**只读重发**记录的 event 与 request；文档明确 "clients should not respond to replayed request messages"；result `{status, events, requests}`（无历史则 0/0） | wire-mode.html ; data-locations.html |
| 12 | steer | Wire 1.4+；注入运行中的 turn（不新开 turn），result `{"status":"steered"}`；无 turn → -32000 "No agent turn is in progress"；消费时发 `SteerInput` 事件 | wire-mode.html |
| 13 | set_plan_mode | Wire 1.4+；需 initialize 声明 `supports_plan_mode: true`；状态持久化到 session | wire-mode.html |
| 14 | cancel | 无参数；运行中的 prompt 随后返回 `{"status":"cancelled"}`，replay 返回 cancelled 与已发计数 | wire-mode.html |
| 15 | 反向请求（agent→client） | 方法 `request`，`params.type ∈ ApprovalRequest｜ToolCallRequest｜QuestionRequest｜HookRequest`；**必须同 JSON-RPC id 应答**。Approval result `{request_id, response ∈ approve｜approve_for_session｜reject, feedback?}`；Question result `{request_id, answers}`（空 answers=不支持/关闭面板）；ToolCall result `{tool_call_id, return_value}`；Hook result `{request_id, action ∈ allow｜block, reason}` | wire-mode.html |
| 16 | 事件类型 | `event` notification，`params {type, payload}`：TurnBegin、TurnEnd、StepBegin、StepInterrupted、StepRetry(1.10)、CompactionBegin/End、StatusUpdate、ContentPart、ToolCall/ToolCallPart/ToolResult、ApprovalResponse、SubagentEvent、BtwBegin/BtwEnd、SteerInput、PlanDisplay、HookTriggered/HookResolved | wire-mode.html |
| 17 | 启动参数 | `kimi --wire [--work-dir <d>] [--session <id>｜--resume <id>｜--continue] [--model <m>] [--thinking｜--no-thinking] [--config <json>｜--config-file <p>] [--skills-dir <p>] [--mcp-config-file <p>]`；`--yolo/--yes/--auto-approve/--afk` 是自动批审（本家族**从不计划/从不使用**）；裸跑 `kimi`（无参数）会从 CDN 下载并执行安装脚本 | kimi-command.html |
| 18 | 隔离目录 | `KIMI_SHARE_DIR`（默认 `~/.kimi`）承载 config.toml、kimi.json、mcp.json、credentials/、mcp-oauth/、sessions/<work-dir-md5>/<session-id>/{context.jsonl,wire.jsonl,state.json}、plans/、logs/；`KIMI_SHARE_DIR` 不影响 skills 搜索路径 | env-vars.html ; data-locations.html |
| 19 | 会话创建/恢复 | 每次启动自动新建会话；`--session <id>` 不存在时自动新建；`--continue` 续最近；`/new`、`/sessions`；session state（approval/plan/subagent/additional_dirs）随恢复还原；启动时重放历史 | sessions.html ; data-locations.html |
| 20 | 认证 | `KIMI_API_KEY`/`KIMI_BASE_URL`/`KIMI_MODEL_*` 环境变量覆盖；或 `<KIMI_SHARE_DIR>/config.toml` 的 providers/models；OAuth 凭据在 `<KIMI_SHARE_DIR>/credentials/`（`kimi login`） | env-vars.html ; data-locations.html |
| 21 | 默认网络行为 | 模型调用是唯一任务流量；`KIMI_CLI_NO_AUTO_UPDATE=1` 关闭自动更新（含启动阻断更新门）；**`telemetry` 配置默认 true 且无环境变量开关**（文档值，未实测）；无模型时 prompt → -32001 | env-vars.html ; config-files.html |
| 22 | ACP 候选 | `kimi acp` = 多会话 ACP server；创建/加载会话前检查认证，未登录返回 AUTH_REQUIRED（code -32000） | https://moonshotai.github.io/kimi-cli/en/reference/kimi-acp.html ; https://moonshotai.github.io/kimi-cli/en/guides/ides.html |
| 23 | Rust 变体 | `kimi-agent`（`MoonshotAI/kimi-agent-rs`，experimental，独立发版）：vendor 自称 Wire 协议兼容且 "existing clients need no modifications"，但文档限制：Wire only、Kimi provider only、无账号 login、无 `--prompt/--command`、仅本地执行、MCP OAuth 存储不同（`~/.kimi/credentials/mcp_auth.json` vs Python `~/.kimi/mcp-oauth/`） | wire-mode.html（Kimi Agent (Rust) Wire server 章节） |
| 24 | 本机安装 | **未安装**（无 `kimi`/`kimi-agent` 可执行文件）；artifact sha256 = unknown（无可摘要物；安装/更新未授权） | 本机检查（L2 未测） |

钉版含义：以上是 2026-10-04 官方正文状态；任何升级/换机都使 release 与协议版本失效，必须重钉重验（G1）。**上游已归档**是本单最大的外部边界：本切片钉的是最终 Python 实现的文档状态，后继 `kimi-code` 是否保留 Wire 通道 unknown。

## 通道决策（Wire vs ACP）

- **选定：原生 Wire（`kimi --wire`）**。理由：Wire 是本家族暴露给外部的**最底层原生协议**（官方定义 "The message-passing layer used internally by Kimi Code CLI"，终端 Shell 与 ACP server 都经它与 agent core 通信）；question/approval 反向请求、steer、replay、cancel 全部攻击点都在 Wire 面有文档化语义；JSON-RPC 2.0 与已冻结 stdio 传输接缝直接匹配。
- **未选：ACP（`kimi acp`）**。ACP 是标准化上层（IDE 集成/多会话），且 ACP server 在创建/加载会话前要求已登录（AUTH_REQUIRED -32000），把认证与 ACP 会话语义引入通道；N006 范围是原生切片，故登记为候选并保留 URL，不实现、不运行。若后续要 L3 闭环，ACP 是次选入口（需要在已登录环境下另行评估）。
- **后继产品**：`kimi-code` 文档只有 Server API（REST/WS，experimental，需 bearer token）与 ACP，无 Wire 页；**不作为本单通道**，迁移结论登记 unknown。
- **升级边界**：无自动版本协商可依赖（见下）；wire protocol 仅 `initialize.protocol_version` 声明/回报；升级须按 G1 重钉 release + 重跑 L1/L2。

## 假设攻击四点结论

1. **Wire 版本协商**：可协商字段只有 `initialize` 的 `protocol_version`（请求声明、响应回报）；**不匹配如何处理文档未写** → 驱动 `channel_report().protocol.version_negotiation.mismatch_policy = "unknown"`；客户端 `initialize()` 返回 `version_match: True/False/"unknown"`（服务器未回报即 unknown），**不自动降级、不重试、不臆造兼容结论**；`-32601` 走文档明确规定的 no-handshake 回退（实现 + fake 测试）。
2. **question/approval 反向请求**：方法名 `request`，以 `params.type` 区分（ApprovalRequest/QuestionRequest/ToolCallRequest/HookRequest）；应答必须同 JSON-RPC id，且 result 内的 `request_id`/`tool_call_id` 回显 payload 自带 id；审批枚举 `approve|approve_for_session|reject`。客户端**永不 auto-approve**：无调用方 handler 时帧原样滞留 `unanswered_requests()`，不写任何 reply；显式应答必须由调用方给 decision/answers（无默认值）。
3. **steer / replay**：steer 只注入不新开 turn（`status:"steered"`；无 turn -32000）。replay 是**只读**历史重放（`wire.jsonl`），文档明文 "clients should not respond to replayed request messages"；客户端实现**显式防线**：replay 窗口内到达的 `request` 帧不投递给任何 handler，id 进入 fence 集合，此后 `reply_approval/reply_question/reply_request/reply_request_error` 一律抛 `ReplayResponseRefused`；fake 测试断言 peer 只收到 1 次 replay 写、replies=0（历史审批没有被二次批准）。
4. **Rust 不得冒充 Python 同能力**：`KimiWireClient.launch()` 在 spawn 前校验 argv 必须含 `--wire`（`kimi-agent` 无此 flag），否则 `ValueError` 发前拒（测试 monkeypatch `subprocess.Popen` 证明未启动任何进程）；驱动 `channel_report().variants.rust` 与 `capability_matrix().rustVariant` 登记能力差异（Wire only / Kimi provider only / 无 login / 无 `--prompt/--command` / MCP OAuth 存储不同）；客户端不承诺与 Rust 变体互换。

## 实现（CODE_READY + L1；L2 未测）

| 交付 | 位置 | 测试 |
| --- | --- | --- |
| Harness 驱动 | `plugins/harness/src/ordessa_harness/kimi/native_channel.py`（FAMILY_ID="kimi"；channel_report 含上游/许可/归档/协议 schema 来源/1.10/launch/隔离 KIMI_SHARE_DIR/网络/认证/session-replay/回调/cancel/unknown/升级；plan_launch 纯计划；compile_config {model,provider,thinking,session,replay} 映射+provider deferred+发前拒；capability_matrix 三态） | `plugins/harness/tests/kimi/test_kimi_native_channel.py` **19P/0F** |
| 消费者客户端 | `products/agent-tools/src/ordessa_agent_tools/native_clients/kimi.py`（KimiWireClient：initialize 版本协商+no-handshake 回退、create_session 保持 prepared、send_prompt 原样终态、events/inbound/unanswered 原样保留、reply_approval/reply_question/reply_tool_call 同 id、replay fence、steer/cancel/set_plan_mode、close；describe 无 runtimeReady） | `products/agent-tools/tests/native_clients/test_kimi_client.py` **19P/0F** |

命令与退出码（家族单元执行；主执行者需复跑）：

```
.venv-ordessa-py312/bin/python -m pytest plugins/harness/tests/kimi -q -p no:cacheprovider                                      # 19 passed, exit 0
.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/native_clients/test_kimi_client.py -q   # 19 passed, exit 0
```

反例 → 门映射：

| 反例 | 测试 | 门 |
| --- | --- | --- |
| replay 历史审批拒绝应答（显式 reply 亦拒） | `test_replay_history_requests_are_fenced_and_never_answered` | N006 fence / G4 |
| 失回执不重发（peer 只收到一次写） | `test_prompt_timeout_is_typed_and_never_resent`（stderr `recv=1 replies=0`） | G11 |
| 超时 typed 失败 | 同上（`RequestTimeout(method="prompt")`，pending 保持 unknown） | G5/G11 |
| 缺配置发前拒 | `test_launch_requires_wire_entry_before_spawn`、`test_launch_refuses_auto_approve_flags_before_spawn`；驱动 4 个拒绝键参数化 | G3/G1/SAFETY |
| 两请求 id 不串（乱序回执） | `test_nested_steer_and_prompt_ids_do_not_cross`（prompt 回执先于 steer 回执到达仍各归其位） | G6 |
| 陌生 event 原样保留 | `test_unknown_event_type_preserved_verbatim` | G4 |
| 同 id 回调（approval+question） | `test_live_approval_and_question_answered_on_same_jsonrpc_id` | G4 |
| 无 handler 绝不 auto-approve | `test_inbound_request_without_handler_is_never_auto_approved`（peer replies=0） | G4/SAFETY |
| 版本回报/不匹配/-32601 回退 | `test_initialize_negotiates_version_fields_verbatim`、`..._mismatch_...`、`..._unsupported_...` | G1 |
| create session 不伪造 id、不发帧 | `test_create_session_stays_prepared_and_sends_nothing`（peer `recv=0`） | G6 |
| close 只释放 own 进程 | `test_close_releases_only_owned_process` | G8 |
| 对未见 request 不编造 payload 身份 | `test_reply_to_unknown_request_id_refuses_to_fabricate_identity` | G4 |

## 每家矩阵初稿（列取自 specs/030-native-harness-expansion/acceptance.md）

| 列 | 值（2026-10-04，L2 未测） |
| --- | --- |
| familyId | kimi |
| chosenChannel | 原生 Wire（`kimi --wire`，JSON-RPC 2.0 stdio）；ACP 候选未选（认证门+上层协议） |
| upstreamRelease/SHA | release tag **1.52.0**（PyPI `kimi-cli`，**已归档 final**）；源码 commit SHA 未钉（未下载源码）unknown |
| artifactDigest | unknown（本机未安装，无可摘要物） |
| protocolVersion | Wire **1.10**（initialize.protocol_version） |
| driverPath | `plugins/harness/src/ordessa_harness/kimi/native_channel.py` |
| clientPath | `products/agent-tools/src/ordessa_agent_tools/native_clients/kimi.py` |
| nativeSessionBinding | 未绑定（029 native session reservation 未交付；session 由 CLI launch 创建；客户端 create_session=prepared） |
| configOwner | kimi 家族 compile_config（G3 发前拒）；provider 归 config-file owner（deferred，不造 guessed flag） |
| profileKinds | unknown（未测；model/thinking 是启动级参数） |
| skill 适用性 | 无文档化禁用开关（--skills-dir 只追加）；scratch HOME 隔离 user 级；项目级可见（declared，未观察） |
| prompt 适用性 | declared yes（Wire prompt，response 带终态）；L2 未测 |
| model 适用性 | declared yes（launch --model；无 wire set_model 热切换 → hotModelSwitch 发前拒） |
| MCP 适用性 | 文件 owner（mcp.json/--mcp-config-file）；compile 拒绝 `mcpServers` 键（不吞） |
| internalSandbox 适用性 | unsupported（无文档；compile 拒绝 `sandbox` 键） |
| approvalCallback | declared yes（ApprovalRequest）；implemented yes(client, caller-decides, 无默认)；observed no |
| resume | declared yes（--session/--continue launch 级）；implemented plan-only；observed no |
| cancel | declared yes（cancel；prompt 返回 cancelled）；implemented yes(client)；observed no |
| extensions | unknown 类型/字段原样保留（implemented yes）；observed no |
| transportFence | no（未交付，登记） |
| requestReconciliation | declared yes（同 id + 乱序回执按 id 归位）；implemented yes(client)；observed no |
| installScope | 未安装、未分发；安装/更新=待授权 |
| L0–L4 证据 | L0✓（本表 24 行逐条 URL）；L1✓（38 用例：驱动 19 + 客户端 19，全部 fake/L1 标注）；L2 **未测**（无 CLI）；L3/L4 未测（模型预算 0） |
| 限制 | 上游 archived→后继 Wire 未验证；mismatch 策略 unknown；telemetry 默认 true 未实测关闭；Rust 变体不同能力；无 wire session-create；无 wire模型热切换 |
| 下一步 | 授权后安装 1.52.0（或评估后继 kimi-code）→ 隔离 KIMI_SHARE_DIR 下做 L2：启动/initialize 回报/no-model prompt(-32001)/cancel/replay 空历史/退出清理；重钉 artifact digest；再评估 ACP 与后继迁移 |

## 未测清单（一律 unknown，不得当通过）

- **L2 全部未测**：真实 `kimi --wire` 进程启动、握手、事件流、退出码与信号清理（本机无 CLI；安装/更新未获授权）。
- 真实 server 的 `protocol_version` 回报与不匹配行为；`-32601` 回退仅按文档在 L1 模拟。
- 会话恢复（`--session`/`--continue`）、`wire.jsonl` replay 的真机语义（本单只钉文档并实现 fence）。
- 无模型 prompt 的 -32001 真机行为；模型调用（L4）预算 0，未做。
- 隔离下 skills/plugins/hooks/MCP 实际效果；telemetry 与自动更新在 wire 模式的真实网络行为。
- Rust `kimi-agent` 实机、后继 `kimi-code` 的 Wire/迁移结论、ACP 运行时。
- 管理绑定（029 AT-009/010/011）依赖阻塞；不发布 runtimeReady；本单终态 **CODE_READY + L1（L2 未测）**。

## 诚实登记

- “回执≠完成”按官方正文裁决：`prompt` 的 response 只在 turn 完成时返回并携带终态；**写入成功不是完成**、缺响应=unknown 且不重发；测试不把 response 简写成“已完成”，也不把 fixture 当上游兼容证据。
- 上游 2026-09-22 归档（1.52.0 final）是重大边界；Wall-clock 与文档状态可能演进，升级必须重钉重验（G1）。
- 本证据不含 runtimeReady；所有 observed 保持 no/unknown；矩阵中的 unsupported/unknown 均有文档依据或明确标注未测。
