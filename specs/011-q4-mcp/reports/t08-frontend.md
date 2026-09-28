# Q4 T08 — MCP 前端可先行 glue（plugins/assets/mcp/frontend）

日期：2026-09-28 · 工作树：`worktrees/011-q4-mcp` · 范围：仅新增前端扩展包与本报告的写入；未改动任何既有文件。

## 1. 文件清单（全部新文件）

| 文件 | 作用 |
| --- | --- |
| `plugins/assets/mcp/frontend/package.json` | npm 名 `@ordessa/plugin-asset-mcp`，`ordessa.id: ordessa.asset-mcp` |
| `plugins/assets/mcp/frontend/manifest.json` | `{"id":"ordessa.asset-mcp","version":"0.1.0","hostApi":"2","entry":"entry.js"}`（过 `extension-loader/src/manifest.ts::parseManifest` 全部规则） |
| `plugins/assets/mcp/frontend/build.mjs` | 复用 `tooling/build-extension.mjs`（esbuild bundle，external react/@extensions/@ordessa/extension-api） |
| `plugins/assets/mcp/frontend/tsconfig.json` / `vitest.config.ts` | 仿 `plugins/chat/api`、`plugins/chat/frontend` 的 paths/alias（契约指向真实源文件） |
| `src/dto.ts` | wire DTO（canonical v2 literal/secretRef、probe facts、连接/目录/预览形状），与 `plugins/assets/mcp/backend/definition.py`、`probe.py::_handshake_facts` 对齐 |
| `src/wire.ts` | `McpWireClient` 接口（11 个 camelCase 方法 ↔ `mcp.*`）+ `createFetchMcpWireClient`（wire/1 JSON-RPC 信封，`POST {base}/wire/v1/{method}`）+ `MCP_WIRE_METHODS` 绑定表 |
| `src/status.ts` | `McpStatusService` 抽象 + 六级事实分级（defined/approved/enabled/connected/catalog/callable）+ wire 驱动实现；无 client ⇒ `absent`，不造数据 |
| `src/credentials.ts` | `CredentialProvider` 凭据提供者抽象（只有 listCredentials——**无任何返回明文的接口**） |
| `src/settings.tsx` | MCP Settings section 组件（定义列表、stdio/remote 编辑、literal/secretRef 分流、独立批准动作、有限探测与范围声明） |
| `src/chat.tsx` | `createMcpChatInputSource`（ChatInputSource，plus 面板）+ `mcpStatusChipContribution`（chatContribution()/composer.toolbar）+ 文案分级函数 |
| `src/entry.tsx` | 插件 `ordessa.asset-mcp`：`requires: [WorkbenchToken, ChatContributionsToken]`，注册 settings section + chat 贡献；导出 `registerMcpFrontend` 供会话服务 owner 注入真实 client |
| `tests/{fakes.ts,wire.test.ts,status.test.ts,chat.test.ts,settings.test.tsx,entry.test.ts}` | vitest 单测（in-memory fake McpWireClient；chat 用例走真实 `createChatContributions` 注册/查询/撤销路径） |

## 2. 组件 × ux.md 条目映射

| ux.md（docs/design/mcp/ux.md）条目 | 实现位置 | 说明 |
| --- | --- | --- |
| Settings 列表：定义名/transport/批准修订/来源/上次**探测**结果 | `settings.tsx` `McpSettingsSection` 列表区；`probeColumn` | 探测列文案固定为「探测成功（无凭据，rN · 时间）— 非会话连接」/「探测被拒（code）」/「未探测」；列表断言 `not.toMatch(/已连接|连接成功/)` |
| 「探测成功」文字不得变成「会话已连接」 | 同上 + `tests/settings.test.tsx` 第 1 用例 | 探测与连接是两套词，probe facts 里也渲染「探测成功 ≠ 会话已连接」 |
| stdio command/args/cwd 与可读常量编辑 | `settings.tsx`（command/args；**env** literal 行）| 注意：现行后端 canonical（`backend/definition.py` 与 legacy `SC/assets/mcp.py` 互证）**不含 cwd 字段**（stdio 仅 command/args/env），故未给 cwd 造输入框——待域侧新增字段后随 canonical 一起加 |
| 远端 URL/headers/授权引用 | `settings.tsx` remote 分支 + headers ValueRows | |
| 秘密输入委托统一凭据提供者、页面不回显明文 | `credentials.ts::CredentialProvider`（仅 id+label 列表）；secretRef 行渲染为 select（值只能是 credentialId）或只读引用 | 明文从不进入本包任何类型/组件 |
| 缺 Credential 服务时 secretRef 只读且不能应用 | `settings.tsx`：无 provider ⇒ secretRef 行 `input disabled`、「+ secretRef 条目」禁用、「批准并用于选择」`disabled` + `mcp-approval-blocked` 文案；测试断言 approveRevision 从未被调用 | |
| 保存候选修订 → 独立「批准并用于选择」 | `save` 只调 `mcp.saveRevision`（文案「已保存候选修订（尚未批准，不参与选择；保存不探测、不启动）」），`approve` 单独按钮调 `mcp.approveRevision` | 测试断言两次独立调用且顺序 |
| 有限探测按钮 + **无凭据**范围声明 | `runProbe` → `mcp.probe`；`ProbeFactsView` 渲染 `credentialScope: unproven`、`credentialsExcluded` 槽位、`doesNotProve` 全列表 | 拒绝路径保留 typed `PROBE_*` code，不软化成成功 |
| Chat 输入区按需打开 MCP 状态/选择小面板 | `chat.tsx::createMcpChatInputSource`（surface `plus`）经 `ChatContributionsService.addInputSource` 注册 | 六级：已定义/已批准/已启用/连接成功/工具已发现/本次可调用（`status.ts::MCP_LEVEL_LABELS`），`serverFactLine` 保持 pending/catalog-changed/refused/unknown 各是各话 |
| Pending 和 Unknown 不是 Connected | `status.ts::grade`（connected 仅凭 inspectConnection 证据；callable 仅后端明说且需已有 catalog）+ chat/status 测试各 1 用例 | |
| 服务缺席 → 面板 unavailable，不造数据 | `createMcpStatusService(undefined)` 恒 `absent`；输入源回单条 disabled「MCP 状态服务不可用」；entry 无 wire client 时 **不注册** Settings section（contracts.md §2「后端 provider 缺席时设置区域不显示」） | |
| Profile 编辑（facet UI） | **跳过**（见 §5） | |
| 审批用既有 UI、不画第二套弹窗 | 本包未实现任何审批弹层 | 工具调用审批属 T09+/Permission，前端 glue 不触碰 |

## 3. 实际跑过的命令与真实退出码

前置事实：本工作树**没有 node_modules**（根依赖未安装）；未运行 `npm ci`/`npx`（避免动根 lock 或拉取版本漂移）。Node 模块解析沿父目录链命中主仓 `/home/maoqh/projects/ordessa/node_modules`（与 `package-lock` 同版本：vitest 4.1.10 / react 19.2.7 / jsdom 29.1.1 / typescript 6.0.3 / esbuild 0.28.1），因此无需局部安装。所有命令在 `plugins/assets/mcp/frontend/` 执行：

| 命令 | 结果 | 退出码 |
| --- | --- | --- |
| `/home/maoqh/projects/ordessa/node_modules/.bin/vitest run --maxWorkers=1` | `Test Files 5 passed (5)`，`Tests 31 passed (31)`（wire 4 / status 8 / chat 8 / settings 7 / entry 4） | 0 |
| `/home/maoqh/projects/ordessa/node_modules/.bin/tsc --noEmit` | 无输出（strict，src+tests） | 0 |
| `ORDESSA_PRODUCT_OUTPUT_ROOT=/tmp/t08-frontend-build node build.mjs` | 产出 `/tmp/t08-frontend-build/extensions/ordessa.asset-mcp/{entry.js,manifest.json}`（32KB bundle；**未写 products/**） | 0 |
| manifest 规则内联复核（ID/版本/hostApi=2/entry.js） | 全部通过 | 0 |

（首跑记录：中途 2 轮红：1 个 await 优先级 bug、1 个 oxc 解析错误 + 1 个测试选择器缺陷，修复后如上全绿；无删断言、无 skip。）

## 4. 未跑项与原因（不产假绿）

- **electron smoke / 产品装配运行**：`products/desktop/extensions.json` 登记归 C0 integration-request，本包尚未装配；无 headless 桌面环境跑真实 shell。标 untested。
- **对真实 Server 的 wire 往返**：`mcp.*` 方法描述符由 T09（同树并行施工中）注册，`MCP_WIRE_METHODS` 的 11 个 id 是按 contracts.md §1 操作表的 camelCase 拟定值，须由 T09 `plugin.py` 最终核对（fetch 信封本身按 `wire/envelope.py` 真实规则测试过）。
- **Workbench Settings 页内嵌渲染**：只跑了 fakeWorkbench + 组件级 jsdom，未在真 `WorkbenchShell`（含 openSettings 定位、空态）里挂载；workbench 自身测试覆盖宿主侧。
- **chat 前端真实 composer/InputPanel 渲染**：见 §6 resolver 缺口。
- **Profile facet UI**：跳过（Z1 r2：profile-api 与 foundation 组合不兼容，登记于此前 checkpoint 报告）；本包不含任何 Profile 贡献。

## 5. Profile facet

按任务指示整项跳过，未写任何 `mcp.servers` facet 代码；T08 交付不含 Profile 面，待 Z1 裁定后另起。

## 6. C0 integration-request 素材（需要登记的装配面）

1. `products/desktop/extensions.json` `enabled` 追加：`"ordessa.asset-mcp"`（前置：`ordessa.contracts`、`ordessa.workbench`、`ordessa.chat-api`、`ordessa.chat`（chat frontend，提供 `ChatContributionsToken`）均已在启用链上）。
2. 可选 per-extension 配置（host 原样转发给 entry factory）：
   `{"config": {"ordessa.asset-mcp": {"wire": {"baseUrl": "http://127.0.0.1:<port>"}}}}`；缺席即「后端 provider 缺席」形态（无 Settings section、面板 unavailable）。
3. **chat composer.toolbar resolver 缺口**：`plugins/chat/frontend/src/views/chat-page.tsx:71` 的默认 resolver 表是 chat 内部表，外部 key 现在会「位置留空」渲染；集成需把 `ordessa.asset.mcp.status-chip` → 本包导出的 `McpStatusChip` 加入该表（或 chat 提供注册通道）。在此之前小面板主通道（ChatInputSource/plus 面板）完全可用。
4. **凭据提供者 token**：平台尚无 Credential 服务 DI token（T07 只有 Python 宿主端口）；`registerMcpFrontend` deps 已预留 `credentials` 槽，集成时以真实 provider 注入。
5. **T09 方法名核对**：`mcp.listDefinitions/getDefinition/saveRevision/approveRevision/archiveDefinition/probe/assign/unassign/resolvePreview/inspectConnection/listTools` 需与 `backend/plugin.py` 描述符一致（源表：`src/wire.ts::MCP_WIRE_METHODS`）。
6. wire client 的鉴权头：`createFetchMcpWireClient({ headers })` 由会话服务 owner 供给（token 文件归 owner），本包不持有凭据。

## 7. 依赖的 chat-api / workbench 真实符号（非自造证明）

| 消费符号 | 构造处（文件:行，本树实际路径） |
| --- | --- |
| `WorkbenchToken` | `packages/workbench/api/workbench.ts:60`（任务书写的 `packages/desktop-platform/contracts/workbench/src/workbench.ts` 不存在；foundation 载体 `packages/desktop-platform/contracts/foundation/src/contract.ts` 再导出之） |
| `WorkbenchComposition.addSettingsSection` / `openSettings` | `packages/workbench/api/workbench.ts:41/:45`；宿主语义 `packages/workbench/src/model.ts:108-115`（openSettings 校验 section id）、`src/shell.tsx:97-122`（sections 渲染 + 「没有已注册的设置分区」空态） |
| `Workbench.composition?`（缺席即拒绝，不回落旧 view id） | `packages/workbench/api/workbench.ts:57` |
| `ChatContributionsToken` / `ChatContributionsService.addInputSource/addContribution` | `plugins/chat/api/src/contract.ts:402/:392-395`；注册语义 `plugins/chat/api/src/registry.ts:171-200`（重复 id 拒绝、scope 关闭精确撤销——被 tests/chat.test.ts 直接执行） |
| `chatContribution()`（opaque 注册记录） | `plugins/chat/api/src/registry.ts:57`，经 `contract.ts:406` 再导出 |
| `defineChatComponentKey` / `ChatComponentKey` | `plugins/chat/api/src/contract.ts:31/:27` |
| `ChatInputSource/ChatInputEntry/ChatInputQuery/ChatInputSurface` | `plugins/chat/api/src/contract.ts:243/231/207/205`；`query` 只读语义与 abort=UI 取消见 `registry.ts:119-143`（测试覆盖 abort 行为经 queryReady 轮询真实状态机） |
| `ChatSlot`（composer.toolbar）/ `ChatProjection` | `plugins/chat/api/src/contract.ts:168-174/191` |
| 消费接缝 `ChatSessionGateway`（任务书写作 ChatSessionsGateway，实际符号单数） | `plugins/chat/api/src/contract.ts:343-349` — 本包**不**发送消息，仅注明该 seam 属会话 owner |
| 插件生命周期 `Token/PluginContext/ResourceScope/scoped` | `packages/desktop-platform/extension-api/src/index.ts`（entry 用 `context.resources` 作唯一注册作用域） |
| 入口工厂/配置转发 `(api, config)` | `packages/desktop-platform/extension-loader/src/index.ts:16` |
| wire/1 信封 `jsonrpc/id/method/params` + 单 `result|error` | `apps/server/src/ordessa_server/wire/envelope.py:32/:51`、路由 `transport/http/app.py:115` |
| 域形状 literal/secretRef、probe facts | `plugins/assets/mcp/backend/definition.py`（v2 typed values）、`backend/probe.py:418-441`（credentialScope unproven / doesNotProve 清单） |

## 8. V08 反例覆盖情况（前端可证部分）

服务缺席（§2 三处 fail-closed 行为）、悬空引用（批准后消失→grade 停在 defined；enabled 无批准→停在 defined 的护栏在 `status.ts::grade`）、pending≠connected、探测≠连接、保存≠批准、secretRef 不可应用、scope 关闭撤销贡献——均有断言用例；「provider 卸载后重挂」与「输出期间变更不打断当前输出」属宿主/会话行为，随 T10 无模型 UI smoke 验收（本包按「面板仅按需 query，无常驻改写」的形态遵守，未单测宿主渲染时机）。
