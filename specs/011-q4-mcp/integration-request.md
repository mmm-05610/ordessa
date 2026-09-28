# Q4 → C0 集成请求（integration-request）

1. **产品装配（G1/T09）**：`products/server/src/ordessa_server_product/composition.py default_plugins()` 增补 Q4 MCP 插件入口（待 backend/service 层 wire 描述符就绪后提精确符号）。Q4 不改 C0 文件。
2. **桥工件钉退役更正（R-Q4-2）**：`docs/baseline.md` 的 acp-bridge sha `5fd6a37b…` 对 HEAD `e30f5ff6df`+ 已漂移（Q4 现场重编两次确定性 `714044a5…`，见 reports/t04-t05-research.md §1.1 与裁定 R-Q4-2）。请 C0 重钉或在 known-issues 登记；Q4 探针报告将引用实际使用 sha。
3. **Pi 版本双 pin 裁定（R-Q4-4）**：生产闭包 `@automatalabs/pi-acp 0.5.0`+Pi 0.84.2 vs PATH CLI 0.86.1（Go-bridge 握手已证）。Q4 受控探针按 0.84.2 落证；如 C0 裁定换 0.86.1，Q4 复跑矩阵。
4. **server-compat mcp 面退出（T09 删除清单，只减不增）**：待 Q4 wire 服务+装配绿后由 C0 执行——删除/缩减 `SC/assets/{mcp.py,mcp_probe.py,rendering.py}` 的 MCP 写入路径、`core_wire.py` `assets.publishMcp/assets.probe` 注册与 `_COMPAT_METHODS` 冻结表对应项（tests/test_server_compat_boundary.py:37）、`composition.py:995-1166` MCP 段（保留其中 subagent bridge 段归 Q3/C0，勿随 MCP 一并删）、`server_assets` mcp kind 写入方；数据保全：`server_assets`/`server_profile_assets` 行经 `adopt_legacy_revision` 按旧摘要迁移（Q4 已交付 API+字节互证），迁移脚本归属 T09 后续提交。
5. **根锁/依赖**：方案 A（复用树内已钉 `@modelcontextprotocol/sdk` 1.29.0 MIT，零新增）为 Q4 managed lane 默认路线；若 C0 裁定 Python `mcp` SDK（方案 B），依赖清单见 reports/t04-t05-research.md §5，需 C0 生成根锁。

## 增补（T09-service / T08-frontend 批，2026-09-28 晚）
6. **产品装配精确符号（更新 G1）**：`default_plugins()` 增补 `ordessa_mcp.plugin.McpAssetServerPlugin`（descriptor id `ordessa.asset.mcp`，provided_ports `asset.mcp.v2`，12 个 `mcp.*` descriptors，error-families 贡献 46 码与现有表零重叠）。
7. **请求级 principal 注入面（C0/host 缺口）**：wire/1 与 plugin_host 实测 `principal` 零命中，handler 只收 params；Q4 服务层已把 principal 显式入参并做域内隔离，但 wire 面上为 caller-claimed。宿主注入认证 principal 后仅需替换 handler 取值点。Q4 不造假 auth。
8. **desktop extensions.json 登记**：`@ordessa/plugin-asset-mcp`（`plugins/assets/mcp/frontend`，manifest hostApi '2'）+ `ordessa.asset.mcp.status-chip`→`McpStatusChip` 的 chat resolver key 入表（C0 装配面）。
9. **credential 端口注入**：Server plugin context 注入 `credentials`/`secret_store` 端口到 `asset.mcp.v2` 服务面（T07 HostCredentialPort 适配已就绪，等装配）。

## 增补（T05-client 批，2026-09-28 深夜）
10. **managed client 路线裁定（限定替代在案）**：条目 5 的"方案 A 复用树内钉 `@modelcontextprotocol/sdk` 1.29.0"经勘察**不在根 package-lock 闭包**（根锁/根 package.json 零命中；根无 node_modules；`require.resolve` MODULE_NOT_FOUND），1.29.0 仅钉于 `plugins/harness/packaging/pi/package-lock.json:47/:2397`（harness/C0 锁面，Q4 不跨界取包）。故 Q4 已按 research-and-reuse「限定替代」条款落地 `backend/managed/client_stdio.py`：stdio JSON-RPC 最小 client（initialize 协商/tools-list/tools-call/close-cancel，无 resources/sampling/elicitation；remote 传输显式 `MCP_TRANSPORT_UNSUPPORTED` 拒），L2 受控 fake server 全证据见 reports/t05-client.md。**请 C0 裁定**：(a) 引入官方 Python `mcp` SDK（依赖清单=条目 5/报告 t04-t05 §5，需 C0 生成根锁），或 (b) 授权本线复用 TS SDK（跨锁桥接方案+供应链口径），或 (c) 维持本限定替代为过渡形态并登记 known-issues。D5 权限缝已统一为 `backend.permissions.check_tool_callable`/`ToolCallDecision` 单一 Protocol（bool 双形已删除）。


## 增补 2（permissions-r4 消费轮实测）
11. **npm workspaces 卷入**：根 `package.json` glob `plugins/**` 实测已自动收纳 `plugins/assets/mcp/frontend`（`@ordessa/plugin-asset-mcp`，当前 UNMET 仅因本树未 npm ci）。C0 下次生成根锁会包含该 link 与其依赖边（应零新第三方依赖——frontend 仅 dev 用 vitest/typescript，运行时 import 全为 workspace 内包；请 C0 复核 lock diff 归因于此）。根 `typecheck` 脚本只跑 apps/desktop，不受影响。
