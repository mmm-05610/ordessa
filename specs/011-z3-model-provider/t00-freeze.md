# T00 现状冻结（Z3 — Model-provider v2）

冻结时间：2026-09-28。执行者：Z3 主代理（lead）。本文件只记录实测事实；接缝缺口逐条给
`BLOCKED_INTEGRATION` 归属，不造 stub 假充。

## 1. 树与起点

| 项 | 实测值 |
| --- | --- |
| 本线工作树 | `/home/maoqh/projects/ordessa/worktrees/011-z3-model-provider` |
| 本线分支 | `codex/011-z3-model-provider` |
| 起点提交 | `96fef2db47`（"Prepare Spec Kit plugin rollout for Codex, ZCode and Qoder"） |
| 快照父提交 | main `cd7d31f3cf`（README 冻结口径，本树实测祖先一致） |
| 起点 git status | clean（无未提交文件） |
| 工具链 | Python 3.12.14（`/home/maoqh/.local/bin/python3.12`，baseline 钉版）；Node v22.22.1；本树独立 `.venv` 已建（baseline lockfile + editable `pacthold`/`server-plugin-api`/`apps/server`）；根 `npm ci` 277 packages（frozen lock，未改 lock） |

## 2. 只读输入树

| 树 | 提交 | 状态 | 用途 |
| --- | --- | --- | --- |
| `plugin-model-provider-impl` | `9305563719d25e04076b9221a7284660bd8f8642` | clean | 旧实现移植源（PARTIAL，77 pytest + 10+8 vitest） |
| `model-provider-spec` | `4346da2ce4` | clean | 旧产品设计（R1 已被新裁决修订） |

后续新提交不自动成为输入；如需追加必须记录新 SHA。

## 3. 上游真实导出核对（设计稿 vs 本树事实）

| 设计稿接缝 | 本树实测（`96fef2db47`） | 结论 |
| --- | --- | --- |
| Harness C2 `harness.configuration-adapters` v1 | `plugins/harness/src/ordessa_harness/` 无该注册点；`native_materialization.py` 仍含品牌渲染（待 C2 所有权转移） | **BLOCKED_INTEGRATION → C0/harness-api**。本域 adapter 按 C2 目标语义先写（E1），真实注册等 harness-api |
| Harness C4 `harness.configuration` plan/apply/verify + C5 submit permit | 不存在 | **BLOCKED_INTEGRATION → C0/harness-api**。T05 的 submit 闸门先以冻结端口协议 + E1 假闸门驱动，生产接线等真实发布 |
| Profile facet 注册口（`ProfileContributions.addEditor` 等） | `docs/design/profile-v2/contracts.md` 为目标稿；main 无实现 | **BLOCKED_INTEGRATION → Z1/profile-api**。T04 facet/ReferencePort 先按旧包端口协议 + E1 |
| Chat `ChatContributionsToken` `composer.footer` | 不存在（`packages/desktop-platform/contracts/agent` 只有 AgentClient/Sessions 面） | **BLOCKED_INTEGRATION → Z2/chat-api**。T05 选择器先按旧包冻结 stub 形状（consumer 侧测试），真实接线等发布 |
| Workbench `addSettingsSection`（composition） | **已存在**：`packages/desktop-platform/contracts/workbench/src/workbench.ts` + `plugins/workbench/src/model.ts` 实现 `WorkbenchComposition` | 真实面可用，T03 直接消费，不再用 stub |
| 检查点引用 | `refs/heads/codex/011-{foundation,harness-api,profile-api,chat-api}-ready` 全部**不存在**（2026-09-28 实测） | 按协议先独立工作；发布后按固定 SHA 消费 |

## 4. wire 形状 / DB 标识（冻结事实）

- 六方法：`providerModels.list/create/update/archive/probeModels/probeConnection`；参数形状 =
  server-compat `core_wire.py` `_PARAM_SHAPES:238-276`；handler 映射 `_COMPAT_METHODS:339-365`。
- 表标识 `SLOT_TABLE = "providerModels"`；`opaque_id("provider")` 旧 provider ID 沿用。
- 错误码/投影字段冻结表：旧包 `specs/002-model-provider/contracts/backend-wire.md`（与 compat 逐项对齐，
  旧 `test_plugin_registration.py` 为形状门）。
- 双 owner 门：宿主 `apps/server/src/ordessa_server/plugin_host/host.py` `DuplicateMethodError`。
- 宿主端口名（六个）：`database`、`objects`、`notifier`、`idempotency`、`credentials`、`secret_store`（可缺席）。

## 5. 品牌版本与许可（T02 输入口径）

| 品牌 | harness_id | 钉版 | 证据入口 | 许可注记 |
| --- | --- | --- | --- | --- |
| Pi | `pi` | `@automatalabs/pi-acp@0.5.0` + `@agentclientprotocol/sdk@1.3.0` | `plugins/harness/packaging/pi/package.json`；官方文档 @ pi `2b0a123d` | MIT（packaging 根声明）；本包不复制其源码 |
| Codex | `codex` | `@agentclientprotocol/codex-acp@1.1.14` | `plugins/harness/packaging/codex/package.json`；官方 config reference | packaging 根声明；项目 `.codex/config.toml` 禁覆 `model_provider*` 键 |
| Claude Code | `claude-code` | `@agentclientprotocol/claude-agent-acp@0.81.2` | `plugins/harness/packaging/claude/package.json`；仓内 `provider-session.test.mjs`/`provider-routing-smoke.mjs` 已有 E2 局部（假端点 A/B 隔离 + resume） | Anthropic 专有 SDK 条款由 packaging 链承载；本包不复制源码 |

## 6. 旧 R1 → 新 restart-resume 差异表

| 维度 | 旧 R1（model-provider-spec @ 4346da2） | 新裁决（本包 spec.md） | 实现影响 |
| --- | --- | --- | --- |
| 应用失败处置 | 不可安全应用即拒绝，不重启 | 先按 C2 评估 session-local/reload/restart-resume；有同 session resume + 隔离/readback 证据才允许受控重启 | adapter assess 输出四值路径；Harness restart 事务归 C0 执行，本域声明语义 |
| 恢复身份 | 不适用 | 必须恢复**同一原生会话**；`session/new` 冒充恢复禁止；无法证明 resume 仍拒绝 | verify/readback 绑 native session id；反例：new-session 冒充必红 |
| 输出中切换 | 当前输出不中断（不变） | 不变 | pending-next-turn 语义沿用 |
| 拒绝回退 | 禁止退回旧 endpoint（不变） | 不变；拒绝不得暗发默认模型 | 状态机沿用旧 next_turn.py |

## 7. 旧实现盘点（移植来源，逐文件来源 SHA=9305563）

| 旧路径 | 处置 | 目标 |
| --- | --- | --- |
| `plugins/model-provider/src/ordessa_model_provider/{records,protocols,probe,catalog,next_turn,ports,plugin,testing}.py` | 移植 + 按新裁决增量 | `plugins/assets/model-provider/src/ordessa_model_provider/` |
| `plugins/model-provider/tests/*.py`（10 文件，77 例） | 移植 + 新增反例 | `plugins/assets/model-provider/tests/` |
| `plugins/model-provider/desktop/**`（10 vitest） | 移植；alias 路径按新深度修正；token 从固定值改为沿用平台已审 token | `plugins/assets/model-provider/desktop/` |
| `plugins/model-provider/chat-contribution/**`（8 vitest） | 移植；stub 标注 E1、真实接线登记 api-request | `plugins/assets/model-provider/chat-contribution/` |
| `plugins/model-provider/profile-contribution/**` | 移植；facet 注册按目标稿 + E1 | `plugins/assets/model-provider/profile-contribution/` |
| `plugins/model-provider/contracts/*.ts` | 移植 | `plugins/assets/model-provider/contracts/` |
| `plugins/server-compat/.../model_configs/**` | 行为 oracle（只读对照），不 import | 迁移比对门 |
| `plugins/harness/packaging/claude/provider-*.mjs` | 借鉴受控假端点证据模式 | T02/T06 E2 设计参考 |

旧 DELIVERY 明确 PARTIAL 项中，属本线的：#2 真实 ACP seam、#5 Chat/Profile 真实契约、#6 桌面 wire 传输口、
#7 TurnFact/引用重绑 —— 全部转 api-requests；#1 compat 退出、#8 产品装配归 C0 集成（integration-request.md）；
#3/#4（E2 三品牌、E3 真实模型）按检查点协议处理，E3 本轮无授权不跑。

## 8. 新增 wire 方法命名冻结（contracts.md「例如」名的 T00 裁定）

设计稿给出示例名 `modelProvider.catalogue/inspectChoice/chooseForSession/queryChoice/reconcileChoice`。
save/probe 属 ProviderCatalogPort 但示例未覆盖；为避免歧义冻结为（与旧 `providerModels.*` 无冲突）：

| method_id | 端口语义 |
| --- | --- |
| `modelProvider.catalogue` | ProviderCatalogPort.list(target, cursor) |
| `modelProvider.saveProviderConfig` | save(patch, expectedVersion, operationKey) |
| `modelProvider.probeProvider` | probe(configRef, expectedVersion, operationKey) |
| `modelProvider.inspectChoice` | inspectChoice(target, choice) → supported/unsupported/unknown |
| `modelProvider.chooseForSession` | queue(target, choice, expectedOverlayRevision, operationKey) |
| `modelProvider.queryChoice` | ModelChoicePort.inspect(target) |
| `modelProvider.reconcileChoice` | reconcile(operationId) |

## 9. 环境事实

- 本树 venv：`.venv`（Python 3.12.14）。导入验证 `pacthold`/`ordessa_server`/`server_plugin_api` ok。
- npm：frozen lock 安装 277 packages；本线不修改根 `package-lock.json`（TS 测试经根 hoisted vitest/react 运行）。
- 严禁真实模型调用（E3 无授权）；probe 一律本地假端点/受控反例。
