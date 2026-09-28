# Q1 集成请求（交 C0 收口的公共面）

本线只写 `plugins/assets/skills/**` 与本 feature 文档。以下项需要公共所有者执行或复核，
本线未自行提交（AGENTS.md 规则 5/7、共同 plan「C0 另独占 products/根锁/tooling/compat 公共删除」）。

## 1. 产品装配（G1）
- `products/server/src/ordessa_server_product/composition.py:40-55` 的 `default_plugins()` 加入
  `SkillsServerPlugin()`（`ordessa_skills.plugin`，插件 id `ordessa.skills`，
  `requires=("ordessa.workspace",)`）。裸组合需与 `WorkspaceServerPlugin` 同启（已实测）。
- `products/desktop/extensions.json` + `extensions.lock.json` 登记桌面扩展 `ordessa.skills`
  （目录 `plugins/assets/skills/desktop`，manifest id `ordessa.skills`）与其消费的
  `plugins/assets/skills/contracts` TS 包；本线 `npm run build` 未启用它时只被发现不装配。
- 本树曾出现 `products/desktop/extensions.lock.json` 中
  `extensions/ordessa.workbench/entry.js` 哈希漂移（他线产物），已 `git checkout --` 还原未提交；
  请 C0 在集成树复算该哈希是否为构建非确定性。

## 2. 兼容面退役账（G20，必须与本线新服务互斥完成）
现存唯一实现是 server-compat 的 `assets.*`。本线 `skills.*` 19 个方法与冻结 compat 方法集
**不重名**（`test_wire_skills_family.py` 断言不相交）。待 C0 执行：

| 旧符号 | 位置 | 目标 |
| --- | --- | --- |
| `assets.list/publishSkill/bind/unbind/bindings` | `core_wire.py:252-262, 854-975` | 由 `skills.*` 承接后删除，保留历史 wire 兼容语义或按已审迁移映射 |
| `assets.syncCatalog/catalog/installFromCatalog` | `core_wire.py:779-828` | 同上 |
| `assets.publishMcp/publishPlugin/probe` | `core_wire.py:830-930` | **不属 Skills**，转 mcp/plugin 资产域接管单 |
| `SkillAssetStore` / `AssetRecords`（skill 相关） | `ordessa_server_compat/assets/{skills,records}.py` | 唯一实现转 `ordessa_skills.library`，旧类删除，不留 shim |
| `profiles/clone.py` 的 `copy_bindings`（skill 项） | `:104-115` | 改走 Skills 公开 API（Z1 与 C0 协调） |
| `apps/server/tests/test_asset_hubs.py` skill 段 | `:40-163` | 与 v2 套件合并/转移，不留双实现测试 |

## 3. 数据库迁移（本线自建表须入共享迁移链）
本线在 `assignments/store.py::ensure_schema()` 内建了三张本域表，DDL 需原样搬入
`packages/pacthold/src/pacthold/storage/database.py` 迁移链并由 host 统一版本推进：
`skill_assignments`、`skill_assignment_operations`、`skill_binding_cas`
（列与索引以 `assignments/store.py` 当前实现为准；本线未改 `server_assets`/`server_profile_assets` 任何字节）。
`server_profile_assets` 既有固定修订绑定 → Profile `enable(revision)` 的迁移**尚未执行**，
需 Z1 的 profile-api 与迁移裁定（G08 要求双向样本与回滚证明）。
Skill 版本批准记录当前落在资产根下 `approvals/<assetId>.json` 文件树；
若 C0/Z1 判定应入库加列，属共享 schema 变更，本线未擅自加列。

## 4. 平台接口缺口（符号级）
1. `server_plugin_api` 无面向插件的类型化拒绝协议：`WireService.dispatch` 只识别
   `ordessa_server.wire.errors.WireError` / `ordessa_server.errors.ServerError`，而本线纯度门禁禁止导入宿主业务模块，
   现以 `WireError.__cause__.code` 传递本域错误码（`internalCode` 丢失）。请求 C0 在插件 API 提供中立拒绝类型。
2. `workspace.records.get()` 抛 `ServerError("WORKSPACE_NOT_FOUND")` 而非返回 `None`，
   与本线 `WorkspaceLookup` 端口不匹配，现为 `plugin.py` 内的 duck-typed 适配器；请求 C0/Z1 定契约。
3. 宿主 `idempotency` 端口（`IdempotentRecords`）在插件域不可用，本线改用本域操作账
   `skill_assignment_operations`（CAS+重放已测）。请 C0 提供可注入的中立幂等端口。
4. `docs/baseline.md` Backend 安装行缺 `-e packages/server-plugin-api`（见 implementation-baseline.md §2），
   照抄会失败；本线未改公共文档。
5. apps/server 套件在本树收集期 78 errors：产物门禁引用旧路径
   `plugins/agent-box-harness/runtime/worker-entry.mjs` 与
   `plugins/agent-box-harness/packaging/claude/node_modules/@agentclientprotocol/claude-agent-acp`（均 ABSENT），
   且 `TOOL_claude=ABSENT`。若属命名收口残留，请 C0 判定并更新门禁；本线未动宿主测试。

## 5. 本阶段实测到的上游缺陷（不在本线写入面，转 C0）

1. **Pi 投影 argv 与固定版本可能已失效**：`plugins/harness/src/ordessa_harness/pi/projection.py:35`
   注入 `--skill-dir /runtime/home/skills`、`--agent-dir /runtime/home`；在本机唯一可运行的 pi（0.86.1）上
   实测 `Error: Unknown option`（exit 1）。pin 0.84.2 的旗标集本机无产物可测。
   证据与复现命令：`specs/011-q1-skills/research/probe-results.md`。请 C0 在补齐 0.84.2 产物后复测并修投影旗标。
2. **Claude 用户级 skills 根默认不生效**：`CLAUDE_CONFIG_DIR/skills` 需 launcher 传
   `settingSources` 含 user 且 `skills:"all"`（实测于 adapter 0.81.2 精确 pin）。
   本线 `harness_adapters/capabilities.py` 因此把该格保持 `unknown`；接线后需与 C0 一起复测。
3. **`skills/changed` 只观测到 `extraRoots/set` 触发**（0.155.0-alpha），文件变更触发未观测到；
   codex-acp 1.1.14 dist 静态实测忽略 `skills/changed` 而按 session/prompt 重同步。
   结论：本线不实现「靠通知驱动 reload」的假设，更新只在下一次提交时重合成完整集合。

## 6. npm 根锁增量
本树 `npm ci` 后新增 workspace 由 `plugins/**` glob 自动发现，未手改根 `package.json`/`package-lock.json`
（若有生成漂移仅出现在本树临时态，导出检查点前已还原他主文件）。最终根锁由 C0 生成。

## 6. 请 C0 在集成后跑的 Q1 门
`.venv/bin/python -m pytest plugins/assets/skills/tests -q`（本线套件）；
`cd plugins/assets/skills/desktop && npx vitest run`；消费 harness-api/profile-api/chat-api 后，
`harness_adapters/` 的纯意图词汇需 1:1 映射到真实注册点并重跑 G10–G13、G16、G19（L3），
`assignments/ports.py` 的 Profile 层需换成真实 profile-api 后重跑 G08/G09。

## 7. 消费 permissions-api r4 会摧毁 Z1 交付（请求 C0 裁定、Q5 修分支后重发）
实测（本树 `e3358c0790` 上 `git merge --no-edit ad8902d5c8`）：合并结果删除 **55 个上游文件**，含
`plugins/profile/pyproject.toml`、`plugins/profile/src/ordessa_profile/*`、`plugins/profile/api/*`
（Z1 已发布 profile-api `4943628f47` 的交付物）与 `evidence/platform-bindings.md`；合并后
`pip install -e plugins/profile` 报「不是 Python 工程」。这属共同 plan 禁止的「挑一边整文件覆盖」，
不是 Q1 可修的问题。
本线处置：立即 `git reset --hard` 回退到合并前 `e3358c0790`（该 merge 结果保留在本地分支
`q1-abandoned-permissions-r4-merge` 供比对），回退后 Z1 包在位、门数与回退前一致
（393 passed + 同 6 条上游红；桌面 125 passed）。
请求：Q5 让 r4 检查点分支不再删除兄弟 lane 的包，或 C0 在集成树统一裁决其分支基底；
修好后重发 `-r5`，Q1 按固定 publication SHA 重新消费并复跑 `mandatory_policy` 的 12 条测试。
