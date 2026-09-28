# R0/T00 — 冻结输入、盘点与接口绑定表

日期：2026-09-28。执行线：Q4（`codex/011-q4-mcp`）。

## 冻结输入

| 项 | 值 |
| --- | --- |
| 本树起点 SHA | `96fef2db47`（父 `cd7d31f3cf` = 共同 plan 固定 main 快照） |
| 工作树 | `/home/maoqh/projects/ordessa/worktrees/011-q4-mcp`，起点 clean |
| Python | 3.12.14（venv `.venv`，`pip install -r apps/server/lockfiles/server-linux-py312.txt` + 本仓 `-e` 包；额外纳入 `packages/server-plugin-api`、`plugins/workspace`、`plugins/server-compat`） |
| 基准红账 | `docs/known-issues.md` + `docs/migration/backend-build-test.md`（pacthold 238P；harness 308P/3S/2F inherited；server 59 inherited same-id + 6 scope-reds） |
| 检查点消费 | 2026-09-28T18:00Z 实测 `git branch -a`：**foundation / harness-api / profile-api / chat-api / permissions-api 均未发布**（仅 9 条 feature 分支 + plugin-plan）。本线先行独立工作，发布后再按固定 SHA 接线。 |
| 品牌固定版本 | Codex/Claude/Pi native 版本与 ACP bridge：bridge 复现构建 `CGO_ENABLED=0 go build …`，sha256 `5fd6a37b…`（`docs/baseline.md`）；Pi/Codex/Claude 目标 CLI 版本 pin 属 T04/T05 受控探针前置，登记于下文缺口 G3/G4，探针落证前相应格保持 unknown。 |

## 旧实现盘点（V01/V09 字节互证来源）

来源全部在 `plugins/server-compat/src/ordessa_server_compat/`（下记 SC）。完整符号级清单见各任务实现报告；关键复用裁定按 `docs/design/mcp/research-and-reuse.md` 执行：

| 模块 | 现状符号 | 裁定 |
| --- | --- | --- |
| `SC/assets/mcp.py` | `canonical_definition`（mcp.py:61）、`definition_digest`（:123，`json.dumps(sort_keys,separators=(",",":"))`，`ensure_ascii` 默认 True，前缀 `sha256:`）、`McpAssetStore`（:128，`<assets_root>/mcp/<asset_id>/<revision>/server.json`，0o644，staging+rename，`MCP_REVISION_EXISTS` 防覆盖）；校验正则 `[a-z0-9][a-z0-9._-]{0,63}`、transport 单键、command 前缀 `/`、url `https://` 或前缀 `http://127.0.0.1`、env/header 值必须恰为 `{"credentialRef": "<id>"}` | **迁移改造**：digest/磁盘布局/错误码字符串保持字节互证；env/header 升级为 `Literal|SecretRef` 判别但旧 `credentialRef` 单键形状必须继续可读可校验（FR-12） |
| `SC/assets/mcp_probe.py` | `probe_stdio`（mcp_probe.py:40，timeout=5.0、max_bytes=64KiB、`start_new_session`、killpg SIGTERM→2s→SIGKILL、固定 `2024-11-05` initialize 报文、无凭据 env 三元组、五型 PROBE_* code） | **限定复用**：保留限时/收尾模式；升级协商版本区分与有/无凭据结果分列（T03） |
| `SC/assets/rendering.py` | `render_json_config`/`render_toml_config`/`render_for_family`（:69/:77/:100）；`resolved_env` 明文入档路径 | **仅借鉴格式测试**：不作 renderer 迁移；native 输出改 C2 intent（T04，依赖 harness-api） |
| `SC/assets/records.py`+`SC/core_wire.py` | `server_assets`/`server_profile_assets` 表（pacthold `storage/database.py:197-216,474-496` 迁移 12→13）、`assets.publishMcp`→`assets_publish_mcp`（core_wire.py:882）、`assets.probe`（:830）、`_asset_refusal`（:77） | 语义迁往 MCP 描述符；compat 只减不增（T09，删除归 C0） |
| `SC/composition.py:995-1166` | MCP 装配段：verify→`MCP_CREDENTIAL_INJECTION_UNVERIFIED` 拒绝任何 env→render→`/runtime/home/` target→asset_files；subagent bridge 同段耦合（composition.py:1078-1140） | 拆出本域经公开注册点装配；不吸收 subagent bridge（T09） |
| 测试 | `apps/server/tests/test_asset_hubs.py`（:116/:149/:163/:211/:258/:410/:662）、`test_asset_surface_refusals_147.py`、`test_harness_mcp_config_source_086.py`、fixtures `fake_mcp_server.py`/`mcp-config-probe-server.mjs` | 作为 V01/V03 红→绿对照与旧样本来源；新包自带等价测试 |

## T00 接口绑定表（宿主实际公开 API ↔ 目标语义契约）

图例：✅ 本树已有可导入；🟡 部分/需薄适配；❌ 缺失（列入 api-requests，等 checkpoint）。

| 目标接缝 | 实际符号与位置 | 状态 |
| --- | --- | --- |
| Server typed method 注册 | `server_plugin_api.ServerMethodDescriptor/ServerPluginRegistration/ServerPluginContext/ServerPlugin`（packages/server-plugin-api/src/server_plugin_api/contract.py:57/:187/:163/:216）；host `MethodRegistry`（apps/server .../plugin_host/host.py:95）；`mcp.*` 方法 id 合法（contract.py:15）；不触碰 `wire/handlers.py` | ✅ |
| 宿主端口 | `bootstrap/runtime.py:491-502`：`database/objects/notifier/idempotency/credentials/secret_store/…`；`asset.mcp` 端口现由 compat 提供（SC/plugin.py:281） | ✅ |
| 内容寻址存储 | `SC/assets/mcp.py` 模式 + pacthold `<root>/objects/sha256/…`；**无插件自带 DB migration 贡献槽**（`PluginRegistration` 无 tables 项）→ 分配记录走插件数据根文件/插件私有 SQLite，不请求改 pacthold 中心 schema | 🟡 决策：域内自持存储 |
| 产品装配 | `products/server/src/ordessa_server_product/composition.py:40-55 default_plugins()` —— **C0 所有**，Q4 只提交 integration-request | ❌ G1 |
| Harness C2 `harness.configuration-adapters`、assess/compile/verify intent、实例 config generation、逐会话原生装载 | 代码零命中；仅 `docs/design/harness-v2`。已有最近物：`ProfileSpec.mcp_target/mcp_key` + slots 校验（plugins/harness .../registry/schema.py:76-89）、`harnesses.toml` 声明、`AcpChannelRegistry`（server_acp/registry.py）、Go bridge `session/new` 仅传 `cwd`（进程级 profile env） | ❌ G2（harness-api） |
| Profile facet `mcp.servers` | 无 facet 注册 API；profile 记录在 compat 私有 | ❌ G5（profile-api，Z1） |
| Chat 输入区/状态贡献 | composer 在 `plugins/agent/conversation/src/view.tsx` 内部，无宿主 slot API；Settings 有 `WorkbenchComposition.addSettingsSection`（packages/desktop-platform/contracts/workbench/src/workbench.ts:25-46，workbench 已实做 model.ts:120） | 🟡 Settings ✅ / Chat ❌ G6（chat-api，Z2） |
| credential service | `CredentialRecords`（apps/server .../credentials.py:11，端口 `credentials`）+ `SecretStore.read(locator)`（pacthold storage/secrets.py:19，端口 `secret_store`，非 NT 可为 None）+ `ProfileEnvelope` locator-only 约束；无统一"授权瞬间解析"API | 🟡 G7（约定解析时机，T07 用现有两层） |
| Permission `authorizeToolCall` | 零命中；现仅有 compat posture 解析（SC/profiles/permissions.py，last-match-wins，"resolves posture only"） | ❌ G3（permissions-api，Q5）；接上前不放行任何真实 tools/call（FR-09/T06） |
| Pi 受管桥 / 工具桥接入口 | Go bridge 无 `mcpServers` 符号；Pi extension 未接 | ❌ G4（等 harness-api + 受控探针定版） |

## 环境/红基线（本线复跑前取样）

见下文「基线复跑记录」（首个实现提交后由主代理回填，不引用未验证数字）。

## V00 探针回填（adapter session/new.mcpServers）——追加于 2026-09-28，不改动上文既有行

上表「Harness C2 …逐会话原生装载」行的 ❌ G2 状态不变（生产 intent 类型仍缺），但
**adapter 入口面**已由受控探针升为运行时 L2 证据（reports/t00-acp-probe.md）：

| 目标接缝 | 探针实测符号与位置（钉版工件 dist 行号） | 状态更新 |
| --- | --- | --- |
| codex-acp 1.1.14 逐会话注入 | env `CODEX_PATH` 注入假 app-server（dist/index.js:22068-22072,31645）；`session/new.mcpServers`→`thread/start.config.mcp_servers`（26578-26586,26670-26697,26735-26754）；`mcpCapabilities{acp:false,http:true,sse:false}`（28805-28809）；缺字段=线形拒（-32602），`[]`=负控干净，双会话不串，adapter 不代连 MCP | observed（L2，adapter 行为已证；真实 codex CLI 装载仍未证） |
| claude-agent-acp 0.81.2 逐会话注入 | env `CLAUDE_CODE_EXECUTABLE`（dist/acp-agent.js:515-517,6416）；mcpServers→SDK options（6214-6236,6390-6393）→CLI argv `--mcp-config`（sdk.mjs arg-builder）；`--strict-mcp-config` 实测缺席（原生发现面未抑制，V04 仍开） | observed（同上边界；树内无 tgz，本次从 npm 缓存按 lock integrity 取回） |
| C2 契约形状注意项 | client 每请求必须带 `mcpServers` 数组；http 条目 `headers` 必填（可空数组）；codex name 空白→`_`、默认 `config/read` 去重可吞同名（`DISABLE_MCP_CONFIG_FILTERING` 关）；无效条目 `vecSkipError` 静默丢 → verify 只能以后端观察为准 | 供 G2 收紧引用 |
