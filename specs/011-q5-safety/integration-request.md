# Q5 收尾交接清单（integration-request.md）

消费记录：`foundation` publication `8844c475bc`（merge `52906b514d`）、`chat-api` r3 publication `3d8c3fa410`（merge `7b4de06148`）。
`profile-api` publication `4943628f47` 已消费后回退（revert `b4b48d7564`），原因见 §E。

## A. 待 C0 唯一 owner 替换的旧权威（本线不改 shared compat）

| 旧物 | 现位置 | 调用方 | 目标 | 需要的迁移事实 |
| --- | --- | --- | --- | --- |
| 审批唯一权威（旧） | `plugins/server-compat/src/ordessa_server_compat/approvals/records.py`（`ApprovalRecords`，表 `server_approvals`） | server-compat 内 approvals 调用方与 `approvals.decide` 路由 | `ordessa_permissions_backend.ApprovalFacts`（表名、ID 形态、`approval.requested/settled` 事件名、CAS+`decideRequestId` 幂等全部保真；列已做 PRAGMA 级比对） | 切换写入方到 `permissions.authorizer@1`，保留旧 wire ID 与数据 ID；两权威并存已被本线测试证明会在同一行产生冲突（见 `plugins/permissions/backend/tests/test_permissions_backend_dual_authority.py`），不得双路接同一 native request |
| 旧 last-match-wins 规则引擎 | `.../profiles/permissions.py`（`resolve()` 后匹配覆盖前 deny） | Profile 权限表单/执行配置冻结 | 用户意图导入 `ordessa_permissions_api.PermissionIntent`；上限另由 `PolicyCeiling` 可信来源 | 不等价条目 `needsReview`、保留原值、不自动 allow（`specs/011-q5-safety/api-requests.md` G6） |
| 品牌投影 | `.../profiles/posture_config.py`、`posture_translation.py` | 旧 Profile 写盘路径 | `ordessa_permissions_adapters`（claude/codex/pi 的 `entries`/`claims` 由这两个文件的实测可写路径导出） | 写盘成功不等于生效；L2/L3 未证格保留 UNKNOWN |
| 桌面 Settings 页宿主 | `packages/workbench/src/shell.tsx:114` + `plugins/workbench/src/model.ts:124` | Workbench | 无需改动；`sandbox` 与 `permissions` 各自 `addSettingsSection` 已实测注册 | — |

## B. 产品装配（C0 独占 `products/**`）

- `products/server`：默认组合需显式启用 `PermissionsBackendPlugin`、`PolicyAdaptersPlugin`、`SandboxBackendServerPlugin`、`SandboxAdaptersServerPlugin`（可选域，缺插件时按各包语义工作）。当前本线未写产品装配。
- `products/desktop/extensions.json`：未加入 `ordessa.permissions-chat`、sandbox settings 扩展 ID；加入后才有真实浏览器组合证据（本线只有 jsdom 级证据）。
- `apps/desktop/tsconfig.json` 的测试通配为 `plugins/*/*/tests`，覆盖不到四层路径 `plugins/assets/sandbox/frontend/tests`（`plugins/permissions/frontend/tests` 同样问题）。src 已被覆盖，因此根 `npm run typecheck` 通过；若需要根测试聚合，请由 C0 扩一条 glob，而不是本线改宿主配置。

## C. 根锁与生成物

- 本树运行过 `npm ci`（根 `package-lock.json` 未被本线改写；`npm ls` 会显示两个新 workspace 在下次根安装前为 UNMET）。
- 最终根锁仅由 C0 生成并提交。本线验证时 `docs/ui-preview/*.png` 被 `npm test` 重新生成，已 `git checkout --` 还原，未提交。

## D. 跨域组合门（须由 C0 集成树证明，本线不能自证）

`docs/design/safety-controls/verification.md` 门 3：Permissions 的原生权限投影与 Sandbox 原生配置 facet 若声明同一 native field，必须组合期拒绝。
本线在**各自包内**用真实 `harness.configuration-adapters` 点 + 本地 stub facet 证明了平台会拒（异常 `HarnessContributionError`「native field claims overlap」，两种注册顺序都拒且两者都不 admitted）。
但“两个真实 facet 相遇”的联合证明必须把两域装进同一 registry：为避免任一域测试变成另一域的硬依赖（门 2：互不要求安装），本线刻意不 import 对方包。请在 C0 集成树补一条联合测试，实测 claude `permissions.ask/deny` 与 codex `sandbox_mode/sandbox_workspace_write` 的 claim 集是否相交。

## E. 回退 profile-api 的精确原因（请 Z1/C0 处理）

`4943628f47`（`codex/011-profile-api-ready`）的 `plugins/profile/src/ordessa_profile/plugin.py:17` 仍 `from pacthold.resource_contracts import AgentBoxProfileV1`，而 foundation 已把该模块迁到 `plugins/runtime-compat/src/pacthold_runtime_compat/resource_contracts/`（`git ls-tree` 两侧可见）。merge 后 `import ordessa_profile` 直接 `ImportError`，且本线不得修改 Z1 的业务包，故回退消费。
需要 Z1 出 `profile-api-r2`（改 import 到 `pacthold_runtime_compat`，或消费 `ordessa_server_product.composition.ServerProductComposition.database_type()` 这类公开访问器——本线 `plugins/permissions/backend/tests/support.py` 用了后者并通过）。

## F. 本线请求仍未兑现的公共接缝（见 api-requests.md）

G1 pre-effect 授权门（harness 在工具副作用前调用 `permissions.authorizer@1`）；G2 native receipt 回传；G3 `harness-api` 检查点发布后绑定 C3 `SetField/ResetField`（本线 `sandbox/adapters/seam.py` 保持显式 unbound 并断言无 `SetField` 泄漏）；G4 Profile facet。

## G. 平台侧观察（非本线写入面）

- 全仓测试模块名仍有唯一一处重复：`packages/pacthold/tests/test_brand_rename.py` 与 `plugins/runtime-compat/tests/test_brand_rename.py`。两域各自目录内跑 pytest 不受影响，但 `pytest packages apps plugins` 这类整仓聚合会 `import file mismatch` 中断。归属 C0（两文件都不是本线所有）。本线六个 Python 包已保证全仓唯一 basename（`find … | uniq -d` 只剩上面这一对）。
- `npm test` 会重写 `docs/ui-preview/*.png`；本线每次验证后 `git checkout --` 还原、不提交。请 C0 决定该生成物是否该进聚合门。
- 本线两个前端包的测试目录在 `apps/desktop/tsconfig.json` 的 `plugins/*/*/tests` 通配之外（四层路径），根 typecheck 只覆盖其 `src`。需要根聚合覆盖测试时由 C0 扩 glob。
