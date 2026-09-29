# 021 · Nightly Product Closeout — 控制面入口

> **MORNING_CANDIDATE = YES 不是任务停止条件。**
> 它只是最低可交付产品基线（floor，不是 ceiling）。只要尚未进入最终
> Closeout，Lead 必须继续推进更高完成度。

## 1. Mission

这不是新项目。Ordessa monorepo 已存在大量实现（desktop、server、pacthold、
workbench、插件域、ACP、packaging/deb 等），今晚的任务是在无人值守状态下，
以 Lead + Subagent 队伍持续推进**产品收尾**，直到明早最终 Closeout，产出：

一个真正 **可构建 → 可打包 → 可安装 → 可启动 → 可选择/创建项目 → 可创建会话
→ 可选择 Harness/Profile → Agent 在真实项目中工作 → 流式输出 → Tool Call UI
→ 权限模式与审批 → Profile/Skill/MCP 可用 → 多 Harness → 可作为继续开发基线**
的 Linux amd64 Ordessa `.deb`。

权威验收路径（Real Product > Test Count）：

```
installed deb → normal launch → project → session → Harness/Profile
→ real prompt → streaming → tool call → permission(如支持) → completion
```

优先级：**P0 = 真正可安装、可启动、可使用的 Ordessa Desktop**；
P1 = WorkBench/Pacthold/SDK/Plugin 边界进一步干净。
任何架构优化不得牺牲已获得的产品可用性。

## 2. 事实基线

| 项 | 值 |
| --- | --- |
| 开始时间 | 2026-09-29 23:53 Asia/Shanghai（系统本地即 UTC+8，按本地时间执行） |
| 最终 deadline | 2026-09-30 08:00 Asia/Shanghai |
| NIGHTLY_TRUNK | `nightly/021-ordessa-product-closeout`（对今晚具有 main 地位） |
| main baseline SHA | `b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0`（root worktree 今晚不动） |
| Integration worktree | `/home/maoqh/projects/ordessa/worktree/021-ordessa-product-closeout` |
| 排除方式 | `/worktree/` 经 `.git/info/exclude` 本地排除（不修改项目 `.gitignore`） |
| 真正的 main | 今晚保持不动；一切最终成果只进 NIGHTLY_TRUNK |

## 3. 最高优先级

1. **P0**：deb 可构建、可安装、可启动；bundled server/plugin 正常；无白屏/无限 loading/启动 crash。
2. **P1**：普通 Harness Desktop 主路径 —— project / session / streaming / tool call / permission & approval / 真实 Harness E2E（至少 1 个完整 + 第 2 个真实证据）。
3. **P1/P2**：Profile / Skill / MCP / 既有配置能力接通并真正进入 runtime（禁止"保存成功但 runtime 不消费"）。

## 4. 非目标（今晚不做）

- 全面退休 runtime-compat（020 波 2 是搬家 epic，非删码）。
- 大规模 storage ownership 搬迁；重写 Server/Pacthold；大规模 API redesign；数千行纯架构搬家。
- remote / container / multi-root workspace 新抽象（除非已存在、只是接通）。
- push 远端 / 发布正式 release / 改保护规则；**无 push，main 不动**。
- 修改用户真实配置/凭据/登录态（`~/.codex` 等）；不 kill 用户 live services
  （`docs/known-issues.md` §services）。真实测试一律隔离 data-root + 临时项目。
- 不为凑任务发明新功能；所有任务必须来自现有产品目标、已有实现、已有 spec、真实问题或合理收尾。

## 5. 文档索引

| 文档 | 用途 |
| --- | --- |
| [acceptance.md](acceptance.md) | 产品验收合同（唯一验收口径，checklist） |
| [continuous-operation.md](continuous-operation.md) | 持续推进协议（唯一合法停止条件） |
| [execution-plan.md](execution-plan.md) | 阶段波次与时间策略 |
| [subagents.md](subagents.md) | 队伍名册、派工流与分支纪律 |
| [ledger.md](ledger.md) | blocker/backlog 动态真相源 |
| [checkpoints.md](checkpoints.md) | 绿色 checkpoint 台账（回滚锚点） |
| [evidence.md](evidence.md) | 真实证据登记（命令/退出码/产物/SHA256） |
| [decision-log.md](decision-log.md) | 只记长期有效裁决 |
| [final-report.md](final-report.md) | 晨报模板（Closeout 时填成） |

## 6. 当前运行阶段

Phase 0 Bootstrap（本目录建立并提交）→ 等待用户 `/goal` → Phase 1 Establish
Reality → 后续按 execution-plan.md 波次推进。

## 7. Morning Candidate 定义

见 [acceptance.md](acceptance.md) §Morning Candidate：18 条**同时满足**才允许写
`MORNING_CANDIDATE = YES`。达成后立即形成 C-MC1 绿色 checkpoint，然后继续：
扩大真实 Harness 覆盖 → 补 Profile/Skill/MCP/assets → 修 UX/error handling →
增加 installed-product smoke → 低风险架构债 → regression tests → 清理，
直到最终 Closeout。后续 Candidate 不得比前一个差。

## 8. Continuous Operation 原则

见 [continuous-operation.md](continuous-operation.md)。唯一正常结束方式：
A 用户叫停 / B 最终 Closeout 完成 / C 环境完全不可用 / D 仓库内合理任务穷尽
（≥2 轮主动巡检无任务）。单个 blocker、单个 Worker 返回、单个测试失败、
某个 Harness 不可用、Morning Candidate 达成、显式 backlog 做完——均**不**构成
停止条件。Lead 永久维护 NOW / NEXT / REVIEW / VERIFY / BACKLOG 工作队列。
