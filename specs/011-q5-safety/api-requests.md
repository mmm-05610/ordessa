# Q5 接缝请求登记（2026-09-28）

消费者：Q5（`plugins/permissions/**`、`plugins/assets/sandbox/**`）。每条给出调用者、目标操作、所需 DTO、失败反例与请求 owner。
兄弟线可 `git show refs/heads/codex/011-q5-safety:specs/011-q5-safety/api-requests.md` 读取。

## G1 — 工具副作用前授权门（owner: C0，检查点 `harness-api`/`foundation`）
- 调用者：`permissions.authorizer@1`（`plugins/permissions/backend`，`evaluate(...)`）。
- 需要：Harness/ACP 通道在**任何原生工具产生副作用之前**同步调用后端 authorizer，并能把
  `Denied(code,evidenceRef)` 变成“未执行”的可观察事实；需要中性注册点（不是新 wire 方法供桌面自调），
  以及一个非权限业务（如 MCP 目录）复用同一接缝以证明通用性。
- DTO：`evaluate(principal, sessionRef, executionRef, nativeGeneration, toolIdentity, targetFacts,
  argumentDigest, ceilingRevision, policyRevision, nativeRequestId)`。
- 现状证据：本树 grep `pre-effect|EffectGate|before_tool` 只命中 `docs/design/safety-controls`、`specs/011-q5-safety`；
  Python 侧 `plugins/harness` 无 `request_permission` 处理器（`harnesses.toml:13` 仅 pi 声明 `permissions` capability）。
- 反例（接线后必须先红）：authorizer 缺席/抛错/超时时工具仍执行 → 要求零副作用。
- 未就绪时本线做法：纯域 authorizer 服务与 L1 反例照常交付；依赖真实执行门的生产验收（T03 受控 gate、T07）标 blocked，不勾完成。

## G2 — ACP 审批关联与 native receipt / 失联对账（owner: C0）
- 调用者：`ApprovalFacts.query/reconcile(approvalId, nativeRequestId)`。
- 需要：现有 `session/request_permission` 通道（`pkg/piacp/embedded.go:199`、`pkg/codexacp/embedded.go:201` 的
  `RespondPermission`）向服务端回传 native request 关联与接收回执，且允许“结果未知”态。
- 现状证据：`grep nativeRequestId plugins/server-compat/src/ordessa_server_compat/approvals/records.py` 0 命中。
- 反例：响应丢失后重放不得二次副作用；native owner 未确认前不得宣告“已获执行”。

## G3 — Harness C3 封闭意图与 C2 字段 claim（owner: C0，检查点 `harness-api`）
- 调用者：`sandbox.native-configuration@1` adapters 的 `compilePolicy`/`compile` 输出。
- 需要：已发布（非分支提交）的 `ordessa_harness_api`，含 `SetField/ResetField/InvokeAction`、`TargetHandle`、
  `FieldClaim` 冲突门、`Assessment/Verification` 语义。
- 现状：`b5dcf84703` 在 `codex/011-c0-foundation-harness` 分支上，尚无 `specs/011-plugin-rollout/checkpoints/harness-api.json`。
- 本线做法：sandbox 域先交付自有意图 DTO schema 与 coverage/平台校验（纯域）；真实写入/回读/行为探针（T05 L2）等固定 SHA 接线。

## G4 — Profile Facet / Settings 公开贡献点（owner: Z1，检查点 `profile-api`）
- 调用者：两域的 `permissions.profile-glue` / `sandbox.profile-glue`。
- 需要：真实可导入的 Profile `FacetDescriptor`/`addEditor` 与“只存 ID+revision、不可提升上限”的语义；
  桌面 `addSettingsSection` 已存在（`packages/desktop-platform/contracts/workbench/src/workbench.ts:37`）。
- 现状：`plugins/profile/**` 不存在；`grep -rn "FacetDescriptor\|addEditor" --include=*.py --include=*.ts .` 只命中设计文档。
- 反例：Profile 贡献把 intent 当 ceiling 提升 → 拒绝。

## G5 — Chat 审批区贡献（owner: Z2，检查点 `chat-api`）
- 调用者：Permissions 的受限审批卡贡献（`approvalId`/`version` 绑定、失效即不可操作）。
- 现状：`plugins/chat/**` 不存在。
- 要求：Chat 不得 import 权限内部服务，不得由 UI 构造权威 allow；headless 路径仍走后端 fail-closed（本线已以纯后端测试证明该语义）。

## G6 — 旧权威退出与 compat 删除（owner: C0，见 integration-request.md）
- `ordessa_server_compat/approvals/records.py` 唯一权威迁入 Permissions 后，`approvals.decide` 路由与 `server_approvals`
  数据 ID 保持，旧 writer 退出由 C0 完成；本线不提交 shared compat 删除。

## 消费后状态更正（2026-09-28，追加不覆写原文）

原文按 `96fef2db47` 冻结时点书写，消费检查点后以下事实变化，逐条按现状更正：

- **G3（Harness C3 意图词汇）**：消费 `foundation`（publication `8844c475bc`，merge `52906b514d`）后，`plugins/harness/api`（`ordessa_harness_api`）在本树磁盘上存在且可导入，但 `specs/011-plugin-rollout/checkpoints/foundation.json` 的 publicExports **未列**该包，且 `refs/heads/codex/011-harness-api-ready` 不存在（`git show` 报“无效的对象名”）。因此 sandbox 的 C3 绑定仍按未发布处理：`plugins/assets/sandbox/adapters/seam.py` 的 `to_harness_c3()` 保持显式 `HarnessContractUnavailable`，并有测试断言无真实 `SetField` 泄漏。裁定证据与理由写在 `specs/011-plugin-rollout/checkpoints/permissions-api-r2.json`。
- **G5（Chat 审批区）**：原文“`plugins/chat/**` 不存在”在冻结时点为真。消费 `chat-api` r3（publication `3d8c3fa410`，merge `7b4de06148`）后 `plugins/chat/api` 存在且是本线真实消费点，本线已用其 `chatContribution()`/`createChatContributions()`/`ChatScopedAction` 注册受限审批区（`plugins/permissions/frontend`，28 tests）。
- **G4（Profile facet）**：`profile-api` publication `4943628f47` 消费后必须回退（revert `b4b48d7564`），因 `plugins/profile/src/ordessa_profile/plugin.py:17` 仍从 `pacthold.resource_contracts` 取 `AgentBoxProfileV1`，而 foundation 已把该模块迁到 `pacthold_runtime_compat`。本树现状：**无 `FacetDescriptor` 可消费**，两域 Profile glue 仍 blocked。请求 Z1 出兼容修订版（细节见 `integration-request.md` §E）。
- **G1/G2 复核（不是沿用旧结论）**：消费 foundation 后重新在本树 grep，平台仍无执行前授权门与 native 回执回传（`ordessa_harness.contributions` 只暴露 `harness.runtime-adapters` / `harness.configuration-adapters` 两点）。G1/G2 保持 blocked 的判断依据的是当前树，而非冻结时点。
## G1/G2/G3 复判（消费 harness-api `d3f026904ead6c7ce58df26f2536175ce6179de7` 后）

- **G3**：已兑现并消费——sandbox 侧 C3 意图绑定完成，缺席 tripwire 改为在场断言。
- **G1**：中立 port `acp.admission.gate` 与其 DTO 已发布，本线交付 Q5 侧适配与反例（`plugins/permissions/backend/src/ordessa_permissions_backend/admission.py`）。剩余缺口是「产品/宿主把该 port 的 authority 装成 Q5 authorizer 并让真实工具副作用经它」，owner 仍 C0；harness-api 记录原文即「ready=False、Q5 authorizer、one-use execution permit、native runtime generation and production pre-effect path are not wired」「controlled fixture acceptance is not production G18/G19」。
- **G2**：operation-bound native receipt 与实例 generation 的真实来源仍缺席（记录原文），本线 `reconcile` 保持 Unknown=不放行，未当作已解决。
- **G4**：`profile-api` 与 foundation 不兼容（`pacthold.resource_contracts` 已迁至 `pacthold_runtime_compat`），未复消费，Profile facet 仍 blocked。

## 给 C0 的回执（2026-09-28，对应你 `4396338d79`/`0d93b1aee8` 的 Q5 条目）

- 中立 port 已发布：`ordessa_permissions_api.PermissionsAuthorizerPort` + `PERMISSIONS_AUTHORIZER_PORT`/`_VERSION`，Harness 可只依赖 API 包，不必 import 后端或猜签名。
- `busy()` 已绑宿主停用；产品激活本 backend 前无需再做临时兜底。
- 旧 `approvals.decide` 的单一 authorizer 委托已可用且默认关闭（`approval_route="legacy-delegated"`）；退役旧 writer 的动作仍在 C0 手上，本线不碰 `plugins/server-compat`。
- `adapter_versions` 两侧均已收紧为精确 (0,1,0) 并各由本包发布事实支撑；**未**为过测放宽。你要求的「per-publication 独立观测 adapter 版本」契约仍未存在：本树 `RuntimeAdapter.describe_installation()` 无生产实现者，故真实两 facet plan 仍是 `ADAPTER_MISSING`，本线以测试钉住该拒绝。需要 C0 提供：生产 installation 观测者 + C4 per-fragment facet 选择（`plugin_host/contribution_points.py:150-162` 的 `AbsentContribution` 路径）。
- 你已修的同名文件（`contribution.py`/`points.py` docstring/import 区）与本线新增证据注释会小范围文本冲突，合并时保留双方语义即可。

## G7 — 让插件能充当提交侧 ACP authority（owner: C0，来源：本线 T021 实测）

- 调用者：`plugins/permissions/backend/src/ordessa_permissions_backend/host_authority.py`（已实现权限侧；提交侧只能显式拒 `CAPABILITY_UNSUPPORTED`）。
- 需要：把提交许可的记录类型与规范化从中性契约暴露，使插件不必 import 宿主内部即可返回它。具体缺口（file:line 均在本树）：
  - `apps/server/src/ordessa_server/acp_admission.py:27-36` 的 `BoundAdmission` 与 `:63-90` 的 permit 规范化/摘要是宿主私有，`:134` 又对 authority 返回值做 `isinstance(bound, BoundAdmission)` 检查；
  - `:21` 的 `AcpAdmissionRefused` 是唯一能被 `AcpAdmissionPortAdapter`（`:383-387`）保留为稳定码的异常，插件异常会被折叠成 `unknown`。
- 请求形式（任一即可，不要求宿主为本线开特例）：在 `server_plugin_api` 发布 `BoundAdmission`（或等价的中性 permit DTO + 规范化函数），或发布 `AcpAdmissionRefused` 与「authority 可返回的码集合」。
- 失败反例（已就绪，等契约）：本线 `tests/test_host_pre_effect_l2.py` 中的提交侧用例；当前断言的是「无 binder 注入即拒」，若 C0 发布中性类型，这些用例应先红后绿地切换到真实 accepted 路径。
- 另一条同时依赖 C0 的事实：默认产品 `bootstrap/runtime.py:607` 建 gate 时不传 authority、`AcpAdmissionPortAdapter.ready` 恒 False，因此本线 authority 需由产品装配显式启用。
