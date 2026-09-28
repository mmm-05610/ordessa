# P-B 简报 — model-provider 真实应用链（三品牌）

**工作目录**: `worktrees/014-b-model-provider`（分支 `codex/014-b-model-provider`，基线 = main 491aa92392 + merge `codex/plugin-model-provider`，已就位）

**必读输入**（按序）: 本目录 [spec.md](../spec.md)（US2/US5）、[plan.md](../plan.md)（事实 F2/F5/F6、纪律）、[seams.md](../seams.md)、`specs/011-z3-model-provider/report.md` + `docs/design/model-provider/verification.md`（E 级定义：E1 不得报成 E2）、`plugins/assets/model-provider/MIGRATION.md`（在树内）、`docs/baseline.md`、根 `AGENTS.md`。

**目标一句话**: 把 Z3 的"形状正确但全是受控假件"的应用链接到 main 上**已存在的真实目标面**（C2 注册点、C4 服务+permit），自发布 wire error families，交付三品牌 E2 受控矩阵；Profile glue 消费 P-A 的 r2 SHA。

**首要认知（F2）**: api-requests.md 的冻结文本已过时——REQ-Z3-1/2 的目标面已在 main：
- C2 注册点：`plugins/harness/src/ordessa_harness/contributions.py:21` `CONFIGURATION_POINT = "harness.configuration-adapters"`，重复 adapter_id 拒绝 :187-190；类型 `plugins/harness/api/src/ordessa_harness_api/contracts.py`（ConfigurationAdapter/Descriptor/AdapterContext/Assessment/Match/Mismatch/VerificationUnknown）+ `intents.py`。
- C4：`plugins/harness/src/ordessa_harness/application/configuration_service.py:150` `ConfigurationApplicationService`（apply(plan_id, operation_key, submission_permit)；ctor 强制注入 permits/journal，无默认 permit）；permit 机制 `apps/server/src/ordessa_server/acp_admission.py:94-140`（volatile fence、AUTHORIZATION_REFUSED）。
- error families：`packages/server-plugin-api/src/server_plugin_api/contributions.py:74` `WIRE_ERROR_FAMILIES_POINT_ID`，插件可自贡献（REQ-Z3-7 由本包自己解决，不走接缝）。
**以树内实测符号为准，api-requests 文本只当历史背景。**

## 写入面（只许这些）

`plugins/assets/model-provider/**`；`specs/011-z3-model-provider/**`（报告增补）；`specs/014-plugin-release/**`（勾选 PB-*、写 `reports/P-B-report.md`、更新 S-03/S-06/S-08/S-11 状态）。

**禁区**: `plugins/harness/**`（只读消费）、`plugins/server-compat/**`（退役归 S-08）、其他 plugins/、products/、tooling/、packages/、apps/、根锁、兄弟树、`plugins/profile/**`（glue 只消费不写）。确需变更 harness-api → 停该项写接缝。

## 任务（详账 tasks.md PB-1..PB-8）

### PB-1 R0 基线重建（合并后第一件事）
旧分支基线缺 main 的 harness-api/chat 内容，**所有旧计数作废重测**：Python（server/adapters/profile-contribution 三组）、desktop vitest、chat vitest（旧分支 alias 不解析的问题在新基线应消失——验证之）、contracts tsc。冻结安装命令（各子包 `-e`，登记 S-10）；回填消费 SHA（foundation/chat-api 经 main 的哪些提交，用 ancestry 实证）。S-11 **已确认**（core 答复 2026-09-28）：`packages/desktop-platform/server-bridge/src/wire-port.ts` 的 `HttpWirePort` 已交付（含测试），宿主接线归 core INT-01——R0 直接消费 `HttpWirePort` 类型，验收口径写「接口与实现已交付、生产绑定在 INT-01」。

### PB-2 C2 注册落地
adapters `{pi,codex,claude}.py` 的 `registration_manifest()` 从"本地 typed 面"（types.py 自写）对齐到 harness-api 真实类型（必要时装一个薄适配层，方向：adapters→harness-api，禁止反向）；注册**只经本包自己的声明面**（本包插件 entry/贡献 manifest，在 `plugins/assets/model-provider/**` 内）进 `CONFIGURATION_POINT`——**不动 products/server 组合**（装配归 core S-03，且须在 S-08① 退役之后）；复验真实 registry：重叠注册拒（:187-190）、第二 client 必红（MP-11 生产格）。conformance 门（`adapters/tests/test_adapters_conformance.py:80-103`）保持绿。

### PB-3 C4 绑定与 submit permit（MP-05 真实生产闸门）
`server/src/ordessa_model_provider/ports.py:76-110` `HarnessConfigPort` 的 apply/read_back 从 `testing.py FakeHarnesses` 换绑 `ConfigurationApplicationService`：plan→apply(plan_id, operation_key, submission_permit)→verify→read_back 全链；一次性 permit 的重放/换目标/过期必红；**无 permit 裸 apply 必红**。admission `ready=False` 未翻转（S-06）前，生产环境路径必须诚实 refused/unknown——在测试里以受控 permit 走通，在报告里区分"受控级全绿 / 生产级待 S-06"。

### PB-4 wire error families
13 个业务码（api-requests.md:80-85 清单）经 `wire.error-families` 自发布；反例：与既有族冲突拒批、未知码不落 UNAVAILABLE 冒充。

### PB-5 三品牌 E2 受控矩阵（DONE 的必要条件）
行 = pi / codex / claude-code；列 = MP-03 目录事实 / MP-06 restart-resume / MP-07 失败不撒谎 / MP-10 秘密哨兵 / MP-11 C2 单 owner。证据要求（verification.md E2）：`initialize→session/new→prompt(fake endpoint)→换 choice→必要时 resume(同 native id)→下一 prompt`，双会话交错，验证**下游实际路由**（配置文件/option ack 不算）。品牌语义钉（conformance 已锁，勿漂）：codex 永不写 project-scope provider、provider 级变更 restart-resume 同 thread、model-only 变更 session-local；pi RPC 成功≠effect 证据；claude model 与 endpoint 两件事、session/new 冒充 resume=Mismatch。**缺格 = 该品牌不得报 ready，整体 PARTIAL**。真实模型调用（E3）禁跑。

### PB-6 Profile glue（弱依赖 P-A）
消费 P-A 交付的 profile-api r2 SHA（merge A 分支或按 SHA cherry-pick，记 ancestry）；`profile-contribution/` 的 `EffectiveChoiceResolver`/视图端口接真实 ProfileContributions（REQ-Z3-3）。A 未交付期间：fixture 先行 + report 登记依赖；**不得**写 plugins/profile。

### PB-7 退役准备与金样（S-08①②；只出清单与顺序，不执行删除）
1. adapters `common.py` golden 渲染与 harness 侧（`native_materialization.py:114-145`）一致性钉死（conformance 已有，保持并扩到注册路径）——S-08② 的承接方证据。
2. server-compat `model_configs` writer（`core_wire.py:238-276`）逐行退役清单 + 消费者核查 + "先退 compat 再装配"顺序确认，写回 seams S-08①；server-compat 文件的实际删除（含 profile 的 `server_profiles`，代 A 执行）归**集成波次**，本包不动 server-compat/harness 源文件。

## 门与反例（终态前必须全过）

| 门 | 断言 | 反例 |
| --- | --- | --- |
| 注册 | 三品牌注册进真实点；重叠必拒 | 只在本地 registry 测过 ≠ 绿 |
| permit | 无 permit 必拒；重放必拒 | apply 成功但 permit 路径未走 = 假绿 |
| E2 矩阵 | 逐格证据 + 下游路由证明 | 缺格报 ready = 禁止；E1 报成 E2 = 禁止 |
| 品牌语义 | 三品牌 dialect 钉不漂移 | golden 漂移未解释 = 红 |
| 回归 | R0 重测基线全绿不回退 | 继承红新增未登记 = 不许收口 |
| 诚实 | 生产级 vs 受控级分开陈述 | 混写 = 假绿 |

## DoD

实现 + 门 + `reports/P-B-report.md`（R0 重测计数、消费 SHA、E2 矩阵逐格、缺口与 S 单回填）+ 011-z3 report 增补 + tasks.md PB-* 勾选一致。git：本分支正常提交，不 push 不外并；子代理规矩同 P-A。
