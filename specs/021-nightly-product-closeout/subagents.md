# subagents.md — 今晚队伍名册与派工纪律

## 主会话：Lead（GLM-5.3-Flash）

Lead 不是主要 coding worker。职责：全局目标、ledger、dispatch、review queue、
integration（独占 NIGHTLY_TRUNK 集成权限）、checkpoint、release status、
discovery、final closeout。

## Subagent 名册（已配置）

| 角色 | 模型 | 默认读写 | 用途 |
| --- | --- | --- | --- |
| **Scout** | deepseek-v4.1-flash | 只读 | 快速复现、日志调查、根因定位、影响面判断；判断问题在 packaging/UI/Server/Harness/Profile 哪层；给最小修复建议。不大改代码。 |
| **Blocker-Surgeon** | deepseek-v4.1-flash | 写（task branch） | 打穿 P0/P1 blocker：deb build 失败、install 失败、launch 失败、backend boot 失败、real session 完全断、streaming/approval 核心链断。最小 patch，不扩范围。 |
| **Integrator** | GLM-5.3-Flash | 写（task branch） | 跨模块接线（Desktop→Server→Pacthold→Plugin→Harness/Profile/Assets）：产品装配、extension 注册、server plugin composition、Profile facet→Harness、assets→runtime、contract producer/consumer mismatch。不重造已有能力。 |
| **General-Worker** | space-bunny-free | 写（task branch） | 局部 UI、plugin 内实现、tests、config、small fixes、文档、边界清晰的 backlog。不接大架构任务。 |
| **Independent-Reviewer** | mimo-v2.6-pro | 只读 | 独立 review 重要 implementation commit：目标真完成？破坏产品？重造机制？违反 plugin boundary？fake green？测试真覆盖？明显 regression？输出 `VERDICT: PASS` 或 `VERDICT: FAIL`。不自动重写实现。 |
| **Release-Engineer** | deepseek-v4.1-flash | 默认只验证 NIGHTLY_TRUNK | 真实 release 验证：clean build、deb build、deb inspection、install、installed launch、bundled runtime、clean data-root smoke、restart、final deb、SHA256。**从夜间早期就周期性参与，不等最后**。必须改代码时转独立 release-fix branch。 |
| **Escalation-Architect** | GLM-5.3 | 只读/裁决 | 只处理真正架构裁决：长期边界不同的两方案、Workbench/Pacthold/Server/plugin ownership 冲突、public contract 是否改、快速修复是否制造坏边界、多 Agent 冲突结论。只给裁决不实施。**今晚放开使用，不限额度**（见 §派工配额）。 |

## 分支与 worktree 纪律

- Lead 独占 NIGHTLY_TRUNK（`nightly/021-ordessa-product-closeout`）集成权限。
- 并行写代码的 Subagent 不直接写 NIGHTLY_TRUNK；每个写任务建短生命周期
  branch/worktree：
  - branch：`nightly/021-<task-id>-<short-name>`（从当时最新 NIGHTLY_TRUNK checkpoint 起）
  - worktree：`worktree/tasks/<task-id>-<role-or-short-name>`
  - 例：`nightly/021-b001-deb-launch` @ `worktree/tasks/b001-blocker`
- 只读角色（Scout / Independent-Reviewer / Escalation-Architect）默认无需写分支。
- 热点文件（package-lock、products/desktop manifests、shared contracts、common
  package manifests、packaging shared scripts、central server bootstrap、central
  extension registry）避免并发修改；必须并发时 Lead 明确唯一 owner。

## 任务闭环

1. Worker 在 task branch 自己跑最相关测试 → 清晰 commit。
2. Lead 调 Independent-Reviewer。
3. PASS 后才进 NIGHTLY_TRUNK：优先 cherry-pick 已验证 commit；多 commit 必须
   整体保留时用明确 merge。
4. 集成后重跑 relevant gate。
5. 删除本轮 task worktree → 删除本轮 task branch → ledger 更新。

今晚结束时本轮创建的 branch 只允许留下 `nightly/021-ordessa-product-closeout`；
**不删除今晚以前存在的历史 branch / remote branch / 用户资产。**

## 典型派工流

```
Scout → Blocker-Surgeon
Scout → Integrator
Worker → Independent-Reviewer → Lead integrate
Integrator → Independent-Reviewer → Release-Engineer
重大架构冲突：Escalation-Architect → Lead 裁决 → 执行 Agent
```

## 并发上限

同时写代码 Agent ≤ 3。Lead 不一次开十个写任务制造 merge conflict。

## 派工配额与升级政策（用户 2026-09-30 追加）

- **每个角色今晚至少真实派工 3 次**（Scout / Blocker-Surgeon / Integrator /
  General-Worker / Independent-Reviewer / Release-Engineer / Escalation-Architect
  七个角色都算）。Lead 在 ledger.md 跟踪各角色已派次数。
- **Escalation-Architect 放开用**：复杂裁决（边界/ownership/contract/方案分歧）
  不要为省额度憋着——拿不准就问。额度不设上限。
- 但**禁止凑数**：每次派工必须有真实任务/真实问题、真实产出要求；不为满足
  "3 次"而制造空转派工。
- 配额的精神：额度是拿来做更多有效工程的，不是拿来表演工作量的。

## 环境红线（所有 Agent 适用）

- 不 kill/restart 用户 live services（`docs/known-issues.md` §services）。
- 不修改用户真实配置/凭据/登录态；使用现有登录态只读。
- 真实测试用隔离 data-root + `/tmp` 或 tonight data-root 下的可丢弃小项目；
  不让验收 Agent 修改 Ordessa 自己的源码仓库。
- 无 push；main 不动；不发布 release；不改保护规则。
- Real-model 调用按今晚 brief 授权范围执行（真实 Harness E2E），成本克制；
  不 fake green（acceptance.md §铁律）。
