# N009 GitHub Copilot CLI 原生通道决策与实现证据

执行：家族单元切片（harness 驱动 + products 消费者客户端），2026-10-04。真实模型调用 0、安装 0、CLI/SDK 运行 0。全部协议事实为 **L0**（官方文档正文 + `github/copilot-sdk` main 分支一手源码逐条钉定，来源 URL 见下）；全部测试为 **L1 fake peer**（本地脚本模拟 JSON-RPC 帧，**不冒真实进程**）；本机无 `copilot` CLI，**L2 未测**。不发布 runtimeReady。

## L0 钉版表（来源 URL + 查阅日期 2026-10-04）

| # | 项目 | 钉定值 | 来源 URL |
| --- | --- | --- | --- |
| 1 | 上游 SDK 仓库 / 包 | `github/copilot-sdk`；Node `@github/copilot-sdk`、Python `github-copilot-sdk`、Go/.NET/Rust/Java 同名 SDK | https://github.com/github/copilot-sdk （README） |
| 2 | SDK 许可 | **MIT**（LICENSE 原文 "Copyright GitHub, Inc."） | https://raw.githubusercontent.com/github/copilot-sdk/main/LICENSE |
| 3 | CLI 仓库 | `github/copilot-cli`（release-only 分发：tar.gz/msi/deb/rpm + install.sh） | https://github.com/github/copilot-cli |
| 4 | CLI 许可 | **GitHub Copilot CLI License**（自定义：仅允许未修改再分发、且必须作为提供额外实质功能的应用/服务的一部分、不得独立分发；禁止修改/派生） | https://raw.githubusercontent.com/github/copilot-cli/main/LICENSE.md |
| 5 | SDK release 钉版 | **v1.0.16**（published 2026-09-30；release body: "refreshes the SDK snapshot for Copilot CLI 1.0.90"） | https://api.github.com/repos/github/copilot-sdk/releases/latest |
| 6 | CLI release 钉版 | **v1.0.91**（published 2026-10-01，releases/latest 重定向确认；SDK v1.0.16 内含快照 1.0.90） | https://api.github.com/repos/github/copilot-cli/releases/latest |
| 7 | 协议版本 | **3**（`sdk-protocol-version.json` = `{"version": 3}`；python SDK `_MIN_PROTOCOL_VERSION = 3`，min==max） | https://raw.githubusercontent.com/github/copilot-sdk/main/sdk-protocol-version.json ; https://raw.githubusercontent.com/github/copilot-sdk/main/python/copilot/client.py |
| 8 | 通道 | SDK↔CLI = **JSON-RPC to the Copilot CLI server**；SDK "manages the CLI process lifecycle automatically"；可连外部 server（cliUrl） | README ; https://raw.githubusercontent.com/github/copilot-sdk/main/docs/getting-started.md |
| 9 | CLI server 模式 | `copilot --headless --port 4321`（省略端口=随机；默认仅 loopback `127.0.0.1`；`--host` 放开）；SDK 子进程 argv = `<cli> --headless --no-auto-update --log-level <lvl> [--no-auto-login] [--session-idle-timeout N] [--remote] --stdio` | backend-services.md ; client.py `_start_cli_server` |
| 10 | stdio 佐证 | 调试文档给出 `copilot --server --stdio`；`--server` 与 `--headless` 是否别名**未验证 → unknown**（本客户端只计划/只接受 `--headless`+`--stdio`） | https://raw.githubusercontent.com/github/copilot-sdk/main/docs/troubleshooting/debugging.md |
| 11 | 握手 | `connect`（文档名 `server.connect`）：`supportedTaskKinds: [agent, client, shell]` + 可选 `token`/`clientInfo{applicationName,applicationVersion,integrationName,integrationVersion}`；result `protocolVersion`；legacy server 回 `-32601` 时回退 `ping` | client-info.md ; client.py `_verify_protocol_version` |
| 12 | 版本门 | 版本不可报或超出 [3,3] = **硬错误**（SDK raise "protocol version mismatch"），无降级、无重试 | client.py |
| 13 | 会话创建/恢复 | `session.create` / `session.resume`（SDK 直接 `request("session.create"/"session.resume", payload)`，response 携带 `sessionId`；未给 id 时 runtime 生成且不可恢复）；recovery 失败码 `-32075` | client.py/session.py ; session-persistence.md |
| 14 | 会话状态位置 | `~/.copilot/session-state/{sessionId}/`（checkpoints/、plan.md、files/；SDK `base_directory` → 子进程 `COPILOT_HOME`，默认 `~/.copilot`） | session-persistence.md ; client.py |
| 15 | 发送语义 | `session.send` 入参 `prompt`、`wait`（**默认 false**，fire-and-forget）、`mode`(enqueue/immediate)、`responseFormat` 等；result = `{messageId}` **回执**；`wait=true` 亦只保证同 `messageId` | generated/rpc.py `SendRequest`/`SendResult` ; session.py `send` |
| 16 | 完成信号 | 完成事件 = `session.idle`（另有 `session.task_complete`、`assistant.turn_end`）；事件类型 40+，含 `permission.requested/completed`、`user_input.*`、`elicitation.*`、`abort` | streaming-events.md |
| 17 | 取消 | `session.abort` `{sessionId}` → `{success, error}`（nodejs SDK `session.abort()` "Abort the currently processing message in this session"）；另有 `session.interruptMainTurn`（生成面存在，语义未验证） | session.py `abort` ; generated/rpc.py `AbortRequest/AbortResult` ; nodejs/README.md |
| 18 | 权限回调 | 事件 `permission.requested`/`permission.completed` + pending permission RPC（`session.permissions.handlePendingPermissionRequest`）；无 handler 时 SDK 以 `user-not-available` 处理（**不是 approve-all**）；结果形状为带 `kind` 的 mapping | streaming-events.md ; session.py ; python README |
| 19 | 权限决策枚举 | `PermissionDecisionKind`：`approve-once`、`approve-for-session`、`approve-for-location`、`approve-permanently`、`approve-read-only-for-session`、`reject`、`cancelled`、`user-not-available`、以及拒绝类 `denied-*`；`no-result` 是 SDK "leave unanswered" 哨兵（不作决策） | generated/rpc.py ; nodejs/README.md |
| 20 | 认证 | 显式 SDK token > Copilot 环境认证 > 环境变量 GitHub token（`COPILOT_GITHUB_TOKEN` > `GH_TOKEN` > `GITHUB_TOKEN`）> 存储的 Copilot CLI 凭据 > GitHub CLI 凭据；支持 BYOK；OAuth 是 authorization-code 流程（**非 device flow**），token 类型 `gho_`/`ghu_`/`github_pat_` 可用、`ghp_` 废弃 | auth/README.md ; setup/local-cli.md ; setup/github-oauth.md |
| 21 | `COPILOT_TOKEN` | 官方文档未出现 → **unknown**（本实现不使用） | 上列 auth 文档交叉检索 |
| 22 | SDK 自动下载 | Python：推荐 `python -m copilot download-runtime`（一次性），**跳过则首次使用自动下载匹配 runtime**；缓存 `~/.cache/github-copilot-sdk/cli/{version}/prebuilds/{platform}/`（macOS Library/Caches、Windows LOCALAPPDATA）；下载校验 release `SHA256SUMS.txt`；`COPILOT_CLI_EXTRACT_DIR`/`COPILOT_SKIP_CLI_DOWNLOAD`/`COPILOT_CLI_DOWNLOAD_BASE_URL` 可覆盖；Node/.NET 直接捆绑为依赖；Go/Java/Rust 不默认捆绑 | setup/bundled-cli.md ; python `_cli_download.py` / `_cli_version.py` ; README |
| 23 | 进程/凭据路径 | 解析顺序 **explicit path > `COPILOT_CLI_PATH` > downloaded runtime**；SDK 设置 `COPILOT_HOME`；`mode="empty"` 时设 `COPILOT_DISABLE_KEYTAR=1`（"so per-tenant credentials don't leak through a shared keytar store"）；SDK 可注入 `COPILOT_SDK_AUTH_TOKEN` | client.py `_resolve_runtime_entrypoint` / `_start_cli_server` |
| 24 | SDK 日志 | 默认 `copilot-cli` 模式日志在 Copilot home 的 logs 目录（`process-<ts>-<pid>.log`），`--log-dir` 改址；SDK 传 `--log-level`，可选 none/error/warning/info/debug/all | debugging.md |
| 25 | 上游产品声明 | README："Full control: Preview every action before execution — nothing happens without your explicit approval"；premium request 计费与 CLI 相同；需要 Copilot 订阅（BYOK 除外） | github/copilot-cli README ; copilot-sdk README |
| 26 | 本机安装 | **未安装**（无 `copilot` 可执行文件）；artifact sha256 = unknown（无可摘要物；安装/更新未授权） | 本机检查（L2 未测） |

钉版含义：以上是 2026-10-04 官方文档 + `copilot-sdk` main 源码状态；上游迭代快（README 明言 "We're building quickly"），任何升级/换机都使 release、CLI 快照与协议版本失效，必须重钉重验（G1）。

## 通道决策（CLI server JSON-RPC vs 直接用 SDK）

- **选定：CLI server 原生 JSON-RPC（`copilot --headless --stdio`，协议 v3）**。理由：SDK 与 CLI 之间就是这条 JSON-RPC 通道（README 图示 `Application → SDK Client → JSON-RPC → Copilot CLI (server mode)`），它与 N001 冻结的 stdio/JSON-RPC 传输接缝直接匹配；会话创建/恢复、send 回执、权限回调、abort 全部在该面有文档/一手源码语义。
- **未选：直接依赖 `@github/copilot-sdk` / `github-copilot-sdk` 包**。理由（N009 指定攻击点，见下节）：SDK 自动下载/托管 CLI 进程、读取账号环境（`COPILOT_HOME`、keychain、`COPILOT_SDK_AUTH_TOKEN`），违反 G12 "不得继承用户认证/home"；且 SDK 语义层会隐藏进程 ownership，与 G8 "仅清理 owned 进程" 冲突。SDK 仅作为 L0 文档/源码来源。
- **TCP（`--headless --port N`）未选**：文档明言 "No built-in auth between SDK and CLI"，端口模式引入本机网络面；本切片只用 stdio。
- **升级边界**：握手 `connect` 回报整数 `protocolVersion`，SDK 侧 min==max==3，超范围硬失败；升级须按 G1 重钉 release + 重跑 L1/L2。

## SDK 自动管理进程风险专节（本单核心攻击点）

官方文档与一手源码钉定的 SDK 行为（全部 2026-10-04 阅读）：

1. **自动下载**：Python SDK 首次使用会自动下载匹配 runtime（`ensure_runtime_wrapper()`；`download-runtime` 是"推荐的一次性步骤"而非必需门），下载自 `github.com/github/copilot-cli/releases/download/v<ver>/…`（unstable 快照用 `github/copilot-sdk` 的 `runtime-*` tag），并用 release `SHA256SUMS.txt` 校验后解包进 `~/.cache/github-copilot-sdk/cli/{version}/prebuilds/{platform}/`；Node/.NET SDK 把 CLI 作为依赖捆绑；Go/Rust 可回退 PATH 上的 `copilot`（`COPILOT_CLI_PATH`）。
2. **进程托管**：SDK 默认 spawn 并持有 CLI 子进程（"the SDK manages the CLI process lifecycle automatically"、"CLI Process … dies with app"），argv 含 `--headless --no-auto-update --log-level`，stdio 或 TCP 可选；外部 server 模式才不 spawn。
3. **账号环境读取**：SDK 默认 `use_logged_in_user = not github_token`；CLI 读取 `COPILOT_HOME`（默认 `~/.copilot`）下的存储 OAuth 凭据，SDK 可注入 `COPILOT_SDK_AUTH_TOKEN`，并可通过 `COPILOT_DISABLE_KEYTAR` 控制共享 OS keychain 探针（证明存在 keychain 复用面）。
4. **二进制解析顺序**：explicit > `COPILOT_CLI_PATH` > 下载 runtime——PATH 同名不同程序（G1 反例）在 SDK 默认路径上真实存在。
5. **本切片反制（已实现并测试）**：
   - 驱动/客户端**从不调用 SDK**；`plan_launch` 要求调用方显式传入受控二进制路径（无默认值、不解析 PATH）；
   - 计划强制 `--headless --stdio --no-auto-update --no-auto-login`，env 设 `COPILOT_SKIP_CLI_DOWNLOAD=1`、`COPILOT_DISABLE_KEYTAR=1`，`COPILOT_HOME` 钉进 scratch；
   - 客户端 `launch()` 在 spawn 前拒绝缺 server 标志/空 argv/自动批审标志的 spec（monkeypatch `subprocess.Popen` 测试证明零 spawn）；
   - 客户端**没有 token 参数**，不传 `COPILOT_SDK_AUTH_TOKEN`；驱动 `compile_config` 对任何 token 形键（TOKEN/SECRET/PASSWORD/CREDENTIAL/APIKEY）发前拒；
   - 清理只走 `ProcessChannel.close()`（owned 子进程，G8）。
6. **未实测**：以上反制在真实 CLI 上的运行效果属于 L2，未做（无 CLI、未授权安装/认证）。SDK 自动下载是否在无网环境降级等行为 = unknown。

## 实现（CODE_READY + L1；L2 未测）

| 交付 | 位置 | 测试 |
| --- | --- | --- |
| Harness 驱动 | `plugins/harness/src/ordessa_harness/copilot/native_channel.py`（FAMILY_ID="copilot"；channel_report 含 upstream/双许可/release 钉版+本机 unpinned 登记/协议 v3/sdk_process_management 风险专节/launch/隔离/认证/session/回调/cancel/unknown/升级边界；plan_launch 纯计划且 executable 显式参数化；compile_config {model,reasoning_effort,session_id,log_level,session_idle_timeout}，hotModelSwitch/sandbox/mcpServers/未知键/全部 token 类键发前拒；capability_matrix 三态全 observed=no） | `plugins/harness/tests/copilot/test_copilot_native_channel.py` **22P/0F** |
| 消费者客户端 | `products/agent-tools/src/ordessa_agent_tools/native_clients/copilot.py`（CopilotClient：connect/initialize 协议门 v3 + legacy -32601 ping 回退、create_session/resume_session 原生 sessionId、send 回执≠完成、wait_idle=session.idle、events 未知原样保留、unanswered_requests、reply_permission 同 id 且永不 auto-approve、cancel=session.abort、command、close；describe 无 runtimeReady） | `products/agent-tools/tests/native_clients/test_copilot_client.py` **22P/0F** |

命令、计数与退出码（家族单元执行；主执行者需复跑）：

```
.venv-ordessa-py312/bin/python -m pytest plugins/harness/tests/copilot -q -p no:cacheprovider                                      # 22 passed, exit 0
.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/native_clients/test_copilot_client.py -q   # 22 passed, exit 0
```

反例 → 门映射：

| 反例 | 测试 | 门 |
| --- | --- | --- |
| 配置含 token 类键（GH_TOKEN/github_token/COPILOT_GITHUB_TOKEN/providerToken/apiKey）发前拒 | 驱动 `test_compile_config_refuses_token_class_keys`（5 参数） | G12 |
| hotModelSwitch/sandbox/mcpServers/未知键发前拒 | 驱动 `test_compile_config_refuses_second_ownership_and_unknown_keys`（4 参数） | G3 |
| 协议版本超范围（v2）硬失败、不降级不重试 | 客户端 `test_out_of_range_protocol_is_a_hard_failure`（peer 只收到 1 次 connect） | G1 |
| auto-approve 不存在：非法决策 ValueError + 无 helper + 决策表无该值 | 客户端 `test_invalid_permission_decision_rejected_and_no_auto_approve_helper` | G4/SAFETY |
| 无 handler 的权限回调绝不自动应答（peer replies=0） | 客户端 `test_permission_without_handler_is_never_auto_approved` | G4/SAFETY |
| 权限回调同 id 应答且只发调用方决策 | 客户端 `test_permission_callback_answered_on_same_id`（peer decisions=["reject"]，replies=1） | G4 |
| 失回执：typed timeout、ledger 保持 unknown、peer 恰一次写 | 客户端 `test_lost_receipt_timeout_never_resent`（session.send 计数=1） | G11 |
| 未知事件原样保留 | 客户端 `test_unknown_events_preserved_verbatim` | G4 |
| 缺配置发前拒（未握手 / 无 session）零帧写出 | 客户端 `test_send_before_connect_is_refused_before_any_write`（recv=0）、`test_send_without_session_is_refused_before_any_write`（仅 connect） | G3 |
| 缺 server 标志/空 argv/自动批审标志的 launch spec 零 spawn 发前拒 | 客户端 `test_launch_requires_server_mode_before_spawn`、`test_launch_refuses_auto_approve_flags_before_spawn`、`test_empty_argv_is_refused_before_spawn` | G1/SAFETY |
| close 后使用 = ChannelClosed，仅释放 owned 进程 | 客户端 `test_close_then_use_is_channel_closed` | G6/G8 |
| 对未见 request id 不伪造权限应答 | 客户端 `test_reply_permission_for_unseen_request_is_refused` | G4 |
| 驱动无 runtimeReady、矩阵无 observed=yes、release unpinned 登记 | 驱动 `test_channel_report_has_no_runtime_ready_claim_and_pins_release`、`test_capability_matrix_is_honest`、`test_channel_report_documents_sdk_auto_download_and_mitigation` | EVIDENCE |

## 每家矩阵初稿（列取自 specs/030-native-harness-expansion/acceptance.md）

| 列 | 值（2026-10-04，L2 未测） |
| --- | --- |
| familyId | copilot |
| chosenChannel | CLI server 原生 JSON-RPC v3 stdio（`copilot --headless --stdio`）；SDK 未采用（自动下载/托管进程/账号环境风险）；TCP 未选 |
| upstreamRelease/SHA | SDK **v1.0.16**（2026-09-30，含 CLI 快照 1.0.90）；CLI **v1.0.91**（2026-10-01）；源码 commit SHA 未钉（未得授权下载源码）unknown |
| artifactDigest | unknown（本机未安装，无可摘要物） |
| protocolVersion | **3**（`sdk-protocol-version.json`；SDK min==max） |
| driverPath | `plugins/harness/src/ordessa_harness/copilot/native_channel.py` |
| clientPath | `products/agent-tools/src/ordessa_agent_tools/native_clients/copilot.py` |
| nativeSessionBinding | 未绑定（029 native session reservation 未交付）；客户端用 `session.create`/`session.resume` 原生 sessionId，不伪造 |
| configOwner | copilot 家族 compile_config（G3 发前拒）；launch 级仅 log_level/session_idle_timeout，model/reasoning_effort/session_id 为 session.create 材料；token 类键一律拒 |
| profileKinds | unknown（未测；model/reasoning_effort 为 session 级） |
| skill 适用性 | 文档化 skills 面（`skills.*` RPC、session.skills.*）；无"禁用"开关记录 → unknown，未实现 |
| prompt 适用性 | declared yes（session.send）；L2 未测 |
| model 适用性 | declared yes（session.create model）；热切换 RPC `session.model.switchTo` 存在但本家族 compile 拒绝 `hotModelSwitch` 键——声明的启动级配置与运行态切换分离 |
| MCP 适用性 | 架构存在（session.mcp.*，GitHub MCP 默认内置）；`mcpServers` 为第二 owner → compile 拒绝（不吞） |
| internalSandbox 适用性 | unsupported（无文档；compile 拒绝 `sandbox` 键） |
| approvalCallback | declared yes（permission.requested + pending permission 面）；implemented yes(client, caller-decides, 无默认)；observed no |
| resume | declared yes（session.resume；恢复配置重述/BYOK 需重供、`-32075` 恢复失败）；implemented yes(client)；observed no |
| cancel | declared yes（session.abort → {success,error}）；implemented yes(client)；observed no |
| extensions | unknown 事件/方法/字段原样保留（implemented yes）；observed no |
| transportFence | no（未交付，登记） |
| requestReconciliation | declared yes（同 id 应答 + 乱序回执按 id 归位）；implemented yes(client)；observed no |
| installScope | 未安装、未分发；CLI 许可为自定义 GitHub Copilot CLI License（未修改再分发的条件），安装/分发=待授权 |
| L0–L4 证据 | L0✓（本表 26 行逐条 URL + 风险专节）；L1✓（44 用例：驱动 22 + 客户端 22，全部 fake/L1 标注）；L2 **未测**（无 CLI）；L3/L4 未测（模型预算 0） |
| 限制 | SDK 自动下载/托管进程/账号环境风险（已文档化反制，L2 未验）；`COPILOT_TOKEN`/device flow/`--server` 别名 unknown；协议 v3 仅静态钉定；CLI 许可限制再分发 |
| 下一步 | 授权后安装 v1.0.91（或 SDK v1.0.16 快照 1.0.90）→ 隔离 COPILOT_HOME、无 token 环境做 L2：启动/connect 回报 v3/无认证 session.create 失败码/`--no-auto-login` 行为/退出与信号清理，重钉 artifact sha256；再评估权限回执与 session.idle 真机语义 |

## 未测清单（一律 unknown，不得当通过）

- **L2 全部未测**：真实 `copilot --headless --stdio` 进程启动、`connect` 握手回报、`session.create/resume`、`session.send` 回执与 `session.idle`、`session.abort`、退出码与信号清理（本机无 CLI；安装/更新未授权）。
- 真实 CLI 对带 `jsonrpc` 头帧的接受度；`--server` 是否为 `--headless` 别名；`--stdio` 与 `--headless` 组合的真实行为。
- 权限请求的真实帧形状/同 id 应答 vs `session.permissions.handlePendingPermissionRequest` 的确切封装（本实现两端点都保留：同 id reply 由本客户端提供；RPC 名登记为已知方法）。
- 认证相关的所有运行时行为（`COPILOT_GITHUB_TOKEN`/`GH_TOKEN`/`GITHUB_TOKEN`、存储 OAuth、BYOK、keychain）；本切片不注入、不测试、不读取。
- 协议版本不匹配时真实 CLI 的错误形状；`-32075` 恢复失败码未做。
- `session.send wait=true` 的真实返回时机（文档称仍只有 messageId；门在 L1 未验）。
- 模型调用（L4）预算 0；MCP/skills/plugins/LSP/Telemetry 的真实网络与隔离效果未测。
- 管理绑定（029 AT-009/010/011）依赖阻塞；不发布 runtimeReady；本单终态 **CODE_READY + L1（L2 未测）**。

## 诚实登记

- "回执≠完成"按一手源码裁决：`SendRequest.wait` 默认 false，`SendResult` 仅 `messageId`；完成证据只认 `session.idle`。测试不把 send 回执写成 completed，也不把 fixture 当上游兼容证据。
- SDK 自动下载/自动登录/进程托管是**官方文档明载**行为；本切片的隔离/拒绝措施是代码级反制，**不是**已验证的运行时保证。
- 上游迭代快且 CLI 采用自定义许可（非 MIT；SDK 才是 MIT），任何再分发/捆绑须单独评估许可条件。
- 本证据不含 runtimeReady；矩阵所有 observed 保持 no/unknown，未测项均有明确标注。
