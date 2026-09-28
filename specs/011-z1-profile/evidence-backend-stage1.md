# Z1 后端阶段 1 证据（evidence-backend-stage1）

执行方式说明：本应由单包实施子代理完成；子代理派发连续三次因平台配额
（exceed quota limit）立即失败，按"普通阻塞自行解决"降级为**主代理直接实施**。
该过程偏差已登记 report.md。所有命令在本树根执行，venv 为本树 `.venv`。

## 命令与退出码（2026-09-28 实测）

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest plugins/profile/tests -q` | **130 passed**（退出码 0） |
| `bash plugins/profile/tests/boundary_check.sh` | OK（0 violations） |
| `bash plugins/profile/tests/run_counterexamples.sh` | OK（**12/12** 注入被门判别） |
| 旧基线对照：隔离检出 b77f9f23cb + 本树 venv pytest | 70 passed（R0 实测，未沿用旧报告） |

## 旧→新测试 ID 对照（v1 语义变更说明）

70 个旧测试全部保真迁移并通过。语义被 v2 设计明确改变的仅以下 6 处，
每处为"拆分存储证据与运行证明"（PV-04/PV-07），未删除任何断言意图：

1. `test_storage.py::test_schema_v1_applied_once` → 改名
   `test_schema_steps_applied_once`：断言从 version=1 升级为逐级 [1,2]、
   reopen 不追加迁移行；新增 v2 三表在表清单断言中。
2. `test_us5_projection.py::test_fr012_…`：EXPECTED_COLUMNS 增加 v2 列/表；
   原"无 permission/credential 列"断言逐列保留并覆盖新表。
3. `test_us2_switch.py::test_us2_4_unprovable_application_marks_needs_recovery`：
   驱动从 verify_hook（DB read-back 证明，v2 已废除）改为端口回答 unknown
   （受控 fixture）。新增断言：journal=unknown、previous binding 未被替换。
4. `test_us2_switch.py::test_sc003` 反例3：同上，端口 unknown 驱动。
5. `test_edge_cases.py::test_edge1_unverifiable_after_restart_blocks_sending`：
   恢复路径从 DB read-back 升级为端口 reconcile confirmed-current；
   断言"reconcile 本身不产生轮次"。
6. `test_us5_projection.py::test_us5_2_needs_recovery_state_is_visible_not_faked`：
   blockers 值 `application_unverifiable` → `application_unproven`（新链路），
   并新增 journal 状态可见断言。

`verify_hook`/`read_back_verify`/`read_back_consistent`（DB read-back 证明）
已从生产代码删除；recovery 只走端口 reconcile（sessions.verify_recovery 返回
requires_port/requires_reconcile，不升级）。

## 新增覆盖 → checklist 映射

| 测试文件 | 覆盖 |
| --- | --- |
| test_contracts.py（10） | PV-03：schema 未知字段/未知类型/enum/边界拒绝；四值状态（UNSET≠null≠[]≠disabled）；Applicability 三值；SessionRef 跨 realm 不相等；ConfigIntent set/reset 互斥（显式 0 是真值）；receipt 拒绝 legacy-unverified；journal 状态校验；公共投影无秘密字段 |
| test_policy.py（6） | G03/G04：默认启用/允许；CAS 冲突+幂等重放；同 key 异 payload 拒绝；禁写后既有 overlay 可见可清；禁用 facet 拒新写、存值保留、清 overlay 可用；impact preview 计数；realm 隔离 |
| test_sessions_v2.py（12） | 端口缺席 typed blocked 且 selection/journal 完整；G20 选择不触端口（plan/apply/inspect/abort/restart=0）；confirmed 走 receipt+清 overlay；G10/G11 commit 注入失败→unknown、reconcile 补 receipt、不重发消息；reconcile rejected-unchanged 恢复旧绑定；G07/G08 apply 拒绝全保留；G08 v2 reset 到端口；G08/G13 缺 provider 阻塞不过滤；G02 双 realm 同 native key 不串写；G16 native key 冲突 plan 前 0 写入；generation 失效；同 Profile 重选不清 overlay |
| test_migration_v2.py（7） | G17：v1 库原位升级（id/修订/存值不动）；两次幂等；legacy settled 投影 legacy-unverified 且永不为 receipt；pending 迁移保留；uid 碰撞拒绝不合并；全新库到 v2；v21 server_profiles 导入语义保持（修订不塌缩） |
| test_v2_extension.py（6） | PV-06 扩展性证明：owner 必须宿主注入；跨 owner 重复 facetId 拒绝；注册→describe→存值→preview→apply 全链；G01 零 facet 管理可用；**核心源码无业务名断言**（acme_widget/model_selection 等不出现在 core 文件）；卸载保留值+重注册 migrate 裁决 |
| test_plugin_registration_v2.py（4） | PV-05：build 带 resource provider 且 discovery 零写盘；agent-box.profile@1 真实 resolve（含 digest/revision）；外来 ref 拒绝；services 门面 policy/describe 可用 |

## 受控 fixture 边界声明

`ScriptedConfigPort` / `ScriptedV2Provider` / `ScriptedProvider` 是受控证据
工具（constitution IV），证据种类显式标为 `controlled-fixture`。它们证明
Profile 侧 journal/fence/unknown/reconcile 逻辑与扩展机制，**不证明任何真实
Harness（Pi/Codex/Claude）的应用行为**。真实端口类型 `HarnessConfigPort` 已
冻结并从 harness-api 消费（见 api-requests.md）；端口缺席行为有专测
（typed blocked，不假绿）。

## v2 设计内行为变更（生产代码）

- 存储迁移 v1→v2：realm 列、canonical session 身份三列（确定性回填）、
  policy/journal/receipts 三表；唯一 uid 索引即碰撞门禁。
- `begin_turn`（switch 路径）：完整差异 compile（含 reset）→ journal
  planned → 端口 plan/apply → confirmed 才提交 receipt+绑定+清 overlay；
  rejected/unknown/缺席均 typed 阻塞且不改动绑定。
- 机制策略进入 overlay 写与 receipt 快照（policy_revision）。
- 名称唯一：NFC+trim+casefold，仅约束新写入；restore 冲突需先改名。
- 插件注册：真实 resource provider + 惰性建库（discovery 零写盘）。

## 遗留缺口（诚实边界，均登记 api-requests.md）

- 真实 Harness 端口、canonical SessionRef 的服务端映射证据：等 harness-api。
- Wire registry 的 HTTP 暴露与 auth 装配：C0 集成（integration-request.md）。
- G09/G12 的"与发送互斥的准入门"服务端半边：等 harness-api/会话所有者。
