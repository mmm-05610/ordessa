# T04/T05 只读研究报告（先于 T00 接缝并行）

日期：2026-09-28。执行线：Q4 `codex/011-q4-mcp`。范围：只读探针 + 唯一落盘文件（本报告）。
方法：结论尽量打在**实际固定的工件**上（二进制 sha、锁文件 integrity、vendored tarball 的 dist、
现场命令输出）；引用文档只作线索，凡未现场重跑的既有测试一律标注"未重跑"。

本树起点：HEAD `f382aceecf`（Q4 T01+T02），研究期间树内既有文件零改动、零 git 写操作；
构建/解包实验全部在 `/tmp/q4-bridge-probe/`。

---

## 1. 固定版本盘点

### 1.1 Go ACP bridge（Round H）

| 项 | 值 | 取证方式 |
| --- | --- | --- |
| 固定工件 | `/home/maoqh/ordessa-builds/acp-adapter/acp-adapter-round-h`（7,477,986 B，ELF 静态） | 本次 `file`/`ls -la` |
| 工件 sha256 | `5fd6a37b127274eef5c2f27fe731a720e32e9bd64efd6df23e61fe739bbc61ea` = `docs/baseline.md:17` 与 `plugins/harness/adapters/acp-adapter/docs/BUILD-RECORD-ROUND-H.md:11` 的记录 | 本次 `sha256sum` 实测 |
| 重建命令 | `plugins/harness/packaging/acp-adapter/build-acp-adapter-round-h.sh [out]`：`CGO_ENABLED=0 GOPROXY=off GOTOOLCHAIN=local GOROOT=/home/maoqh/ordessa-builds/go1.24.13 go build -trimpath -buildvcs=false -ldflags "-buildid=" -o <out> ./cmd/acp`；零第三方 require（go.sum 空） | 脚本内容 + BUILD-RECORD |
| 工具链 | go1.24.13 linux-amd64（`/home/maoqh/ordessa-builds/go1.24.13`，tarball sha 记录于 packaging 脚本头） | 文件存在性 |

**漂移发现（本次实测，未在任何登记处出现）**：用上述命令从当前 HEAD 的
`plugins/harness/adapters/acp-adapter` 现场重编两次，产物均为
`714044a5b490a53d5fa89aade993c496e5fa3a5f7c614b4465c4990575185cbd`（两次 `cmp` 一致，确定性成立），
**不等于**基线钉 `5fd6a37b…`。原因一手可见：固定工件的 `--help` 播报
`--adapter codex|claude|pi`（现场运行 `acp-adapter-round-h --help`），而当前源码只有
`codex|pi`（`cmd/acp/main.go:30,68`）；Go claude 模式在 `e30f5ff6df`
（2026-09-27 "Retire duplicate Go Claude adapter…"）被删除，晚于 2026-09-25/26 的复现验证
（`docs/migration/backend-build-test.md:154-160`、`docs/migration/README.md:68`）。
即：`docs/baseline.md:17` 的"reproduces … byte-for-byte"对当前 HEAD 已不成立；
`docs/known-issues.md` 未登记此漂移（grep `5fd6a37b` 无登记命中）。
影响：Round-H 证据（含 11/11 门）对应的二进制与树内源码不再同源；T04 若消费 Go bridge，
必须先裁定「钉 5fd6a37b 外部工件（含 claude 模式）」还是「以 HEAD 重编 714044a5 并重跑门」。

### 1.2 三品牌 CLI/adapter pin（本树声明面 + vendored 工件）

| 品牌 | native CLI pin | ACP adapter pin | 供应链钉 | 本机现状 |
| --- | --- | --- | --- | --- |
| Codex | `@openai/codex` **0.147.0**（平台包 `@openai/codex-linux-x64` `0.147.0-linux-x64`，musl 入口 `bin/codex`）：`plugins/harness/packaging/builders/build-codex-runtime-artifact.mjs:80-85`；`codex/production.py:88 CODEX_CLI_VERSION="0.147.0"` | `@agentclientprotocol/codex-acp` **1.1.14**（`codex/production.py:85-86`；launch = `/usr/bin/node <artifact>/node_modules/@agentclientprotocol/codex-acp/dist/index.js`，`production.py:83,334-336`） | vendored tar `plugins/harness/packaging/codex/vendor/agentclientprotocol-codex-acp-1.1.14.tgz`，本次 sha256=`674e4e939ee373e42bf7b1eece51c42cb7a8dd5b564523eea1b1fa8bbdfbce03`；整包闭包 sha512 integrity 见 `packaging/codex/artifacts/SBOM.json`（source_lock=本目录 package-lock.json） | PATH 无 `codex` |
| Claude Code | 生产运行的是 SDK 内嵌二进制：`@anthropic-ai/claude-agent-sdk` **0.3.280** + `@anthropic-ai/claude-agent-sdk-linux-x64` 0.3.280（`packaging/claude/package-lock.json` 现场读 integrity `sha512-vpPyxYLy…`；builder `build-claude-runtime-artifact.mjs:55-57` 把 `…/claude-agent-sdk-linux-x64/claude` 列为唯一 executable）。另有 **PATH 版 CLI 2.1.274** 的 086 实测 pin（`harnesses.toml:111-113`、测试注释 168 行）——两者是不同工件，见 §3.2 | `@agentclientprotocol/claude-agent-acp` **0.81.2**（`claude/production.py:66-67`；builder:49） | runtime artifact digest `sha256:03324c056754cf7e7a0d117a5abdab02705ef38993d82847b9bb30b2f5d542c5` 记录于 `packaging/claude/PROVIDER-SESSION-PROBE.md`（仓外构建；本次在 `/home/maoqh` depth≤4 未找到该工件文件，路径未登记） | PATH 无 `claude`（`which claude` 空）→ 086 类测试在本环境必走 skipif |
| Pi | 两条链两个 pin：**(a) 生产 npm 链** `@automatalabs/pi-acp` **0.5.0** + `@earendil-works/pi-coding-agent|pi-ai|pi-agent-core` **0.84.2**（`build-pi-runtime-artifact.mjs:69-77`；`pi/production.py:73-77`）；**(b) Go bridge/PATH 链** pi CLI **0.86.1**，`/home/maoqh/.pi/agent/install/releases/0.86.1/…/dist/bundle/cli.js` sha256=`e79626f2dd6f94aa45d30f3fa63cd84319a6eefcd150b353cfaf274366926774` —— 本次 `sha256sum` 与 `packaging/acp-adapter/evidence/handshake-migrated-20260925.json` 及 BUILD-RECORD.md:18 记录**逐字节相符** | 生产链即 pi-acp 0.5.0 本身（`pi/production.py:254-256` node 入口）；Go bridge `--adapter pi` spawn `pi --mode rpc … --extension <gate>`（`internal/pi/client.go:992-1012`） | vendored tar `packaging/pi/vendor/automatalabs-pi-acp-0.5.0.tgz`，本次 sha256=`6252f286efcf9e920cbb70e5a4d7d18c15b1eccf68186130410f5e338b6b4c5e`；闭包含 `@modelcontextprotocol/sdk` **1.29.0** MIT、integrity `sha512-zo3926f2…`（见 §5）（`packaging/pi/artifacts/SBOM.json` 现场读取） | `which pi` = `/home/maoqh/.local/bin/pi`，`pi --version` = **0.86.1**（与 0.84.2 生产 pin 不一致，属版本歧义，需 T00 裁定） |

注 1：BUILD-RECORD.md:18 声称 0.86.1 cli.js "matches the HD-002 pin in
`scripts/hd002/native_product_two_turn_gate.py:16`"，但**该脚本在本树不存在**
（`ls scripts/hd002/` 失败）；pin 记录只剩 BUILD-RECORD 与 evidence JSON 两处。
注 2：`harnesses.toml` 头部注释引用的 `docs/server-round1/fullstack/*.md` 在本树不存在
（`docs/` 下无 `server-round1`），是失效引用。

---

## 2. native lane 可行性（asset_files → sidecar launcher → runtime home）

### 2.1 投递链（读到的实际代码路径）

- 装配点在 server-compat：`plugins/server-compat/src/ordessa_server_compat/composition.py`
  （下称 SC-composition）。每 Turn 调 `port_factory`（:936）时构 `asset_files`
  （:995-1166）：对 Profile 的每条 enabled `mcp` binding → digest 校验（:1022-1028）→
  **任何 stdio env 凭据引用即 `MCP_CREDENTIAL_INJECTION_UNVERIFIED` 拒绝**（:1029-1036）→
  `render_for_family`（`SC/assets/rendering.py:100-126`，仅 stdio；HTTP 一律
  `MCP_TRANSPORT_UNSUPPORTED` :63-66；target/key 只读自注册表）→ 必须落在
  `/runtime/home/` 前缀内（:1042-1046）→ JSON 目标按 `mcp_key` merge、TOML 目标按表拼段
  （:1146-1166），与只读投影撞名则 `ASSET_SLOT_CONFLICT`（:1147-1151, 1159-1163）。
  Order 65 的 subagent bridge 条目合成同段（:1078-1140）。
- 交 launcher：`WorkerSidecarLauncher(... asset_files=asset_files)`（SC-composition:1225，
  WSL/SSH）或 `LocalSidecarLauncher(... asset_files=asset_files)`（:1255，本机）。
- 落盘：`LocalSidecarLauncher.launch` → `write_subscription_files(self.home.role_dir,
  self.asset_files, …)`（`execution/local_channel.py:460-465`；O_TRUNC、0600、O_NOFOLLOW，
  :90-122）；Worker 侧同构 `materialize_subscription(...)`
  （`execution/sidecar.py:493-498`）。键 = guest 路径去掉 `/runtime/home/` 前缀，
  即 role 相对路径（local_channel.py:75-87 注释）。

### 2.2 `/runtime/home/` 语义：**每 Profile 实例，跨会话持久**

- `local_home_root = <data_root>/profiles`（SC-composition:907）；
  `LocalHome` 自述 "One **Profile**'s durable home directory on this machine"
  （local_channel.py:198-199）。locator 规则 `_profile_home_locator` =
  `<profile 角色名规范化>-<profile_id 前 8 位>/<native_home>`（SC-composition:212-237）；
  角色目录内有 `.agentbox-profile.json` 标记，profileId/harnessType/nativeHome 任一不符即
  `HOME_MARKER_CONFLICT`——"two Profiles never share one home"（local_channel.py:218-248）。
- home 生命周期：`prepare()` 只 mkdir + 标记校验（:225-262），**没有任何代码删除 home
  或删除 asset 文件**；`home_locator` 记录在 `server_sessions.home_locator`
  （`sessions/repository.py:821,879,1051`），换 Profile 时置 NULL（:411）再由首个 Turn 重新派生。
- 结论：**Codex/Claude 的 mcp_target 投影天然就是"每 Profile 实例"级隔离**（不同 Profile
  必不同目录，有标记强证）；**同一 Profile 的两个会话共享同一 home 与同一份 MCP 文件**。
  共享 Profile 两会话的边界现状：
  1. `homeConcurrency`：claude 生产模板声明 `"exclusive"`
     （`ordessa_harness/claude/production.py:217`），admission 层对同 Profile 第二个活动
     Turn 直接 409 `TURN_CONCURRENCY_CONFLICT`（repository.py:79-98）；**codex 模板没有
     该键**（`codex/production.py` grep 零命中）→ 按 SC-composition:843 默认 `"shared"`，
     codex 无并发闸门（当前因 §3.1 的槽位冲突实际跑不起来，属学术状态）。
  2. 每 Turn 重写整份内容（O_TRUNC 快照），但**只覆盖声明的名字、从不撤销**：binding 停用后
     下一次无内容可写的 Turn 不会清除旧文件 → 陈旧 MCP 条目可继续被 CLI 读到。
     这正是 V04「两会话不串 / 只有文件落盘不得报 loaded」要反例化的洞。
  3. 会话级差异（session scope 分配）在同一 Profile 内表现为后启动 Turn 覆盖先启动的
     共享文件；运行中的兄弟 Turn 已把旧内容交给 CLI，无从回收。

### 2.3 与只读投影/凭据边界的关系（升格门槛）

- claude 已于 086 把 slot 移到投影之外：`mcp_target=/runtime/home/.claude/.claude.json`，
  且投影文件集合（`production.projection_files()`）不含它 —— 有守卫测试
  `test_harness_mcp_config_source_086.py:227-245`。
- codex 槽位仍与投影正面相撞（见 §3.1）。
- 设计裁定（`docs/design/mcp/harness-adapters.md:15`）要求 C2 只编译 intent、Harness C3
  做合并/冲突/代际发布，"MCP adapter 不能自行写 HOME"；当前 SC-composition 段就是被替换
  对象（`specs/011-q4-mcp/t00-interface-bindings.md:26`），且其渲染路径允许明文
  `resolved_env` 入档（rendering.py:51-62），不满足新 secret 边界。

---

## 3. Codex/Claude 原生 MCP 行为面（逐符号）

### 3.1 vendored Codex app-server 协议里的 MCP 观察面

`plugins/harness/adapters/acp-adapter/internal/codex/schema/v2/`（全部现场读 JSON）：

| 符号 | 内容 | 桥内实现状态 |
| --- | --- | --- |
| `ListMcpServerStatusParams/Response` | 分页 `cursor/limit` → `data: McpServerStatus[]`；`McpServerStatus` required = `authStatus,name,resourceTemplates,resources,tools`（tools 为 name→Tool 映射）= **运行时实际加载目录**的一手观察形状 | **仅 vendored schema，Go 代码零引用**（grep `listMcpServerStatus` 无命中） |
| `McpServerRefreshResponse` | 空对象（= 刷新完成信号） | 同上，零引用 |
| `McpServerOauthLoginParams/Response` + `McpServerOauthLoginCompletedNotification` | `name,scopes?,timeoutSecs?` → `authorizationUrl`；完成通知 `name,success,error?` | 桥走的是另一组旧方法名（下行） |
| `McpToolCallProgressNotification` | `itemId,message,threadId,turnId` | 零引用 |
| `../McpServerElicitationRequest*` + `codex_app_server_protocol.schemas.json` | `"mcpServer/elicitation/request"`、`"mcpServer/oauth/login"`、`"mcpServer/oauthLogin/completed"`、`McpAuthStatus`、Elicitation 全套 schema | — |

桥**实际接线**的 MCP 面（Go，Codex 后端专属）：

- app-server 方法常量 `mcpServer/list|call|oauth/login`（`internal/codex/types.go:794-796`）；
  客户端封装 `Client.MCPServersList/MCPToolCall/MCPOAuthLogin`（client.go:472-497）、
  Supervisor 同名重试封装（supervisor.go:197-232）。
- 暴露面 = ACP prompt 内斜杠命令 `/mcp list|call <server> <tool> [args]|oauth <server>`
  （parse：server.go:4135-4167；处理：4292-4410+），观察结果以**文本 delta** 形式塞进
  `session/update`（`"mcp servers: name(oauth=.. tools=..)"` :4307），非结构化 DTO；
  `/mcp call` 前有真实 `session/request_permission` 闸门（:4364-4392，deny-by-default）。
- 命令广告按后端分流：`CodexAvailableCommands` 含 `/mcp`（server.go:339-347，
  `pkg/codexacp/runtime_runner.go:85`）；`PiAvailableCommands` 不含（server.go:350-352，
  `pkg/piacp/runtime_runner.go:84`）。
- 可用于 verify 的观察符号（升格清单见 §7）：`mcpServer/list`（含工具目录 → catalog digest
  可算）、`mcpServer/status`（v2 schema 已有但未桥）、OAuth 登录状态通知、turn 内
  `mcptoolcall` item（client.go:1313-1320）。

**Codex 原生 lane 的现状硬伤（一手测试登记 + 本读代码复核）**：
`harnesses.toml:36` 的 codex `mcp_target` 正是生产模板只读投影的
`/runtime/home/.codex/config.toml`（`codex/production.py:93` CONFIG_TARGET ∈
`projection_files()` :260-266）→ 任何 codex MCP binding 在 SC-composition:1159-1163
必抛 `ASSET_SLOT_CONFLICT`。这不是推测：`apps/server/tests/test_subagent_harness_round_086.py:218-236`
`test_codex_still_collides_and_is_excluded_from_this_round` 把该事实钉为断言
（本次未重跑；测试为纯静态断言，不依赖 CLI）。设计文档同时规定 C2 目标**本就不应**是
全局 `$CODEX_HOME/config.toml`（`docs/design/mcp/harness-adapters.md:8`）。

**另一条更优的路（本次一手发现）**：生产 codex 适配器是 npm `@agentclientprotocol/codex-acp`
1.1.14（§1.2）。对 vendored tarball dist 现场 grep：其 `createSessionConfig` 把
**ACP `session/new`/`resume` 的 `mcpServers` 参数合并进 app-server 会话级 config 覆盖**
`{"mcp_servers": {...}}`（运行时 config 层，优先于 `config.toml`），且有名称净化与
对已有 config 同名服务器的去重跳过逻辑（`requestedServers/filter(!existingNames…)`）。
即 codex 存在**天然的每会话实例级 MCP 注入面**，不需要写 HOME 文件 —— C2 若发布
session 级 mcpServers intent，codex native lane 可直接落。未证部分：1.1.14 与固定
codex CLI 0.147.0 的真实握手行为（需受控探针，见 §9）。

### 3.2 Claude config source 已证事实（086）

`apps/server/tests/test_harness_mcp_config_source_086.py`（既有测试，本环境因无
PATH claude 会 skipif；以下引其**登记为已测量的断言**，原始运行记录为 2.1.274）：

- `settings.json` 声明 `mcpServers` → **不进**模型请求 `tools` 数组（:169-174 `ADVERTISES`
  False；:193-198 断言）；`$CLAUDE_CONFIG_DIR/.claude.json` → 进，工具名
  `mcp__agentbox-probe__probe_tool_086`（:194）；项目 `.mcp.json` → 进（:174）。
  控制例：两文件皆无 → 无 mcp 工具（:217-224）。
- 读路经与槽位一致性由 :227-245 守卫钉死（含 `mcp_target` 不落入 `projection_files()`）。
- **`--strict-mcp-config` 在全仓代码/测试中零命中**（grep 仅 `docs/design/mcp/harness-adapters.md:9`
  一处设计语言），"严格指定配置源"是官方文档主张，本仓无任何一手指针证据。
- 原生 user/project/plugin MCP 的额外发现面（V04"额外原生来源被识别/阻止"）：未探测。
  `.claude.json` 同时是 CLI 用户级状态文件，投影写入会与用户自有 `mcpServers` 共处一文件
  ——`write_subscription_files` 是**整键覆盖**（composition :1050-1053 只 merge 本 Profile
  的内容，不读回旧文件），CLI 侧合并语义未知。
- claude-agent-acp 0.81.2 的消费面：PROVIDER-SESSION-PROBE.md 记录"0.81.2 指纹覆盖
  session-level options.env/options.settings 与 MCP servers"（resume 失效语义），
  且两个 Node 探针在 fake endpoint 下实测 A=1/B=2/C=1 轮次归属——**同一档位的
  mcpServers-per-session 探针本仓还没有**（探针需要该目录 `npm ci`，本次未装，未跑）。

---

## 4. Pi

- 注册表（`harnesses.toml:373-427`）：`slots` 含 `mcp` 但**无 `mcp_target`/`mcp_key`** →
  native 投影结构性不可行（rendering.py:112-116 `ASSET_SLOT_UNSUPPORTED`）；
  测试 `test_subagent_harness_round_086.py:239-253` 把"只有 claude-code/codex/qwen 有
  mcp_target、pi 没有"钉为断言。launch mode 为 `exec`（pty/stdio，
  `pi --agent-dir /runtime/home --print`）。
- Go bridge（`--adapter pi`）：spawn `pi --mode rpc [--session-dir|--provider|--model]
  [--extension <gate>]`（`internal/pi/client.go:992-1012,1008`）；**唯一**的扩展注入实例是
  权限门 extension（`internal/pi/gate_extension.go`：对 `@mariozechner/pi-coding-agent`
  ExtensionAPI 的 `pi.on("tool_call")` 拦截 bash/write/edit，桥回 `session/request_permission`）
  —— 它一手证明了 **Pi 的 `--extension` 进程级工具注册/拦截面真实可用**，但那是
  *每进程*（每 rpc 会话子进程）注入，不是逐会话 MCP 目录；`extension_ui_request` 在桥内
  被显式拒绝转发（client.go:694）。
- bridge/ACP 通路的逐会话工具注册入口：**Go bridge 无**。ACP 线协议类型里没有
  `mcpServers`（`internal/acp/types.go` grep 仅 `mcpCapabilities` 广告位，且握手证据里
  pi 后端播 `"mcpCapabilities": {}`，evidence/handshake-migrated-20260925.json），
  也没有任何 `registerTool` 符号（全桥 grep 零命中）。
- **生产 npm 链不同（一手发现）**：固定 `@automatalabs/pi-acp` 0.5.0 tarball 的 dist 里
  有一个**完整的每会话 MCP client 桥**：`agent.js:434,465,520` 在
  `session/new|resume|load` 读 `params.mcpServers` → `connectMcp(…, sessionId, cwd, …)`
  → `bridgeMcpServers(servers, signal, deps, binding{sessionId,cwd,sessionSignal,…})`
  （`mcp-bridge.js:823`、`mcp-bridge.d.ts`）：内部用官方 `@modelcontextprotocol/sdk`
  的 `Client + Stdio/SSE/StreamableHTTP transports` 建**每会话独立 client**，
  `McpClientHandle.listTools/callTool/close`、工具别名 `allocateAlias`、以
  `InlineExtension` 注入 Pi 会话、terminal/timeout 语义齐备。
  静态证据 = vendored tarball（sha §1.2）；**未执行**（需要 npm ci + pi 0.84.2 闭包）。
  → 对 T05 的含义：G4 探针要问的问题有了具体靶子——Server 侧能否经该 adapter 的
  `session/new.mcpServers` 注入受管 server（以及它算 native 还是 managed：连接 owner
  在 adapter 进程内，租约语义见 `McpSessionBinding.poison/ownerToken`）。
- 仓外 Pi 本体：`/home/maoqh/.local/bin/pi` = 0.86.1；`~/.pi/agent/install/releases/0.86.1`
  为 Go-bridge 链的已证握手 CLI（§1.2）。官方 extensions 文档无本地副本（只有
  harness-adapters.md:7 的 URL 引用）；`third_party/harness_remote`（Apache-2.0,
  v3.0.2@21ce6db4, SOURCE.json 逐文件 sha256）里也没有 registerTool/mcpServers 面。
- 无证据项 → Pi native lane = **unsupported**（结构性：无槽位）；Pi managed lane =
  **unknown-lean-positive**（机制在固定工件 dist 内一手可见，运行证据为零）。

---

## 5. MCP SDK client 供应链

- `apps/server/lockfiles/server-linux-py312.txt`（35 行）与 `server-windows-py312.txt`：
  `grep -ci modelcontextprotocol` = **0**；无任何 mcp 相关 py 包。
- 根 `package-lock.json`：`modelcontextprotocol` = 0 命中；`@agentclientprotocol/sdk`
  1.5.0 是 **ACP** SDK（tests/acp-connector），不是 MCP SDK。
  packaging/{claude,codex,pi} 各 root、`tests/acp-connector`：均无直接 dep。
- **但树内已有一个钉死且有 integrity 的官方 MCP SDK（TS）**：pi 家族闭包
  `@modelcontextprotocol/sdk` **1.29.0**，MIT，
  integrity `sha512-zo37mZA9hJWpULgkRpowewez1y6ML5GsXJPY8FI0tBBCd77HEvza4jDqRKOXgHNn867PVGCyTdzqpz0izu5ZjQ==`，
  resolved `registry.npmmirror.com/@modelcontextprotocol/sdk/-/sdk-1.29.0.tgz`
  （`plugins/harness/packaging/pi/artifacts/SBOM.json` 现场读取；pi-acp 0.5.0
  package.json 精确依赖 `"@modelcontextprotocol/sdk": "1.29.0"`）。
  它随 runtime artifact 构建流程安装，不需要动根锁。
- 结论与请求草案见 §8。

---

## 6. 官方协议基线（probe/managed 协商集合）

仓内一手（fixture/fake，全部现场读）：

- `SC/assets/mcp_probe.py:33-40`：客户端固定发
  `{jsonrpc,id:1,method:"initialize",params:{protocolVersion:"2024-11-05",capabilities:{},clientInfo:{name,version}}}`，
  一次性读回单行、5s 上限、killpg 收尾（t00 绑定表 :23 同记）。
- `apps/server/tests/fixtures/fake_mcp_server.py:31`：应答固定
  `"protocolVersion":"2024-11-05"`；`mcp-config-probe-server.mjs:21` 与
  `plugins/harness/runtime/subagent-bridge.mjs:56-64` 均**回显**客户端版本。
- 注意（如实）：`2024-11-05` 这个字符串**不在本代理可确认的 MCP 官方版本史里**
  （官方发表史按规范知识为 `2024-10-07`/`2025-03-26`/`2025-06-18`/`2025-11-25`）。
  它只是仓内 fixture 自洽的握手版本——回显式 fake 让任何客户端都"绿"，
  这正是 V03「不把 initialize 当 catalog」要防的假阳性面。T03 新 probe 不能沿用。
- `docs/design/mcp/research-and-reuse.md:9` 已把"旧 probe 固定 2024-11-05，实现须按
  协商版本区分"列为裁定；本任务书把 2025-11-25 作为基线 —— 2025-11-25 的报文形状
  （initialize 增 `clientInfo.title/icon`、elicitation capability、tools 增 `title`、
  Streamable HTTP Origin 校验等）来自**规范知识**，本树内没有 2025-11-25 的任何 fixture
  或 SDK dist 佐证（SDK 未安装；未联网核对）。
- 建议协商集（供 probe/managed 实现，探针落证后回填）：
  probe 应携带支持列表 `[2025-11-25, 2025-06-18, 2025-03-26, 2024-10-07]` 并按**服务器
  回值**记录实际版本（回显 fake 与真值区分开）；managed 首版以固定 SDK
  （TS 1.29.0，若走 pi-acp/TS 路线）声明的 `LATEST/SUPPORTED_PROTOCOL_VERSIONS` 为准 ——
  该常量的实际内容本次**未能读到**（dist 未装），列为探针项。Python `mcp` SDK 若引入，
  同样以其 tag 的常量为准。

---

## 7. 三品牌 × lane 矩阵

| 品牌 | native lane | managed lane |
| --- | --- | --- |
| **Codex** | **observed-negative + unknown-positive**。observed：投影路线被 `ASSET_SLOT_CONFLICT` 结构封死（086 测试钉 + 代码复核 §3.1）；`mcpServer/list|call|oauth/login` 桥实现存在（Go，仅经 `/mcp` 斜杠文本面，且该 Go 二进制与 HEAD 已漂移 §1.1）；codex-acp 1.1.14 dist 一手显示 `session/new.mcpServers` → 会话级 `mcp_servers` config 覆盖（未执行）。升格需要：C2 session 级 mcpServers intent + 对 1.1.14+0.147.0 受控握手/目录观察探针 + HOME 文件"额外原生来源"探测（`$CODEX_HOME/config.toml` 里用户自有 `mcp_servers` 与注入集冲突的识别，§3.1 dedupe 逻辑提示原生同名会赢）。 | **unsupported（本线无入口）**：codex 原生 client 由 app-server 拥有，设计禁止双开（harness-adapters.md:17,27）；若 native 判定不可行，改 managed 需要"明确评审"（同文 :8），当前无任何 codex managed 代码证据。 |
| **Claude Code** | **unknown（机制在、观察面缺）**。observed：读路经 2.1.274 已钉（`.claude.json` 进、settings.json 不进，§3.2；本环境未重跑）；投影可写、槽位不撞。缺口：无运行装载/权限/重启恢复实证；`--strict-mcp-config` 零证据；0.81.2 adapter 的 per-session mcpServers 消费只有文档陈述（PROVIDER-SESSION-PROBE.md；其 node 探针未覆盖 mcp 场景）；原生 user/project/plugin 额外来源与身份恢复未探测。升格需要：npm ci 后扩展 provider-session 探针加 mcpServers 指纹 case + CLI 版 `claude`（钉 SDK 内嵌 0.3.280 的 CLI 与 PATH 2.1.274 的关系先裁定）。 | **unknown**：managed 首版 owner 在 MCP 域进程；claude 与 managed 的互斥（同 definitionId 单 lane）机制本身无代码（`laneByDefinition` 仅设计文）。 |
| **Pi** | **unsupported（结构）**：无 `mcp_target` → 渲染即 `ASSET_SLOT_UNSUPPORTED`（086 测试 :239-253 钉）；设计文 :7 也禁止推断统一内建 MCP 配置。`--extension` 注入面 observed（gate extension），但那是权限拦截，不是 MCP 目录；用它承载 MCP 需要全新受信 extension 工件（版本/许可/信任审批，harness-adapters.md:23）→ 列 G4。 | **unknown-lean-positive**：pi-acp 0.5.0 dist 内每会话 `mcpServers→MCP client bridge→InlineExtension 工具` 链一手可读（§4）；本树生产链就是该 adapter（pi/production.py）。升格需要：受控探针（固定 tarball + 0.84.2 闭包 + fake MCP server，initialize→tools/list→tools/call→close 逐会话证据、双 Pi 会话不串、关闭无泄漏），并裁定连接 owner（adapter 内 bridge vs MCP 域 manager——设计 :21 要求"一 owner"，二者只能居其一）。 |

矩阵通用缺格：三品牌"受控重启恢复同一 native session"均无任何证据；
"输出中变更只在下一次提交生效"在现 asset 路径（每 Turn 快照重写）下机制符合、但从未按
MCP 语义验证；`verify` 的结构化 DTO 观察面三品牌全部为零（现有观察要么是文本 delta，
要么只有文件落盘）。

---

## 8. C2/harness-api 需要发布的精确符号清单（供 G2/G4 收紧）

按 Q4 调用者操作列；每条给"期望 DTO 形状"与"反例（必须拒绝）"。

**G2（native lane，Codex/Claude）**

1. `compile(McpEffectiveSnapshot, family) -> ConfigIntent`。
   - 期望：一次性完整集合（非逐 server 追加）；只读 `mcp_target/mcp_key` 拼写来自
     `ordessa_harness.registry.load_builtin_registry().get(t).profile`（registry 已是公开符号，
     SC-composition:110 消费方式即调用者样例）。
   - 反例：intent 含凭据明文（今天 renderer `resolved_env` 路径的既有形状必须被新类型拒收）；
     intent 目标 ∈ `production.projection_files()`（ASSET_SLOT_CONFLICT 应成类型化结果而非 RuntimeError）。
2. `apply(generation) -> InstanceConfigHandle`：**实例/会话级**代际句柄，取代"写 role 文件"。
   首选载体 = ACP `session/new.mcpServers`（codex-acp 1.1.14 dist 一手证明有消费路径；
   claude-agent-acp 0.81.2 待探针）。
   - 反例：只有文件落盘不得报 loaded（V04 原语）；同 Profile 两会话不同快照 → 各自
     handle 的内容互不可见（现 home 共享 + O_TRUNC 覆盖做不到，§2.2）。
3. `verify(handle) -> NativeObservation`。字段至少：实例 identity、server name、
   transport、**实际加载状态**、观察 tool catalog（可算 digest）。
   可映射的原生符号（本研究发现，供 harness-api 侧实现选路）：
   Codex `mcpServer/list`（`MCPServer{name,oauthRequired,tools[]}`）、v2
   `listMcpServerStatus`（`McpServerStatus{authStatus,name,tools,resources,resourceTemplates}`，
   桥未接，需 app-server 侧核实）、`mcpServer/refresh`；
   Claude：`tools` 数组中 `mcp__<server>__<tool>` 名册（086 探针同款观察面）与
   adapter 指纹（0.81.2）。
   - 反例：catalog 空 ≠ loaded；观察调用失败必须回 unknown 而非 projected。
4. `remove(generation) + reconcile`：撤销必须能**证明清除**（现在没有任何 stale 撤销路径，
   §2.2-2）；native owner 死 → 报 unknown，禁猜 PID kill（设计 :17）。
5. 原生来源冲突登记：读取既有 `mcpServers`/`mcp_servers`（用户自有键）并只读展示/拒绝冲突
   （设计 :17；codex-acp 的 existingNames-dedupe 表明原生同名会静默赢——Q4 不能依赖该静默）。

**G4（Pi managed 桥）**

6. `registerManagedToolBridge(sessionRef, serverName, toolDescriptors) / unregister`：
   Server 校验的登记入口，扩展不持 secretRef、不直连（设计 :23）。
   - 现状锚点：`--extension` 进程注入（gate_extension.go 机制）；pi-acp 0.5.0 的
     `session/new.mcpServers` 若被采用为受控通道，登记语义就变成"每会话 mcpServers 注入 +
     adapter 内 bridge 的 close 归属"——需要 harness-api 明确 owner 后发布。
7. `lease/owner 唯一性符号`：`McpSessionBinding{sessionId,sessionSignal,poison,ownerToken}`
   （pi-acp dist）显示 adapter 内部已有 owner/poison 词汇；C2/G4 发布面若复用它，
   必须给公开类型，否则 Q4 只能把 managed client 收回本域并用 TS SDK 经 sidecar 跑。
8. 反例（G4 探针必测）：扩展绕过授权调真 server → 拒；单会话 close 后另一会话不受影响；
   同一 server 被 native+managed 双开 → 第二者申请即 `OWNER_CONFLICT`。

**SDK 引入请求草案（integration-request.md）**

- 方案 A（TS 复用，零新依赖，推荐先探针）：以已钉 `@modelcontextprotocol/sdk` 1.29.0
  （MIT，integrity 见 §5）作为 managed client 实现基，经 sidecar 内 JS 运行（复用
  `build-pi-runtime-artifact.mjs` 的闭包与 SBOM 机制）。无需动根锁/server 锁。
  代价：Python 域需跨进程调用（新增本地协议面）。
- 方案 B（Python 直用）：引入 PyPI `mcp`（modelcontextprotocol/python-sdk）固定 tag；
  本树零 Python MCP 依赖史 → 需新增 lockfile 行与 `-e` 安装序变更；版本/依赖增量清单在
  裁定后以 `pip install --dry-run` 于钉版本产 SBOM 再报（本次**未**下载，未列假清单）。
  许可证：MIT（SDK 官方仓库声明）。请求内容：批准 A 或 B 之一，并把钉版本 + 闭包
  integrity 提交进 `apps/server/lockfiles` 或对应家族 SBOM。

---

## 9. 明确没证到的（不许把文档当运行证据）

1. **任何一次真实 Codex/Claude/Pi CLI 的 MCP 运行观察**：本机 PATH 无 codex/claude；
   086 测试、PROVIDER-SESSION-PROBE 的两个 node 门、Round H 11/11 门**本会话均未重跑**
   （引用其登记的断言，并区分"文件存在性证据"与"运行证据"）。
2. claude CLI 2.1.274 与生产内嵌 claude-agent-sdk 0.3.280 CLI 的**同一性**：未证；
   两者是不同分发物，086 pin 只覆盖前者。
3. `--strict-mcp-config` 行为、claude 原生 user/project/plugin 额外 MCP 来源识别：零证据。
4. claude-agent-acp 0.81.2 对 `session/new.mcpServers` 的实际消费：只有指纹文档；
   tarball dist 本次未解包核对（无 node_modules、避免 npm ci）。
5. codex-acp 1.1.14 的会话级 `mcp_servers` 覆盖在**真 app-server 0.147.0** 上的效果
   与 `getConfigMcpServerNames` 读取的确切来源：dist 静态可读、运行未证。
6. `listMcpServerStatus` / `mcpServer/refresh` 在固定 codex CLI 上是否应答：桥零接线，
   app-server 行为未探。
7. pi-acp 0.5.0 MCP bridge 的端到端行为（连接、别名、close 无泄漏、双会话不串）：
   全部为 tarball dist 静态证据；未运行；且它与 0.84.2 vs 0.86.1 CLI 版本歧义纠缠。
8. MCP 2025-11-25 报文的规范级核对：未访问官方规范文本；`2024-11-05` fixture 版本
   字符串与官方版本史的不一致仅如实登记，未裁决。
9. claude runtime artifact（digest 03324c05…）与 pi/codex runtime artifacts 的**盘上实体**：
   在 `/home/maoqh` depth≤4 未找到，路径未登记于树内 → 其存在性目前只能算文档声明。
10. 桥二进制漂移（§1.1）的成因裁定（钉工件 vs 重钉源码）：属 T00/主代理权限，本调查
    只报告事实；`docs/known-issues.md` 尚未登记该漂移。
11. `SUPPORTED_PROTOCOL_VERSIONS` 在 SDK 1.29.0 dist 中的实际值：未安装、未读。

## 主代理裁定（2026-09-28，审阅追加）

- **R-Q4-1 协议版本史更正**：`2024-11-05` **是** MCP 官方首版规范日期（transports/tools 即按该版发布；本仓 legacy probe 固定此值并非伪造）。§6 中"不在官方版本史里"一句作废；"回显式 fake 造成假阳性"的告诫保留且有效。T03 已实现的协商集 `("2025-11-25","2024-11-05")` 判定为可接受基线（2024-11-05 维持 legacy 互操作）；后续如需 2025-06-18/2025-03-26 由 T05 managed SDK 常量落证后扩展，不在 probe 盲扩。
- **R-Q4-2 桥工件漂移**：HEAD `e30f5ff6df` 重编为 `714044a5…` ≠ `docs/baseline.md` 钉 `5fd6a37b…`——该文档/钉属 C0 所有，且 main 上"Retire duplicate Go Claude adapter"是本批快照的祖先提交，判定为**预期退役漂移**而非新事故；已转 C0 处理（integration-request），Q4 线不擅改 baseline 钉。Q4 一切运行探针以**现场重编工件的实测行为**为准，引用时记录其 sha。
- **R-Q4-3 Codex native 路线**：投影路（写 config.toml）被只读槽冲突结构性封死 + codex-acp 1.1.14 `session/new.mcpServers` 存在静态一手证据 → Q4 把 Codex native 适配目标定为 **C2 session intent**（api-requests G2 收紧），不再尝试文件投影路。
- **R-Q4-4 Pi 双 pin 歧义**（0.84.2 生产闭包 vs 0.86.1 PATH CLI）：属 C0 runtime 装载裁决面，列 integration-request；Q4 探针以生产闭包 0.84.2 为准，两值差异如实记录。
