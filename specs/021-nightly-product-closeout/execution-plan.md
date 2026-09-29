# execution-plan.md — 执行波次与时间策略

阶段是推进节奏，不是"做完就停"。全程受 [continuous-operation.md](continuous-operation.md) 约束。

## Phase 0 · Bootstrap（已执行）

- [x] 建 NIGHTLY_TRUNK：`nightly/021-ordessa-product-closeout`
- [x] 建 worktree：`worktree/021-ordessa-product-closeout`
- [x] 写 specs/021 全部控制文档
- [x] 读项目现状（baseline/architecture/known-issues/naming/018/020/装配与打包面）
- [x] 向用户汇报今晚执行计划
- 停：等待用户 `/goal`。

## Phase 1 · Establish Reality（收到 `/goal` 立即执行）

不要一上来大改。先建立真实 baseline：

- current build（`npm ci` / `npm run build` / typecheck）
- current tests（`npm test` 聚合 + Python 关键套件，对照 inherited-red 台账）
- current deb build（`npm run build:deb`）
- deb install（真实安装）+ installed launch
- default product assembly 盘点（重点：`products/desktop/extensions.json` 14 项 vs
  仓库已有能力域——skills/mcp/prompts/permissions/model-provider/memory/lsp/
  subagents/runtime-preferences 目前不在默认装配里，先核实它们是桌面扩展缺装配、
  还是 server 侧插件域，再定接通方案）
- obvious runtime failures

产出：初始 blocker ledger（ledger.md）+ 真实起点证据（evidence.md）。

## Phase 2 · P0 Product Delivery

优先清：build → deb → install → launch → bundled server → plugin assembly →
basic project/session。尽快形成：

- C1 deb-build
- C2 installed-launch

## Phase 3 · First Real Harness

真实 Harness：project → session → prompt → streaming → tool call →
approval（如支持）。形成 C3 first-real-harness。

## Phase 4 · Profile / Assets

重点：Profile、Skill、MCP、permission、provider/model、prompts/instructions、
重要 runtime facets。形成 C4 profile-runtime、C5 skill-mcp。

## Phase 5 · Multi-Harness

第二 Harness 真实验证 → C6 multi-harness。
更多 Harness 环境已认证且成本可接受时继续扩大覆盖。

## Phase 6 · Product Hardening

persistence / restart / error handling / unavailable Harness / auth 额度失败 /
MCP failure / session isolation / UI obvious defects / regression tests。

## Phase 7 · Architecture Cleanup（只有产品绿色后）

只做低/中风险、高价值、可验证、可回滚的清理：business hardcode 移出 host /
明显 contract misuse / plugin cross-import / assembly pollution / dead compat shim。
**不开大型 storage/runtime-compat epic。**

## Phase 8 · Final Closeout

最终冻结（时间策略见下）：收回 Subagent → 合并验证成果 → 放弃高风险未验证
worktree → final build → deb → install → launch → smoke → SHA → report →
branch/worktree 清理。

---

## 时间策略（deadline 08:00 Asia/Shanghai）

| 时点 | 动作 |
| --- | --- |
| 23:53–约 02:00 | Phase 1–2：建立事实、积极修根因，目标 C1/C2 |
| 约02:00–05:00 | Phase 3–5：真实 Harness / Profile / Skill / MCP / Multi-Harness |
| 约05:00–06:30 | Phase 6 hardening；获得第一个可用 Candidate 后继续增强 |
| 约 06:30 | 开始降低风险 |
| 约 06:45 | 禁止新大型重构（状态很好时可做小型高价值修复） |
| 约 07:00 | 进入 final release closeout |
| 07:00–08:00 | 最终预留 45–60 分钟：收回、final build/deb/install/launch/smoke/SHA/report/清理 |

- 项目状态很差时：更早冻结架构工作，全部资源压 deb / runtime / E2E。
- 每个阶段完成后立即回到 continuous-operation.md 循环，**不停**。
- 若高风险修改失败且无法快速修：回滚到最近绿色 checkpoint（checkpoints.md）。
