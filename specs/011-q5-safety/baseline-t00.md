# T00 — 冻结基线与盘点（Q5，2026-09-28）

## 起点
- 工作树：`/home/maoqh/projects/ordessa/worktrees/011-q5-safety`，分支 `codex/011-q5-safety`。
- 起点 SHA：`96fef2db47f485091ccaadda96f5321400b249f2`（= `refs/heads/codex/011-plugin-plan`，工作树 clean，`git status --porcelain` 0 行）。
- 环境：`python3.12 -m venv .venv`，`pip install -r apps/server/lockfiles/server-linux-py312.txt`，
  editable 安装 `packages/pacthold`、`apps/server`、`plugins/harness[dev]`、`apps/server[dev]`、`packages/pacthold[dev]`（本树独立 venv，未复用其他树）。
- 基线红账本（继承，非本线造成）：`docs/baseline.md` §Suite expectations —
  pacthold 全绿；`plugins/harness` 2 个继承 npm-closure 红；`apps/server` 59 同 ID 继承红 + 6 裁定范围红
  （逐项见 `docs/known-issues.md`、`docs/migration/backend-build-test.md`）。本线完成后逐 ID 复算，不用总数对比。

## 检查点消费状态（实测）
- `specs/011-plugin-rollout/checkpoints/` **目录不存在**：`ls` 退出码 2（No such file or directory）。
- `git for-each-ref` 无 `codex/011-foundation-ready`、`-harness-api-ready`、`-profile-api-ready`、`-chat-api-ready`。
- 因此本轮 **无可消费检查点**；依赖型生产验收（T03 真实 pre-effect gate、T05 原生配置写入回路、T06 Profile/Chat
  注册、T07/T08 接线）按 [checkpoints 协议](../011-plugin-rollout/contracts/checkpoints.md) 保持 blocked，
  本线先做纯域/独立条目，接缝缺口登记在 [api-requests.md](api-requests.md)。
- 只读观察到 C0 分支 `codex/011-c0-foundation-harness` 上有提交
  `b5dcf84703bd85ac001ca4abb48695071df4b304` “add independent typed configuration API package”
  （`plugins/harness/api/`，包名 `ordessa_harness_api`，导出 `SetField/ResetField/InvokeAction/MountContent`、
  `ConfigurationAdapter`、`FieldClaim`、`Assessment/Verification`、`TargetHandle` 等）。
  **它是未发布分支提交，不是 READY 检查点**：本线不把它当已验收契约消费，也不复制其类型；
  待 C0 发布 `harness-api` 检查点后按固定 publication SHA 正常 merge 再接线。

## 平台真实接缝（存在 / 不存在，附位置）
| 设计要求 | 现状 | 证据位置 |
| --- | --- | --- |
| 插件公开注册面 | 存在：`ServerPluginDescriptor/Registration/Context`、`ServerMethodDescriptor`、`HttpRouteDescriptor`、`StreamRouteDescriptor`、`provided_ports`、`start_hooks`、`disposal` | `packages/server-plugin-api/src/server_plugin_api/contract.py:21,56,94,123,163,186,216` |
| 组合期冲突拒绝 | 存在：`DuplicateMethodError`、`PortConflictError`、`DependentActiveError` 等 | `packages/server_plugin_api/errors.py:33,120,134` |
| `Contribution` / `FacetDescriptor` / C1–C4 注册点 | **不存在**（全仓 grep 仅命中 `docs/design/*`、`specs/*` 文档） | — |
| Harness 封闭配置意图（C3） | 本树 main 快照 **不存在**；仅未发布 C0 分支提交（见上） | `git show b5dcf84703` |
| 工具副作用前授权钩子（pre-effect gate） | **不存在**（grep `pre-effect/EffectGate/before_tool` 只命中文档） | — |
| ACP `session/request_permission` 通道 owner | Go 桥存在：`plugins/harness/adapters/acp-adapter/pkg/{piacp,codexacp}/{runtime.go,embedded.go}`（`PermissionDecision`、`RespondPermission`、profile 的 `ApprovalPolicy`/`Sandbox` 字段）；Python 侧无处理器，`harnesses.toml` 仅 pi 声明 `permissions` capability | `pkg/piacp/embedded.go:39,199`、`pkg/codexacp/embedded.go:39,201`、`plugins/harness/.../harnesses.toml:13,31,248` |
| 审批唯一权威（旧） | 存在：`ApprovalRecords`（表 `server_approvals`，OPEN/SETTLED/INVALID，CAS + `decideRequestId` 幂等 + `approval.requested/settled` 事件、`invalidate_for_execution`） | `plugins/server-compat/src/ordessa_server_compat/approvals/records.py:25,70,146` |
| 旧规则引擎（last-match-wins） | 存在：`TOOL_KEYS` 封闭集、`resolve`（后匹配覆盖前 deny） | `.../profiles/permissions.py:34,139` |
| 品牌投影 | 存在：`translate_claude`/`translate_codex`、`render_claude_settings`、`_CLAUDE_WRITABLE_PATHS`、`_SANDBOX_STRICTNESS` | `.../profiles/posture_translation.py:53,95,131`、`posture_config.py:39,70,77` |
| Profile/Chat 插件包 | **不存在**：`plugins/` 实测只有 agent、commands、connections、connectors、harness、server-compat、workbench、workspace | `ls plugins/` |
| Settings 分区贡献（桌面） | 存在：`WorkbenchComposition.forScope(...).addSettingsSection` | `packages/desktop-platform/contracts/workbench/src/workbench.ts:37` |
| 中性 `SandboxV1` | 存在且**不得复用**为本域实现：`SandboxPort`/`SandboxV1`/`RoomInvariants` | `packages/pacthold/.../runtime_composition/sandbox_port.py`、`protocol.py:45` |
| 依赖方向边界门 | 存在：`apps/server/tests/test_s_mb_sessions_boundary.py`、`test_e_modular_execution_boundary.py` 等 | — |

## 旧实现红/绿起点（本线必须先红的格）
- T01：`profiles/permissions.py:139 resolve()` 实测 last-match-wins → 低优先级 allow 覆盖高优先级 deny。新合成引擎的反例
  （`test_ceiling_deny_cannot_be_widened_by_intent_allow`）在该旧实现上必红。
- T02：`ApprovalRecords.decide` 无 native receipt / 无失联对账查询（`grep nativeRequestId records.py` 0 命中）→
  双权威并存与 receipt 反例先红。
- T04/T05：本树无任何原生 sandbox schema/coverage 类型（`grep -i "NativeSandbox\|requiredCoverage" plugins/` 0 命中）→ 新模块按先红后绿。
- 证据位置随提交记录在 [report.md](report.md)。

## 消费检查点后的基线重算（2026-09-28，追加）

上节冻结的是 `96fef2db47` 起点。本线随后消费了 `foundation` `8844c475bc`（merge `52906b514d`）与 `chat-api` r3 `3d8c3fa410`（merge `7b4de06148`），因此继承红账本必须重算，旧数字不再适用：

| 套件 | 起点基线（96fef2db47） | 消费 foundation 后 | 本线最终复跑 |
| --- | --- | --- | --- |
| `packages/pacthold` | 238 passed | 212 passed（测试随 compat 拆分） | 212 passed，exit 0 |
| `plugins/harness` | 2 failed / 308 passed / 3 skipped | 2 failed / 347 passed / 3 skipped | 同一对 ID，exit 1 |
| `apps/server` | 43 failed / 850 passed / 25 errors | 42 failed / 1092 passed / 25 errors（67 个继承红 ID，foundation 记录一致） | 42 FAILED ID 与消费后账本 `diff` 为空；25 ERROR 仍是同样 5 个文件 |

`profile-api` `4943628f47` 消费后回退（`b4b48d7564`）：其 `ordessa_profile.plugin` 仍 import `pacthold.resource_contracts`，foundation 已迁移该模块，`import ordessa_profile` 直接 ImportError。环境侧需 `pip install -e plugins/runtime-compat`，测试经 `ServerProductComposition().database_type()` 取真实 provider。
