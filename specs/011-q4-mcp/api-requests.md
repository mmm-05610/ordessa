# Q4 → 兄弟线接口请求（api-requests）

按 `specs/011-plugin-rollout/contracts/checkpoints.md`「依赖不构成整线停机」维护。生产者可用
`git show codex/011-q4-mcp:specs/011-q4-mcp/api-requests.md` 读取。

| ID | 请求 owner | 调用者（Q4 侧） | 目标操作/DTO | 为何阻塞 | 反例要求 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| G1 | C0 | `products/server` 装配 | `default_plugins()` 增补 `McpServerPlugin()` 入口（仅声明已有公开贡献） | T09 产品装配不能在 Q4 树改他 owner 文件 | 裸宿主不含 MCP 业务符号 | OPEN，随 T09 提 integration-request |
| G2 | C0 (harness-api) | T04 `adapters/codex*`/`adapters/claude*`；T05 native 互斥校验 | `harness.configuration-adapters` 注册点；C2 intent 类型（compile 对完整有效集合产唯一目标快照）；实例 config generation / target 句柄；verify 的原生观察 DTO（server name/transport/加载状态/catalog digest） | native lane 只能编译 intent，不能自写 HOME；无真实类型则 T04 生产代码无法落地 | 只有文件落盘不得报 loaded；额外原生来源被识别 | OPEN — 等 `codex/011-harness-api-ready` |
| G3 | Q5 (permissions-api) | T06 `backend/permissions*` glue；一切 tools/call 代理 | `authorizeToolCall(principal, sessionRef, leaseId, toolName, argsDigest, policyRevision) -> decision`；有界预授权形状；拒绝/过期/未知类型化 | FR-09 强制前置；未接上前 Q4 不放行任何真实调用（含测试放行的生产路径） | 已发现未授权工具在副作用前拒绝；无 UI 不放行 | OPEN — 等 `codex/011-permissions-api-ready` |
| G4 | C0 + Q4 联合受控探针 | T05 `adapters/pi*` | Pi extension 受管工具桥接入口（Server 校验的登记，扩展不得持 secretRef/直连） | bridge 现无 mcpServers/session 配置传递证据 | 扩展绕过授权的路径必须被拒 | OPEN，探针落证前 Pi 仅管理定义 |
| G5 | Z1 (profile-api-r2 请求见下) | T02 Profile scope 解析、T08 facet | facet 注册 API（`mcp.servers` 值=定义引用/决策/toolSelection）；validate 用 MCP 只读服务核对 | Profile 分配生效链与 UI 面 | 提供者缺席时数据保留、apply fail-closed | OPEN — 等 `codex/011-profile-api-ready`；Q4 先以纯函数实现解析序 user-default→project→profile→session（V02 可在本树全绿） |
| G6 | Z2 (chat-api) | T08 Chat 状态小面板 | 输入区贡献点 + 会话状态 DTO（pending/connected/catalog-changed/refused 分级） | Chat glue 不可用内部模块 | 输出中变更不打断 | OPEN；UI glue 缺席不阻止后端条目 |
| G7 | C0（credential 约定） | T07 `backend/secret*` glue | 统一「授权瞬间解析」时机约定（现两层：`CredentialRecords` + `SecretStore.read(locator)`；非 NT 平台 secret_store 可为 None 的 fail-closed 行为） | plan 绑定 secret revision / 轮换失效需要固定语义 | 明文不落持久定义/日志/事件/native 文件；stale revision 拒绝 | PARTIAL — Q4 先用现有两层实现并记录局限 |
| G8 | C0 (foundation) | 全线 | foundation 检查点发布后按固定 publication SHA merge（含 server-plugin-api/harness 最终导出） | 生产组合门（V09/V10）依赖最终集成 | — | OPEN（2026-09-28T18:00Z 未发布） |

约定：Q4 不以 stub/假接口冒充以上接缝；依赖型条目在对应 checkpoint 发布前保持未勾选。

## G5 更新（2026-09-28 消费 foundation+profile-api 后）
- **实测不兼容**：合并 `codex/011-foundation-ready`(8844c475bc) 后，`pacthold.resource_contracts` 模块已被 C0 迁至 `pacthold_runtime_compat.resource_contracts`（683d67f96b；harness 已用新路径），而 profile-api 检查点 `codex/011-profile-api-ready`(4943628f47, impl f5435be938) 的 `plugins/profile/src/ordessa_profile/plugin.py:17` 仍 import 旧路径 → 本树 `import ordessa_profile` 抛 `ModuleNotFoundError`，`pytest plugins/profile/tests` 收集即红。
- **owner 裁定请求（Z1）**：请 Z1 按 checkpoints.md 消费规则合并 foundation 固定 SHA 并发布 `profile-api-r2`（或声明兼容关系）。Q4 不代改 Z1 代码；facet 接线（T08 Profile 面）在 r2 前保持未勾选。

## Q5 线通知（跨检查点漂移，2026-09-28）
- 消费 `codex/011-permissions-api-ready`(bcd4387bec) 后与 foundation 组合实测：`plugins/permissions/backend/tests` 收集 9 errors（`tests/support.py` import 旧 `pacthold` storage/DB 路径；T009 已迁至 `pacthold_runtime_compat.storage`，harness/profile 同样踩旧路径）。API 运行时包 `ordessa_permissions_api` 导入正常。请 Q5 消费 foundation 固定 SHA 后发布 `permissions-api-r2`（或注明兼容 merge 序）。Q4 适配层已用真实 backend 类完成受控 proof（reports/t06-wiring.md），不等 r2。

## G9（2026-09-29 T10-Pi 探针后向 C0 追加）：Pi runtime 装载面与版本裁定
- **请求 owner**：C0（harness/runtime）。**调用者（Q4 侧）**：T10 managed Pi 桥
  （`plugins/assets/mcp/adapters/pi/ordessa-mcp-bridge.ts` + `backend/managed/pi_bridge.py`，
  证据 `specs/011-q4-mcp/reports/t10-pi-probe.md`）。
- **目标操作/DTO**：
  1. Pi 进程 launch 时的**正式扩展注入入口**：现仅 Go 桥内部硬编码注入自家 gate 扩展
     （`adapters/acp-adapter/internal/pi/gate_extension.go` 写临时 `.ts` +
     `client.go:1008 --extension <gate>`），无面向上层的通用扩展槽；Q4 需要
     start/connect/close 形状下可声明「追加受管扩展路径 + `ORDESSA_PI_BRIDGE_HOST/PORT/TOKEN`
     三个 env」的装载面（探针实证 `pi --mode rpc --no-session -e <ext.ts>` + 上述 env 在
     0.86.1 全链可行：加载/登记/拒绝/清理四格 observed）。
  2. **R-Q4-4 裁定**：生产闭包 pin `@earendil-works/pi-coding-agent` 0.84.2 vs PATH 实装
     0.86.1（本次探针只能以 0.86.1 为对象）。请裁定复测目标版本或重 pin；探针所依赖符号清单
     （0.86.1 已实测）：`--extension/-e`、`--mode rpc`、`--no-session`、`PI_OFFLINE`/
     `PI_SKIP_VERSION_CHECK`、扩展工厂 await-before-session-start、`registerTool`
     （`ToolDefinition.execute(toolCallId,params,signal,onUpdate,ctx)`）、`registerCommand` +
     RPC `prompt` 命中扩展命令不经 LLM、`extension_ui_request/notify` 回帧、`getAllTools()`、
     `session_shutdown`、JSONL `\n` framing。
  3. **C 格（真机 tools/call）升格路径**：需要无凭据的 loopback fake-provider 或等价机制
     （`pi.registerProvider` legacy 形状 `api:"openai-completions"`+baseUrl 或 `streamSimple`
     码钩）由 C0 判定是否属受管测试面；否则该格挂「需凭据」直至获用户真模型授权。
  4. pi-acp 0.5.0 每会话 `mcpServers→InlineExtension` 静态链若入生产，连接唯一 owner
     （adapter 内 bridge vs MCP 域 managed/session_manager）须与 §3 设计「一 owner」条款一并裁。
- **为何阻塞**：无 1/2 则 Pi managed lane 停在 L3-非生产闭包，不能标 ready（harness-adapters
  「未通过入口门不得声称可用」）；无 3 则调用格真机证据缺口保持 unknown。
- **反例要求**：装载面不得允许扩展持 secretRef/直连目标 server（Q4 侧扫描钉死，扩展源
  仅 `node:net` + `127.0.0.1` 字面量）；token 一次性绑定，重放必须拒（已 observed）。
- **状态**：OPEN（G4 的运行时前置；Q4 本树证据已到 reports/t10-pi-probe.md 所列格，不虚报）。

## V00 探针回填结论（2026-09-28，R-Q4-3 / G2 session-intent——仅追加，不改上文既行）

- **结论**：`session/new.mcpServers` 在钉版 codex-acp 1.1.14 与 claude-agent-acp 0.81.2 均实证被消费
  （分别注入 `thread/start.config.mcp_servers` 与 CLI argv `--mcp-config`，逐字段保真、空列表不注入、
  双会话不串、adapter 不代连；证据 reports/t00-acp-probe.md）→ **R-Q4-3 的 C2 session-intent 路线
  在 adapter 入口面成立**，可作为 G2 intent 收紧的一手依据；真实 codex/claude CLI 对注入载荷的装载格
  仍未证（本机 PATH 零命中），G2 关闭仍需 C0 类型 + 品牌 L3 证据。
