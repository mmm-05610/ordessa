# T00/V00：ACP 入口受控探针 —— `session/new.mcpServers` 实际消费行为（Q4 R-Q4-3 前提）

日期：2026-09-28。执行面：worktree `011-q4-mcp`，node v22.22.1（`/usr/bin/node`）。
探针脚本：`plugins/assets/mcp/scripts/probe_acp_session_mcp.mjs`（Codex 品牌）、
`plugins/assets/mcp/scripts/probe_acp_session_mcp_claude.mjs`（Claude 品牌）。
**两者是受控一次性探针，不进 pytest 常跑。**

结论边界（先说死）：

- 已证的是 **adapter 行为**（钉版 adapter 工件 + 假后端 witness，L2 级）：
  codex-acp 1.1.14 与 claude-agent-acp 0.81.2 都把 `session/new.mcpServers`
  逐字段注入各自后端的启动载荷，不自行连接 MCP server，空列表不注入，多会话不串。
- **未证**：真实 `@openai/codex` / Claude 原生 CLI 装载并连上被注入的 MCP server。
  本机 PATH 无 `codex`、无 `claude`（本次 `which` 双双 rc=1；主代理先前实测同结论），
  假后端不会外连，所以「后端拿到 config 后是否真连」仍是 unknown（品牌 L3 ≠ adapter L2，
  不得混登）。R-Q4-3 的 Codex native 路线前提在 **adapter 入口面** 已闭合，
  后端装载面仍挂起（见 §6）。

---

## 1. 输入固定与完整性核对（一手）

### 1.1 Codex adapter（树内 vendored tgz）

| 项 | 值 |
| --- | --- |
| 工件 | `plugins/harness/packaging/codex/vendor/agentclientprotocol-codex-acp-1.1.14.tgz`（193,758 B） |
| sha256（本次实测） | `674e4e939ee373e42bf7b1eece51c42cb7a8dd5b564523eea1b1fa8bbdfbce03` |
| lock 声明 integrity | `sha512-6JKLbGYH0/Gcz788U6KnljwSdNvUnXOyjJDOgsWsbwmXbxn/BXH+urF5AciACdgq13+KgAP9O96Kp6h33BgyKg==`（`packaging/codex/package-lock.json` `node_modules/@agentclientprotocol/codex-acp`） |
| 核对命令（本次实测一致） | `sha256sum <tgz>`；`openssl dgst -sha512 -binary <tgz> \| openssl base64 -A` |
| 闭包 pin | `@agentclientprotocol/sdk` 1.3.0 override（lock 内嵌），`@openai/codex` 0.147.0 —— **运行探针只需 node：dist/index.js 为自包含 bundle（esbuild），外部 import 全部是 `node:*`**（`grep -oE 'from "[^"./][^"]*"' dist/index.js` 仅 node: 命中），未装任何 npm 依赖 |
| 展开 | `tar -xzf <tgz> -C <work>/src` → `src/package/dist/index.js`（31,698 行 bundle） |

### 1.2 Claude adapter（树内无 tgz，npm 缓存离线取回）

- 树内 pin：`plugins/harness/packaging/claude/package-lock.json` →
  `@agentclientprotocol/claude-agent-acp` 0.81.2，integrity
  `sha512-/yvpesq8e6Jv8kl5PHEhwbKRVvzVudXD+ujC0q6PZFmrZK0+xPtiVQYtZIdlUtdhgNKBgBTsGwZkbb2Iw+rbjA==`。
  **树内无 vendor tgz**（`packaging/claude/` 无 vendor 目录，find 零命中）。
- 本次从 npm 本地缓存（`~/.npm/_cacache`，只读，无 registry 请求）按 index 条目
  `make-fetch-happen:request-cache:https://registry.npmjs.org/@agentclientprotocol/claude-agent-acp/-/claude-agent-acp-0.81.2.tgz`
  取出 content 分块（`content-v2/sha512/ff/2b/…`，279,181 B），
  `openssl dgst -sha512 -binary | base64` 与 lock integrity **逐字节一致**。
- 该包**非自包含**（tsc 产物），运行需三个运行时依赖，也全部从同一缓存取回（版本恰为 lock 组合）：
  `@agentclientprotocol/sdk-1.5.0.tgz`、`@anthropic-ai/claude-agent-sdk-0.3.280.tgz`、`zod-4.6.5.tgz`
  （三包 `dependencies` 均为空对象，无二级依赖）。依赖闭包在报告 §5 的登记中不算「树内钉版」，
  复现需先预热 npm 缓存或从 lock 同源补齐——本节如实标注该供应链差异。

---

## 2. 后端二进制注入面（一手行号，均指展开后 dist 文件）

Codex（`src/package/dist/index.js`，codex-acp 1.1.14）：

- `startAcpServer()` 读 env：`CODEX_PATH` / `CODEX_CONFIG` / `DEFAULT_AUTH_REQUEST` / `MODEL_PROVIDER`（31644-31648）。
- `startCodexConnection(codexPath, env)`：`CODEX_PATH` 非空 → `spawn(codexPath, ["app-server"], {env})`（22068-22072，stdio newline JSON-RPC，jsonrpc 字段可缺省，reader 回填 `"2.0"`，21958-21994）；
  未设 → 回落 `createRequire(…).resolve("@openai/codex/bin/codex.js")` 的**捆绑 CLI**（22074-22075）——探针里该回落路径不可达（未装依赖），反证 `CODEX_PATH` 是唯一注入面。
- 调试 witness 面：`attachLogs` 把每帧 `[IN]/[OUT]` 写 `APP_SERVER_LOGS` 目录 `app-server.log`（22006-22035, 22080-22085）。
- MCP 消费缝：`session/new → newSession → codexClient.threadStart({config, …})`（26578-26586）；
  `createSessionConfig` 把 `mcpServers[]` 折成 `config["mcp_servers"][<sanitize(name)>]`（26670-26697；name 空白→`_`，26154-26157）；
  `createMcpSeverConfig`：`http → {url, http_headers}`（headers 数组折 dict）；无 `type` → `{command,args,env}`（stdio）；
  **`sse`/`acp` 直接抛 `invalidRequest`**（26735-26754，静态；本次未运行时触发）。
  initialize 应答广告 `mcpCapabilities {acp:false, http:true, sse:false}`（28805-28809）。
- 冲突去重：默认对每个 session/new 先 `config/read` 取已有 `mcp_servers` 名集合并跳过同名注入（26687-26690, 26700）；
  `DISABLE_MCP_CONFIG_FILTERING=true` 关闭（27060-27063）。假后端返回空 config → 注入全量可见。
- **ACP 线形约束（运行时新发现）**：agent 侧参数解析把 `mcpServers` 定为 required-with-error-default
  （bundle 19543-19551 `requiredDefaultOnError(vecSkipError(zMcpServer), () => [])`；http 条目形状 19504-19513：**`headers` 数组是必填字段**）。
  实测：`session/new` **缺 `mcpServers` 字段 → `-32602 Invalid params ("Required value is missing")`**，
  负控必须以 `mcpServers: []` 显式空数组表达（G6 格）。
- `vecSkipError`：不符合 union 的条目**静默丢弃**不报错（D 格实测：缺 headers 的条目被丢，同请求里合法条目照常注入）。

Claude（`dist/acp-agent.js`，claude-agent-acp 0.81.2）：

- 后端二进制注入面 = env `CLAUDE_CODE_EXECUTABLE`（515-517；6416 `pathToClaudeCodeExecutable: process.env.CLAUDE_CODE_EXECUTABLE ?? await claudeCliPath()`；未设则 resolve SDK 平台包 `@anthropic-ai/claude-agent-sdk-linux-x64/claude` 原生二进制）。
- `session/new.mcpServers` → SDK `options.mcpServers` dict：6214-6236（`http`/`sse` → `{type,url,headers:Object.fromEntries(name/value)}`；无 `type` → `{type:"stdio",command,args,env}`），并入 query options 6390-6393。
- SDK（`@anthropic-ai/claude-agent-sdk/sdk.mjs` arg-builder）以 **argv** 交给 CLI：
  `--mcp-config '{"mcpServers":{…}}'`；`--strict-mcp-config` 仅当调用方置位才出现（SDK 有旗、adapter 未置——C5 实测为缺席）。
- initialize 应答广告 `mcpCapabilities {http:true, sse:true}`（无 acp 位）。

## 3. 假后端（协议形态来源，不臆造帧名）

Codex 侧 fake app-server（探针生成、node 单文件）逐帧应答形态取自两处一手：
(a) adapter bundle 内的 sendRequest 方法名表（`initialize`、`thread/start`、`thread/resume`、`model/list`、
`config/read`、`account/read`、`skills/list`、`skills/extraRoots/set`、`mcpServerStatus/list`…）；
(b) Go 桥 vendored schema `plugins/harness/adapters/acp-adapter/internal/codex/schema/codex_app_server_protocol.v2.schemas.json`
（`InitializeResponse`/`ThreadStartParams.config` 为自由对象/`ThreadStartResponse`/`ModelListResponse`+`Model` required 字段/
`ConfigReadResponse{config,origins}`/`GetAccountResponse{requiresOpenaiAuth}`/`SkillsListResponse{data}`）。
每帧（in/out）追加 `witness/appserver.jsonl`，`thread/start` 另存结构化条目。
Claude 侧 fake CLI 应答 SDK 的 `{"type":"control_request","request":{"subtype":"initialize",…}}` →
`control_response.success{commands,models,account,…}`（模型/账号形状按 `dist/session-model.js getAvailableModels`
与 `dist/hide-claude-auth.js` 谓词一手对齐），并 witness argv/stdin 全帧。

loopback fake MCP server：探针自身在 `127.0.0.1:<随机端口>` 起 Streamable-HTTP 假 server
（应答 `initialize`/`tools/list`，通知 202），每请求记 `witness/mcp-servers.jsonl`；
跑前自测（S1）证明其可达，使「0 命中」断言有意义。

## 4. Codex 品牌逐格（run rc=0，2026-09-28）

复现命令：

```
sha256sum plugins/harness/packaging/codex/vendor/agentclientprotocol-codex-acp-1.1.14.tgz   # 674e4e93…ce03, rc=0
timeout 180 node plugins/assets/mcp/scripts/probe_acp_session_mcp.mjs \
  --tgz plugins/harness/packaging/codex/vendor/agentclientprotocol-codex-acp-1.1.14.tgz --keep
# RC=0；work 目录 witness/appserver.jsonl(60 帧)/mcp-servers.jsonl；结束后已删除
```

| 格 | 判定 | 证据（witness 摘录） |
| --- | --- | --- |
| S0 静态可达 | **observed** | `node dist/index.js --version` → `@agentclientprotocol/codex-acp 1.1.14`，exit 0 |
| S1 fake MCP 自测 | **observed** | 直连 `POST /mcp-selftest` initialize 回 `serverInfo=probe-fake-mcp`（探针自己的 1 次命中，非 adapter） |
| S2 ACP initialize | **observed** | 实连应答 `agentInfo{title:"Codex",1.1.14}`、`mcpCapabilities {acp:false,http:true,sse:false}` |
| G6 线形：缺 `mcpServers` 字段 | **observed（拒）** | `-32602 Invalid params data.mcpServers._errors=["Required value is missing"]` |
| G1-A 注入 `probe` http | **observed** | `thread/start` params：`config.mcp_servers={"probe":{"url":"http://127.0.0.1:<port>/mcp","http_headers":{"X-Probe-Key":"probe-secret"}}}`，`config.projects` 同帧；sessionId==`probe-thread-1`==witness threadId |
| G1-B 注入 `probe-b` | **observed** | 第二帧仅 `mcp_servers={"probe-b":{url …/mcpb, http_headers…}}` |
| G1-D 无效条目静默丢弃 | **observed** | 请求含 `{name:"dropped"（缺 headers)}`+`probe-d` → 帧内仅 `probe-d`；无错误回给 client |
| G3 负控 `mcpServers:[]` | **observed-negative** | 第三帧 `config` keys 仅 `["projects"]`，无 `mcp_servers` 键 |
| G2 adapter 自身不连 MCP | **observed-negative** | settle 1500ms 后 fake MCP 计数：仅 `/mcp-selftest`=1，`/mcp|/mcpb|/mcpd`=0 |
| G4 双会话不串 | **observed** | A/B 帧 server 名集不相交 `{probe}`/`{probe-b}`，4 个 thread id 互异 |
| G5 帧序清单 | **observed** | app-server 收到的方法集：`initialize, account/read, skills/list, config/read, thread/start, model/list`（`config/read`=去重路径在用） |

## 5. Claude 品牌同型最小探针（run rc=0，2026-09-28）

```
timeout 180 node plugins/assets/mcp/scripts/probe_acp_session_mcp_claude.mjs \
  --tgz-acp <cache>/claude-agent-acp-0.81.2.tgz --tgz-sdk <cache>/sdk-1.5.0.tgz \
  --tgz-agent-sdk <cache>/claude-agent-sdk-0.3.280.tgz --tgz-zod <cache>/zod-4.6.5.tgz --keep
# RC=0（work 已删；<cache>=临时物化的 npm 缓存导出目录）
```

| 格 | 判定 | 证据 |
| --- | --- | --- |
| S0/S1/S2 | **observed** | `--version`→0.81.2；fake MCP 自测可达；ACP initialize 实连回 `agentInfo{title:"Claude Agent",0.81.2}`、`mcpCapabilities {http:true,sse:true}` |
| C1 后端 spawn 面 | **observed** | 3 session → 3 个 `--input-format stream-json` 子进程（`CLAUDE_CODE_EXECUTABLE` 指入的假 CLI）；另有 1 次 `claude auth status --json` 旁路探测 |
| C2-A 注入 | **observed** | 第 1 个 spawn argv：`--mcp-config {"mcpServers":{"probe":{"type":"http","url":"http://127.0.0.1:<port>/mcp","headers":{"X-Probe-Key":"probe-secret"}}}}` 逐字段核 |
| C3-B 不串 | **observed** | 第 2 个 spawn 仅 `probe-b`；client sessionId 为 adapter 自生成 uuid |
| C4 负控 `[]` | **observed-negative** | 第 3 个 spawn argv **无** `--mcp-config` |
| C5 strict 旗 | **observed-negative** | 三 spawn 均无 `--strict-mcp-config` → CLI 侧用户/项目原生 MCP 发现面未被抑制（V04「额外原生来源」在此品牌仍未闭合，与本仓 086 勘察一致） |
| C6 adapter 不连 MCP | **observed-negative** | fake MCP 仅自测 1 次命中 |
| 备注 | — | `sse` 类型该品牌映射为 `{type:"sse",url,…}` 转发（静态 6216-6221，运行时未触发）；codex 品牌则直接 `invalidRequest` |

## 6. 判定与挂起项（对 R-Q4-3）

1. **session intent 路线（C2 经 `session/new.mcpServers` 注入）在两个 ACP adapter 品牌均实证**：
   注入发生在后端启动载荷层（codex：`thread/start.config.mcp_servers`；claude：CLI argv `--mcp-config`），
   逐字段保真（name/transport/url/headers），空列表负控干净，双会话互斥，adapter 不代连。
   → 相对 t04-t05-research §3.2「仅静态一手证据」，V00 的 adapter 入口面已升为运行时 L2 证据。
2. **仍未证（不得合并计入 V00 闭合）**：
   - 真实 `@openai/codex` 0.147.0 二进制对 `thread/start.config.mcp_servers` 的消费（PATH/install 目录零 `codex`；
     本探针假后端不外连，「后端是否拨号」未观察）。
   - 真实 Claude 原生 CLI 对 `--mcp-config` 的拨号行为（同上；且闭包内原生二进制本次未装载）。
   - codex 品牌 sse/acp 拒绝、去重命中路径（`config/read` 返回既有 `mcp_servers` 时跳过注入）仅静态行号证据。
   - claude 缺 `mcpServers` 字段的线形行为（只测了 `[]`）。
   - 「注入后模型能否见到工具」属品牌 L3，需真 CLI+受控模型授权，另行登记。
3. 装配侧注意事项（一手，影响 C2 契约形状）：ACP client 必须每请求携带 `mcpServers`（缺字段=参数错误）；
   http 条目 `headers` 必须显式给数组（可空）；codex 侧 name 中的空白会被替换 `_`，且默认去重可能吞掉与
   codex 既有 config 层同名的 server（`DISABLE_MCP_CONFIG_FILTERING=true` 关闭）；
   无效条目被 `vecSkipError` 静默丢 → **verify 面必须以后端观察为准，不能以 session/new 成功反推 server 已装载**。

## 7. 卫生与清理

- 全程 `HOME=<work>/home` 假 HOME 运行 adapter；未读写用户 `~`（npm 缓存仅只读分块拷贝）；
  零 registry 访问（一切从 tgz/缓存 content）；loopback 端口由探针自起自关。
- adapter 以 `detached` 进程组启动，收尾 `kill(-pgid)` SIGTERM→SIGKILL，`pgrep` 复核无残留；
  两个 work 目录（`/tmp/q4-acp-probe-*`）与开发期临时目录均已删除。
- 每命令 `timeout`（180s/20s per-RPC/15s 静态）。
