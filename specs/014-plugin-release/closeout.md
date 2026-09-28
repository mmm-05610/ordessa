# 014 收口并入记录（2026-09-28）

**状态：用户验收通过；四包已并回 1+x 插件分支；阶段工作树与阶段分支已销毁。**
验收口径见各 report（均为诚实 PARTIAL：外部依赖如实登记，未冒充完成）。

## 并回映射

| 014 分支（归档头） | 目标分支（终态 SHA） | 差异路径（全部在己域） |
| --- | --- | --- |
| `014-a-profile` @ `abab9bee89` | `codex/plugin-profile` @ `2c48889a25` | 80（plugins/profile） |
| `014-b-model-provider` @ `346c60b1ef` | `codex/plugin-model-provider` @ `20085c0198` | 76（plugins/assets/model-provider） |
| `014-c-chat` @ `9712a203bd` | `codex/plugin-chat` @ `4d555a09b2` | 27（plugins/chat + plugins/agent） |
| `014-d-harness-claude` @ `d917ddb483` | `codex/plugin-harness` @ `ef554ac63d` | 8（plugins/harness） |

main 侧联合提交：`efcea34e57`（四包 report/tasks 勾选/seams 回填联合、两份
retirement-request、P-C/P-D 探针转录、docs/server-round1 一份）。seams.md 为
b∪c∪d 三路联合；**S-07 命令项两证并存**：PC-10（3 秒窗零
`available_commands_update`）判 absent 在案，P-D 同轮观察到自发播发 ×2（条件
不同），对账归后续波次。

## 处理说明

- 014-b 内部 merge 过 014-a（PB-6 消费 profile-api r2）；并回 model-provider
  时已剥离 `plugins/profile/**` 与 specs，A 的工作只进 profile 分支。
- chat / harness 两支在 012 后已被 main 吸收（integration-core-batch1，差异
  归零）；本次以"main 基 + 己域增量"形态复活，语义与 1+x 一致。
- 四支各补 merge main + 非己域路径对齐 main（合并基推进至 `efcea34e57`），
  消除未来并 main 时的 specs modify/delete 风险；顺带清掉 012 遗留的九份
  tasks.md 假差异（取 main 的"归并≠验收"重置态）。
- **弃置**：014-a 未提交的根 lock 增量（+53，profile 三包 workspace 条目）。
  按执行者 S-02 注记处理：根锁定稿归 INT-02（产品装配侧干净构建重算，连同
  model-provider 两条）；main 上没有对应 workspace 目录，提前提交会弄红
  `npm ci`，故不入 main。
- 完整性检查：四支 `diff(main...)` 非己域路径数=0；profile/model-provider/
  harness 三支 `compileall` 过；chat 为 TS 线，门禁以 P-C report 的 vitest/
  tsc 计数为准（本收口未重跑）。
- 归档：`refs/archive/20260928-014-closeout/heads/{014-a-profile,014-b-model-
  provider,014-c-chat,014-d-harness-claude}`；阶段工作树与阶段分支已删。

## 未随本批（如实）

- **P-E 第二批**（Q5 authority + harness native_evidence → S-06 翻转）未开，
  归下一波次。
- S-08 退役三件事：A③/B①② 清单已交（retirement-request ×2），**执行**归集成
  波次（顺序：退 compat writer → S-03 装配 → 无双写窗口）。
- 生产 admission（S-06）、extensions 装配（S-01/S-03/S-04）、根锁定稿
  （S-02/INT-02）、wire 生产绑定（S-11/INT-01）、发行门依据入库（S-00/INT-05）
  均在 core 侧，见 seams.md。
