# P-A 简报 — profile 解锁与产品就绪

**工作目录**: `worktrees/014-a-profile`（分支 `codex/014-a-profile`，基线 = main 491aa92392 + merge `codex/plugin-profile`，已就位）

**必读输入**（按序）: 本目录 [spec.md](../spec.md)（US1/US5）、[plan.md](../plan.md)（事实 F1/F6/F7、纪律）、[seams.md](../seams.md)、`specs/011-z1-profile/report.md`（完成态权威）、`docs/baseline.md`（环境）、根 `AGENTS.md`。

**目标一句话**: 把已在分支上修好的 profile-api 以 r2 形态正式交付（SHA+元数据），实测解锁 Q1/Q3/Q4/Q5 四条消费线，把桌面三包补到"core 启用即通"，并交付三品牌受控品牌矩阵。

## 写入面（只许这些）

`plugins/profile/**`；`specs/011-plugin-rollout/checkpoints/profile-api.json`；`specs/011-z1-profile/**`（报告/checklist 增补）；`specs/014-plugin-release/**`（含勾选 [tasks.md](../tasks.md) PA-*、写 `reports/P-A-report.md`、更新 S-01/S-09/S-10 状态）。

**禁区**: 其他一切（其他 plugins/、products/、tooling/、packages/、apps/、根锁、兄弟树、main）。发现"必须改禁区才能继续"→ 停该项，在 seams.md 增条目，继续其余任务。

## 任务（详账见 tasks.md PA-1..PA-6）

### PA-2 r2 交付（核心件）
1. 核对修复在位：`plugins/profile/src/ordessa_profile/plugin.py:19-21` 应为 `from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1`（若被合并冲掉则恢复并提交）。
2. 修 `specs/011-plugin-rollout/checkpoints/profile-api.json`：`dependsOn` 填 foundation `8844c475bc`；`planAnchorRef` 指向本线；版本 r2；`implementationSha` = 本树最终实现提交。**不移动**旧 ready ref（4944628f47 与 archived refs 一律不动）。
3. `specs/011-z1-profile/report.md` 增补「014 / profile-api r2」段：修复 SHA、解锁复验结果、交付 SHA。
4. 交付物 = 提交 SHA（012 规则），消费者按 SHA 合并。

### PA-3 四线解锁复验（组合验证，scratch 树，不落本分支）
对每线：`git worktree add` 临时树（基于本分支）→ merge 对应 `codex/plugin-*` → 安装（含 `-e plugins/runtime-compat`、`-e plugins/profile`）→ 跑测试 → 记计数 → 删临时树。期望：

| 线 | merge | 命令 | 期望（旧账口径，漂移须记录原因） |
| --- | --- | --- | --- |
| Q1 skills | `codex/plugin-skills` | `pytest plugins/assets/skills/tests -q` | `test_profile_facet_contribution.py` 6 条 ID 绿（registration_uses_published_facet_api_only / provider_compile_declares_zero / real_resolve_round_trip / read_only_no_writes / absent_profile_refuses / harness_port_absence），整包 433 |
| Q3 subagents | `codex/plugin-subagents` | `pytest plugins/assets/subagents/tests/test_profile_facet_t10.py -q` | 28 条全绿；整包 671 |
| Q4 mcp | `codex/plugin-mcp` | `pytest plugins/assets/mcp -q` | 461 保持；Profile facet（T08）**未实现**——只验证 import 链通，登记缺口不实现 |
| Q5 permissions | 无需 merge（main 已含） | `python -c "import ordessa_profile"` + `pytest plugins/permissions -q` | import 成功；glue（T06 两域）**未实现**——登记缺口不实现 |

### PA-4 桌面三包产品就绪
对照 `plugins/commands`（package.json 带 `ordessa.id` + `manifest.json` `{"id","version","hostApi":"2","entry":"entry.js"}` + `build.mjs`）为 `plugins/profile/{api,frontend,integrations/chat}` 补齐缺件；包内构建演练通过；把启用清单与依赖闭包（profile-chat→chat-api）写回 seams S-01。**不改** products/tooling。

### PA-5 品牌矩阵受控版
- 矩阵：pi / codex / claude-code × {字段投影 golden、会话覆盖/切 Profile 清除、reset 到品牌面、restart-resume 保活}。
- 驱动方式：真实 adapter 接口（经 plugins/harness 的品牌 dialect/渲染面，只读消费），**不是**只调 ProfileDB。
- 环境事实（F5）：codex/claude CLI 本机缺席 → 这两行以受控 fake endpoint 为上限，"真实 CLI 装载格"如实 unknown；Pi 行若本机可用则跑离线受控。
- G18（浏览器几何/200% 缩放/键盘）只列 checklist 不执行（待装配），登记进 report。

## 门与反例（终态前必须全过）

| 门 | 断言 | 反例 |
| --- | --- | --- |
| r2 元数据 | checkpoint JSON dependsOn/implementationSha 有效 | 缺席/空 → 校验必须红 |
| 解锁 | 6+28 条 ID 实测绿 | 组合树跑不了 ≠ 绿；漂移不解释 ≠ 绿 |
| 桌面就绪 | 三包 build 演练出 entry 产物 | 缺 manifest/build.mjs → 门红 |
| 诚实 | PARTIAL 逐条；CLI 缺席如实 unknown | 把受控矩阵写成"三品牌可用"= 假绿，禁止 |
| 回归 | profile 140 口径全绿；继承红零新增 | 新增红未登记 → 不许收口 |

## DoD

实现 + 上述门 + 组合复验计数 + `reports/P-A-report.md`（含所有 SHA、计数、缺口、S 单回填）+ tasks.md PA-* 勾选一致。git：本分支正常提交；**不 push、不 merge 到别处、不动其他树**；子代理只做声明的独立单元且不碰 git/报告。
